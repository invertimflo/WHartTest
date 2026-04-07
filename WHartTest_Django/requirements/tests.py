from unittest.mock import patch
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
import os
import tempfile
import time

from projects.models import Project, ProjectMember

from .models import DocumentImage, RequirementDocument
from .services import DocumentProcessor


class DocxEditorSessionActionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)
        self.user = User.objects.create_user(username="tester", password="password123")
        change_perm = Permission.objects.get(codename="change_requirementdocument")
        self.user.user_permissions.add(change_perm)

        self.project = Project.objects.create(name="Demo Project", creator=self.user)
        ProjectMember.objects.create(project=self.project, user=self.user, role="member")
        self.client.force_authenticate(self.user)

        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="Word Requirement",
            document_type="docx",
            file=SimpleUploadedFile(
                "requirement.docx",
                b"word-content",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            uploader=self.user,
        )
        self.url = reverse(
            "requirement-documents-create-docx-editor-session",
            kwargs={"pk": self.document.id},
        )

    def test_returns_iframe_url_for_word_document(self):
        with patch("requirements.views.create_docx_editor_session") as create_session:
            create_session.return_value = {
                "launch_url": "http://docx.example/embed/binding-1?token=abc",
                "expires_at": "2026-04-03T12:00:00Z",
            }
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["iframe_url"], "http://docx.example/embed/binding-1?token=abc")
        self.assertEqual(response.data["document_id"], str(self.document.id))
        self.assertEqual(
            create_session.call_args.kwargs["pushback_url"],
            f"/api/requirements/documents/{self.document.id}/upload-edited-file/",
        )

    def test_rejects_non_word_documents(self):
        self.document.document_type = "pdf"
        self.document.file = SimpleUploadedFile("requirement.pdf", b"pdf", content_type="application/pdf")
        self.document.save(update_fields=["document_type", "file"])

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("仅 Word 文档支持在线编辑", response.data["error"])


class UploadEditedFileActionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)
        self.user = User.objects.create_user(username="editor", password="password123")
        change_perm = Permission.objects.get(codename="change_requirementdocument")
        self.user.user_permissions.add(change_perm)

        self.project = Project.objects.create(name="Upload Project", creator=self.user)
        ProjectMember.objects.create(project=self.project, user=self.user, role="member")
        self.client.force_authenticate(self.user)

        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="Editable Requirement",
            document_type="docx",
            file=SimpleUploadedFile(
                "initial.docx",
                b"initial-content",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            uploader=self.user,
        )
        self.url = reverse(
            "requirement-documents-upload-edited-file",
            kwargs={"pk": self.document.id},
        )

    def test_upload_edited_file_refreshes_updated_at(self):
        updated_at_before = self.document.updated_at
        time.sleep(0.02)

        with patch(
            "requirements.services.DocumentProcessor.extract_content",
            return_value="edited content",
        ) as extract_content:
            response = self.client.post(
                self.url,
                data={
                    "file": SimpleUploadedFile(
                        "edited.docx",
                        b"edited-content",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                format="multipart",
            )

        self.document.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.document.content, "edited content")
        self.assertGreater(self.document.updated_at, updated_at_before)
        self.assertTrue(extract_content.called)
        self.assertEqual(extract_content.call_args.kwargs.get("force_file"), True)

    def test_upload_edited_file_replaces_existing_content_and_resets_status(self):
        self.document.content = "stale content"
        self.document.status = "ready_for_review"
        self.document.word_count = len(self.document.content)
        self.document.page_count = 3
        self.document.save(
            update_fields=["content", "status", "word_count", "page_count", "updated_at"]
        )

        with patch(
            "requirements.services.DocumentProcessor.extract_content",
            return_value="",
        ):
            response = self.client.post(
                self.url,
                data={
                    "file": SimpleUploadedFile(
                        "edited.docx",
                        b"edited-content",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                format="multipart",
            )

        self.document.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.document.content, "")
        self.assertEqual(self.document.word_count, 0)
        self.assertEqual(self.document.page_count, 1)
        self.assertEqual(self.document.status, "uploaded")


class DocumentProcessorImageCleanupTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

        self.user = User.objects.create_user(username="image-cleaner", password="password123")
        self.project = Project.objects.create(name="Image Project", creator=self.user)
        ProjectMember.objects.create(project=self.project, user=self.user, role="member")
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="Image Requirement",
            document_type="docx",
            uploader=self.user,
            has_images=True,
            image_count=2,
        )

    def test_clear_document_images_removes_existing_records_and_resets_stats(self):
        image_one = DocumentImage.objects.create(
            document=self.document,
            image_id="img_000",
            order=0,
            content_type="image/png",
            file_size=3,
            image_file=SimpleUploadedFile("img-000.png", b"one", content_type="image/png"),
        )
        image_two = DocumentImage.objects.create(
            document=self.document,
            image_id="img_001",
            order=1,
            content_type="image/png",
            file_size=3,
            image_file=SimpleUploadedFile("img-001.png", b"two", content_type="image/png"),
        )
        image_one_path = image_one.image_file.path
        image_two_path = image_two.image_file.path

        processor = DocumentProcessor()
        processor._clear_document_images(self.document)
        self.document.refresh_from_db()

        self.assertFalse(DocumentImage.objects.filter(document=self.document).exists())
        self.assertFalse(self.document.has_images)
        self.assertEqual(self.document.image_count, 0)
        self.assertFalse(os.path.exists(image_one_path))
        self.assertFalse(os.path.exists(image_two_path))

    def test_append_image_placeholder_skips_consecutive_duplicate_rids(self):
        processor = DocumentProcessor()
        content_parts = []
        image_rids = []
        image_order = 0

        image_order = processor._append_image_placeholder(
            content_parts, image_rids, "rId10", image_order
        )
        image_order = processor._append_image_placeholder(
            content_parts, image_rids, "rId10", image_order
        )
        image_order = processor._append_image_placeholder(
            content_parts, image_rids, "rId11", image_order
        )

        self.assertEqual(image_order, 2)
        self.assertEqual(image_rids, ["rId10", "rId11"])
        self.assertEqual(
            content_parts,
            [
                "\n![图片](docimg://img_000)\n",
                "\n![图片](docimg://img_001)\n",
            ],
        )


class RequirementDocumentImageAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

        self.user = User.objects.create_user(username="image-viewer", password="password123")
        self.project = Project.objects.create(name="Image Access Project", creator=self.user)
        ProjectMember.objects.create(project=self.project, user=self.user, role="member")
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="Image Access Requirement",
            document_type="docx",
            uploader=self.user,
            has_images=True,
            image_count=1,
        )

    def test_get_image_returns_latest_duplicate_record(self):
        DocumentImage.objects.create(
            document=self.document,
            image_id="img_000",
            order=0,
            content_type="image/png",
            file_size=3,
            image_file=SimpleUploadedFile("old.png", b"old", content_type="image/png"),
        )
        time.sleep(0.02)
        DocumentImage.objects.create(
            document=self.document,
            image_id="img_000",
            order=0,
            content_type="image/png",
            file_size=3,
            image_file=SimpleUploadedFile("new.png", b"new", content_type="image/png"),
        )

        url = reverse(
            "requirement-documents-get-image",
            kwargs={"pk": self.document.id, "image_id": "img_000"},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"new")
