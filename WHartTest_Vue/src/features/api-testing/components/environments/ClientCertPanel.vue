<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useAppI18n } from '@/composables/useAppI18n'
import { useProjectStore } from '@/store/projectStore'
import { useThemeStore } from '@/store/themeStore'
import { fileService } from '@/features/file-management/services/fileService'
import {
  getClientCertificates,
  createClientCertificate,
  updateClientCertificate,
  deleteClientCertificate,
  validateClientCertificate,
  type ClientCertificate
} from '../../services/clientCertificateService'
import {
  IconPlus,
  IconEdit,
  IconDelete,
  IconLink,
  IconInfoCircle,
  IconExclamationCircle,
  IconSafe,
  IconUpload,
  IconCheckCircle
} from '@arco-design/web-vue/es/icon'

const projectStore = useProjectStore()
const themeStore = useThemeStore()
const { isEnglish, tl } = useAppI18n()
const isDarkTheme = computed(() => themeStore.isBlack)

const certificates = ref<ClientCertificate[]>([])
const loading = ref(false)
const showFormModal = ref(false)
const formLoading = ref(false)
const validating = ref(false)
const editingId = ref<number | null>(null)
const activeAction = ref<'validate' | 'edit' | 'delete' | null>(null)
const activeConfigId = ref<number | null>(null)

const panelText = computed(() => isEnglish.value
  ? {
      infoLine1: 'Client certificates are stored per project and referenced by API / UI environments',
      infoLine2: 'Supports PEM (certificate + private key) and PKCS#12 (.pfx/.p12 single file)',
      infoLine3: 'Passphrases are encrypted at rest and never displayed again once saved',
      title: 'Client Certificates',
      add: 'Add Certificate',
      empty: 'No client certificates yet',
      emptyHint: 'Add a certificate to test HTTPS sites that require mutual TLS (mTLS)',
      type: 'Type',
      certFile: 'Certificate',
      keyFile: 'Private Key',
      passphrase: 'Passphrase',
      hasPassphrase: 'Configured',
      noPassphrase: 'None',
      disabled: 'Disabled',
      validate: 'Validate',
      edit: 'Edit',
      delete: 'Delete',
      description: 'Description',
      createTitle: 'Add Client Certificate',
      editTitle: 'Edit Client Certificate',
      create: 'Create',
      save: 'Save',
      cancel: 'Cancel',
      nameLabel: 'Certificate Name',
      namePlaceholder: 'e.g. Staging mTLS client cert',
      typeLabel: 'Certificate Type',
      typePem: 'PEM (certificate + private key)',
      typePkcs12: 'PKCS#12 (.pfx / .p12)',
      certFileLabel: 'Certificate File',
      keyFileLabel: 'Private Key File',
      uploadHintCert: 'Select the certificate file (.pem/.crt/.cer or .pfx/.p12)',
      uploadHintKey: 'Select the private key file (.key/.pem)',
      replaceFile: 'Replace',
      passphraseLabel: 'Passphrase',
      passphrasePlaceholder: 'Leave blank for an unencrypted private key',
      passphraseKeepHint: 'A passphrase is already saved. Leave blank to keep it unchanged.',
      clearPassphrase: 'Clear the saved passphrase',
      descriptionPlaceholder: 'Optional note',
      enableConfig: 'Enable this certificate',
      requiredCertFile: 'Please upload a certificate file',
      requiredKeyFile: 'A private key file is required for PEM certificates',
      requiredName: 'Please enter a certificate name',
      uploadFailed: 'Failed to upload file',
      fetchFailed: 'Failed to load client certificates',
      createSuccess: 'Client certificate created',
      createFailed: 'Failed to create client certificate',
      updateSuccess: 'Client certificate updated',
      updateFailed: 'Failed to update client certificate',
      deleteSuccess: 'Client certificate deleted',
      deleteFailed: 'Failed to delete client certificate',
      validateSuccess: 'Certificate is usable',
      validateFailed: 'Certificate has issues',
      validateError: 'Failed to validate certificate',
      confirmDeleteTitle: 'Confirm deletion',
      confirmDeleteContent: (name: string) => `Delete client certificate "${name}"? Environments referencing it will stop sending it.`,
      confirmDeleteAction: 'Delete',
    }
  : {
      infoLine1: '客户端证书按项目统一保管，接口自动化 / UI 自动化环境通过引用使用',
      infoLine2: '支持 PEM（证书+私钥两文件）与 PKCS#12（.pfx / .p12 单文件）两种形态',
      infoLine3: '口令加密存储，保存后不再回显',
      title: '客户端证书',
      add: '添加证书',
      empty: '暂无客户端证书',
      emptyHint: '添加证书后即可测试要求客户端证书（mTLS）的 HTTPS 站点',
      type: '类型',
      certFile: '证书',
      keyFile: '私钥',
      passphrase: '口令',
      hasPassphrase: '已配置',
      noPassphrase: '无',
      disabled: '已禁用',
      validate: '校验',
      edit: '编辑',
      delete: '删除',
      description: '描述',
      createTitle: '添加客户端证书',
      editTitle: '编辑客户端证书',
      create: '创建',
      save: '保存',
      cancel: '取消',
      nameLabel: '证书名称',
      namePlaceholder: '如：预发环境 mTLS 客户端证书',
      typeLabel: '证书类型',
      typePem: 'PEM（证书 + 私钥）',
      typePkcs12: 'PKCS#12（.pfx / .p12）',
      certFileLabel: '证书文件',
      keyFileLabel: '私钥文件',
      uploadHintCert: '请选择证书文件（.pem/.crt/.cer 或 .pfx/.p12）',
      uploadHintKey: '请选择私钥文件（.key/.pem）',
      replaceFile: '重新选择',
      passphraseLabel: '证书口令',
      passphrasePlaceholder: '私钥未加密时留空',
      passphraseKeepHint: '已保存口令，留空表示保持不变',
      clearPassphrase: '清除已保存的口令',
      descriptionPlaceholder: '可选备注',
      enableConfig: '启用该证书',
      requiredCertFile: '请上传证书文件',
      requiredKeyFile: 'PEM 类型必须上传私钥文件',
      requiredName: '请输入证书名称',
      uploadFailed: '文件上传失败',
      fetchFailed: '获取客户端证书列表失败',
      createSuccess: '创建客户端证书成功',
      createFailed: '创建客户端证书失败',
      updateSuccess: '更新客户端证书成功',
      updateFailed: '更新客户端证书失败',
      deleteSuccess: '删除客户端证书成功',
      deleteFailed: '删除客户端证书失败',
      validateSuccess: '证书可用',
      validateFailed: '证书存在问题',
      validateError: '客户端证书校验失败',
      confirmDeleteTitle: '确认删除',
      confirmDeleteContent: (name: string) => `确定要删除客户端证书 "${name}" 吗？引用该证书的环境将不再下发它。`,
      confirmDeleteAction: '删除',
    }
)

const translateErrorMessage = (message: unknown) => (
  typeof message === 'string' && message.trim() ? tl(message) : null
)

const typeLabel = (type: string) => (type === 'pkcs12' ? 'PKCS#12' : 'PEM')

// ---------------------------------------------------------------------------
// 列表
// ---------------------------------------------------------------------------

const normalizeList = (payload: any): ClientCertificate[] => {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.results)) return payload.results
  return []
}

const fetchCertificates = async () => {
  if (!projectStore.currentProjectId) {
    certificates.value = []
    return
  }
  try {
    loading.value = true
    const response: any = await getClientCertificates(Number(projectStore.currentProjectId))
    certificates.value = normalizeList(response?.data)
  } catch (error: any) {
    Message.error(
      translateErrorMessage(error?.response?.data?.message)
      || translateErrorMessage(error?.message)
      || panelText.value.fetchFailed
    )
    certificates.value = []
  } finally {
    loading.value = false
  }
}

watch(() => projectStore.currentProjectId, () => { fetchCertificates() })

// ---------------------------------------------------------------------------
// 表单
// ---------------------------------------------------------------------------

interface CertFormState {
  name: string
  cert_type: 'pem' | 'pkcs12'
  cert_file: number | null
  cert_file_name: string
  key_file: number | null
  key_file_name: string
  passphrase: string
  clear_passphrase: boolean
  description: string
  is_active: boolean
}

const formData = ref<CertFormState>(emptyForm())
const certInputRef = ref<HTMLInputElement | null>(null)
const keyInputRef = ref<HTMLInputElement | null>(null)
const uploadingCert = ref(false)
const uploadingKey = ref(false)

function emptyForm(): CertFormState {
  return {
    name: '',
    cert_type: 'pem',
    cert_file: null,
    cert_file_name: '',
    key_file: null,
    key_file_name: '',
    passphrase: '',
    clear_passphrase: false,
    description: '',
    is_active: true,
  }
}

const currentHasPassphrase = computed(() => {
  if (!editingId.value) return false
  return !!(certificates.value.find((item) => item.id === editingId.value)?.has_passphrase)
})

const openCreate = () => {
  editingId.value = null
  formData.value = emptyForm()
  formData.value.cert_type = 'pem'
  showFormModal.value = true
}

const openEdit = (config: ClientCertificate) => {
  activeAction.value = 'edit'
  activeConfigId.value = config.id
  editingId.value = config.id
  formData.value = {
    name: config.name || '',
    cert_type: (config.cert_type as 'pem' | 'pkcs12') || 'pem',
    cert_file: config.cert_file ?? null,
    cert_file_name: config.cert_file_info?.name || '',
    key_file: config.key_file ?? null,
    key_file_name: config.key_file_info?.name || '',
    passphrase: '',
    clear_passphrase: false,
    description: config.description || '',
    is_active: config.is_active !== false,
  }
  showFormModal.value = true
}

const handleTypeChange = () => {
  if (formData.value.cert_type === 'pkcs12') {
    // PKCS#12 把证书与私钥打包在同一个文件里
    formData.value.key_file = null
    formData.value.key_file_name = ''
  }
}

const uploadFile = async (file: File): Promise<{ id: number; name: string } | null> => {
  const res: any = await fileService.upload(projectStore.currentProjectId as number, [file])
  const payload = res?.data?.data || res?.data || res
  const asset = Array.isArray(payload) ? payload[0] : payload
  if (!asset) return null
  return { id: asset.file_id || asset.id, name: asset.original_name || asset.name || file.name }
}

const handleCertFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploadingCert.value = true
  try {
    const uploaded = await uploadFile(file)
    if (uploaded) {
      formData.value.cert_file = uploaded.id
      formData.value.cert_file_name = uploaded.name
    }
  } catch (error: any) {
    Message.error(translateErrorMessage(error?.error) || panelText.value.uploadFailed)
  } finally {
    uploadingCert.value = false
    input.value = ''
  }
}

const handleKeyFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploadingKey.value = true
  try {
    const uploaded = await uploadFile(file)
    if (uploaded) {
      formData.value.key_file = uploaded.id
      formData.value.key_file_name = uploaded.name
    }
  } catch (error: any) {
    Message.error(translateErrorMessage(error?.error) || panelText.value.uploadFailed)
  } finally {
    uploadingKey.value = false
    input.value = ''
  }
}

const buildPayload = () => {
  const payload: Record<string, any> = {
    name: formData.value.name.trim(),
    cert_type: formData.value.cert_type,
    cert_file: formData.value.cert_file,
    key_file: formData.value.cert_type === 'pkcs12' ? null : formData.value.key_file,
    description: formData.value.description,
    is_active: formData.value.is_active,
  }
  if (formData.value.clear_passphrase) {
    payload.clear_passphrase = true
  } else if (formData.value.passphrase) {
    payload.passphrase = formData.value.passphrase
  }
  return payload
}

const validateForm = (): string | null => {
  if (!formData.value.name.trim()) return panelText.value.requiredName
  if (!formData.value.cert_file) return panelText.value.requiredCertFile
  if (formData.value.cert_type === 'pem' && !formData.value.key_file) return panelText.value.requiredKeyFile
  return null
}

const submitForm = async () => {
  const error = validateForm()
  if (error) {
    Message.warning(error)
    return
  }
  try {
    formLoading.value = true
    const payload = buildPayload()
    if (editingId.value) {
      await updateClientCertificate(editingId.value, payload)
      Message.success(panelText.value.updateSuccess)
    } else {
      await createClientCertificate({ ...payload, project: Number(projectStore.currentProjectId) })
      Message.success(panelText.value.createSuccess)
    }
    showFormModal.value = false
    await fetchCertificates()
  } catch (err: any) {
    const firstFieldError = err?.response?.data
      ? Object.values(err.response.data)?.[0]
      : null
    Message.error(
      translateErrorMessage(Array.isArray(firstFieldError) ? firstFieldError[0] : firstFieldError)
      || translateErrorMessage(err?.response?.data?.message)
      || translateErrorMessage(err?.message)
      || (editingId.value ? panelText.value.updateFailed : panelText.value.createFailed)
    )
  } finally {
    formLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// 校验 / 删除
// ---------------------------------------------------------------------------

const handleValidate = async (config: ClientCertificate) => {
  activeAction.value = 'validate'
  activeConfigId.value = config.id
  try {
    validating.value = true
    const response: any = await validateClientCertificate(config.id)
    const result = response?.data || {}
    if (result.valid) {
      Message.success(panelText.value.validateSuccess)
    } else {
      const warnings: string[] = Array.isArray(result.warnings) ? result.warnings : []
      Modal.warning({
        title: panelText.value.validateFailed,
        content: warnings.map((item) => tl(item)).join('\n') || panelText.value.validateFailed,
        okText: panelText.value.cancel,
      })
    }
  } catch (error: any) {
    Message.error(
      translateErrorMessage(error?.response?.data?.message)
      || translateErrorMessage(error?.message)
      || panelText.value.validateError
    )
  } finally {
    validating.value = false
    setTimeout(() => {
      activeAction.value = null
      activeConfigId.value = null
    }, 500)
  }
}

const handleDelete = (config: ClientCertificate) => {
  activeAction.value = 'delete'
  activeConfigId.value = config.id
  Modal.warning({
    title: panelText.value.confirmDeleteTitle,
    content: panelText.value.confirmDeleteContent(config.name),
    okText: panelText.value.confirmDeleteAction,
    cancelText: panelText.value.cancel,
    onOk: async () => {
      try {
        loading.value = true
        await deleteClientCertificate(config.id)
        Message.success(panelText.value.deleteSuccess)
        await fetchCertificates()
      } catch (error: any) {
        Message.error(
          translateErrorMessage(error?.response?.data?.message)
          || translateErrorMessage(error?.message)
          || panelText.value.deleteFailed
        )
      } finally {
        loading.value = false
      }
    }
  })
}

onMounted(() => {
  if (projectStore.currentProjectId) {
    fetchCertificates()
  }
})

defineExpose({ handleCreate: openCreate })
</script>

<template>
  <div class="client-cert-panel h-full overflow-hidden flex flex-col" :class="isDarkTheme ? 'client-cert--dark' : 'client-cert--light'">
    <!-- 说明信息卡片 -->
    <div class="info-card p-4 text-sm space-y-2 mb-4 rounded-lg flex-shrink-0">
      <div class="flex items-start gap-2">
        <icon-info-circle class="text-blue-400 mt-0.5 flex-shrink-0" />
        <div>{{ panelText.infoLine1 }}</div>
      </div>
      <div class="flex items-start gap-2">
        <icon-link class="text-teal-400 mt-0.5 flex-shrink-0" />
        <div>{{ panelText.infoLine2 }}</div>
      </div>
      <div class="flex items-start gap-2">
        <icon-exclamation-circle class="text-amber-400 mt-0.5 flex-shrink-0" />
        <div>{{ panelText.infoLine3 }}</div>
      </div>
    </div>

    <!-- 列表标题 -->
    <div class="flex items-center gap-2 mb-4 flex-shrink-0">
      <icon-safe class="panel-title-icon" />
      <span class="panel-title-text font-medium">{{ panelText.title }}</span>
      <a-button
        size="mini"
        type="text"
        class="ml-auto panel-action-btn"
        @click="openCreate"
      >
        <template #icon><icon-plus class="panel-action-icon" /></template>
        {{ panelText.add }}
      </a-button>
    </div>

    <!-- 列表内容 -->
    <div class="flex-1 overflow-y-auto pr-1 custom-scrollbar">
      <a-spin :loading="loading" dot class="w-full">
        <div class="space-y-2 pb-4">
          <div
            v-for="config in certificates"
            :key="config.id"
            class="config-card p-3 rounded-lg border transition-all duration-300"
            :class="{ 'opacity-60': !config.is_active }"
          >
            <div class="flex items-center gap-3 w-full">
              <div class="config-icon-shell w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0">
                <icon-safe class="text-emerald-500" />
              </div>

              <div class="config-value-shell flex-1 min-w-0 px-4 py-2 rounded text-sm">
                <div class="flex items-center flex-wrap gap-x-5 gap-y-1">
                  <span class="config-name font-semibold">{{ config.name }}</span>
                  <span class="type-tag">{{ typeLabel(config.cert_type) }}</span>

                  <span class="meta-item">
                    <span class="config-meta-label text-xs font-medium mr-1">{{ panelText.certFile }}:</span>
                    <span class="config-meta-value">{{ config.cert_file_info?.name || '-' }}</span>
                  </span>

                  <span v-if="config.cert_type === 'pem'" class="meta-item">
                    <span class="config-meta-label text-xs font-medium mr-1">{{ panelText.keyFile }}:</span>
                    <span class="config-meta-value">{{ config.key_file_info?.name || '-' }}</span>
                  </span>

                  <span class="meta-item">
                    <span class="config-meta-label text-xs font-medium mr-1">{{ panelText.passphrase }}:</span>
                    <a-tag v-if="config.has_passphrase" size="small" color="orange">{{ panelText.hasPassphrase }}</a-tag>
                    <span v-else class="config-meta-value">{{ panelText.noPassphrase }}</span>
                  </span>

                  <span v-if="!config.is_active" class="config-disabled-tag text-xs px-1.5 py-0.5 rounded">{{ panelText.disabled }}</span>
                </div>
              </div>

              <div class="flex flex-shrink-0 flex-nowrap ml-auto gap-2 button-group">
                <a-button
                  type="text"
                  size="mini"
                  @click.stop="handleValidate(config)"
                  :loading="validating && activeConfigId === config.id"
                  :class="{ 'active-button': activeAction === 'validate' && activeConfigId === config.id }"
                >
                  <template #icon><icon-check-circle /></template>
                  {{ panelText.validate }}
                </a-button>
                <a-button
                  type="text"
                  size="mini"
                  @click.stop="openEdit(config)"
                  :class="{ 'active-button': activeAction === 'edit' && activeConfigId === config.id }"
                >
                  <template #icon><icon-edit /></template>
                  {{ panelText.edit }}
                </a-button>
                <a-button
                  type="text"
                  size="mini"
                  status="danger"
                  @click.stop="handleDelete(config)"
                  :class="{ 'active-button': activeAction === 'delete' && activeConfigId === config.id }"
                >
                  <template #icon><icon-delete /></template>
                  {{ panelText.delete }}
                </a-button>
              </div>
            </div>

            <div v-if="config.description" class="config-description mt-2 text-xs px-2 py-1 pl-3">
              <span class="config-meta-label">{{ panelText.description }}:</span>
              <span class="config-meta-value ml-2">{{ config.description }}</span>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="!certificates.length && !loading" class="text-center py-10 px-4 flex flex-col items-center">
            <div class="empty-state-icon-shell w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
              <icon-safe class="text-emerald-500 text-2xl" />
            </div>
            <div class="empty-state-title text-base mb-2">{{ panelText.empty }}</div>
            <div class="empty-state-description text-sm mb-6 max-w-md mx-auto">{{ panelText.emptyHint }}</div>
            <a-button type="outline" @click="openCreate">
              <template #icon><icon-plus /></template>
              {{ panelText.add }}
            </a-button>
          </div>
        </div>
      </a-spin>
    </div>

    <!-- 新建 / 编辑弹窗 -->
    <a-modal
      v-model:visible="showFormModal"
      :title="editingId ? panelText.editTitle : panelText.createTitle"
      @cancel="showFormModal = false"
      @ok="submitForm"
      :ok-loading="formLoading"
      :ok-text="editingId ? panelText.save : panelText.create"
      :cancel-text="panelText.cancel"
      :mask-closable="false"
      :unmount-on-close="false"
      modal-class="config-modal"
      :width="620"
    >
      <a-form :model="formData" layout="vertical">
        <a-form-item field="name" :label="panelText.nameLabel" required>
          <a-input v-model="formData.name" :placeholder="panelText.namePlaceholder" allow-clear />
        </a-form-item>

        <a-form-item field="cert_type" :label="panelText.typeLabel" required>
          <a-radio-group v-model="formData.cert_type" @change="handleTypeChange">
            <a-radio value="pem">{{ panelText.typePem }}</a-radio>
            <a-radio value="pkcs12">{{ panelText.typePkcs12 }}</a-radio>
          </a-radio-group>
        </a-form-item>

        <a-form-item :label="panelText.certFileLabel" required>
          <div class="upload-row">
            <input ref="certInputRef" type="file" class="hidden-input" @change="handleCertFileChange" />
            <a-button size="small" type="outline" :loading="uploadingCert" @click="certInputRef?.click()">
              <template #icon><icon-upload /></template>
              {{ formData.cert_file_name ? panelText.replaceFile : panelText.uploadHintCert }}
            </a-button>
            <span v-if="formData.cert_file_name" class="upload-file-name">{{ formData.cert_file_name }}</span>
          </div>
        </a-form-item>

        <a-form-item v-if="formData.cert_type === 'pem'" :label="panelText.keyFileLabel" required>
          <div class="upload-row">
            <input ref="keyInputRef" type="file" class="hidden-input" @change="handleKeyFileChange" />
            <a-button size="small" type="outline" :loading="uploadingKey" @click="keyInputRef?.click()">
              <template #icon><icon-upload /></template>
              {{ formData.key_file_name ? panelText.replaceFile : panelText.uploadHintKey }}
            </a-button>
            <span v-if="formData.key_file_name" class="upload-file-name">{{ formData.key_file_name }}</span>
          </div>
        </a-form-item>

        <a-form-item field="passphrase" :label="panelText.passphraseLabel">
          <a-input-password
            v-model="formData.passphrase"
            :placeholder="currentHasPassphrase ? panelText.passphraseKeepHint : panelText.passphrasePlaceholder"
            :disabled="formData.clear_passphrase"
            allow-clear
          />
          <a-checkbox
            v-if="currentHasPassphrase"
            v-model="formData.clear_passphrase"
            class="mt-2"
            @change="() => { if (formData.clear_passphrase) formData.passphrase = '' }"
          >
            {{ panelText.clearPassphrase }}
          </a-checkbox>
        </a-form-item>

        <a-form-item field="description" :label="panelText.description">
          <a-textarea v-model="formData.description" :placeholder="panelText.descriptionPlaceholder" />
        </a-form-item>

        <a-form-item field="is_active">
          <a-checkbox v-model="formData.is_active">{{ panelText.enableConfig }}</a-checkbox>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style lang="postcss" scoped>
.client-cert-panel {
  --cc-text: var(--color-text-1);
  --cc-text-subtle: var(--color-text-3);
  --cc-card-bg: rgba(255, 255, 255, 0.88);
  --cc-card-border: rgba(148, 163, 184, 0.18);
  --cc-card-hover-border: rgba(16, 185, 129, 0.45);
  --cc-info-bg: linear-gradient(135deg, rgba(236, 253, 245, 0.96), rgba(248, 250, 252, 0.96));
  --cc-value-bg: rgba(248, 250, 252, 0.94);
  --cc-value-border: rgba(148, 163, 184, 0.16);
  --cc-name-text: rgb(5, 150, 105);
  --cc-tag-bg: rgba(209, 250, 229, 0.85);
  --cc-tag-text: rgba(4, 120, 87, 0.92);
  --cc-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
}

.client-cert--dark {
  --cc-text: rgba(229, 231, 235, 0.94);
  --cc-text-subtle: rgba(156, 163, 175, 0.96);
  --cc-card-bg: rgba(17, 24, 39, 0.6);
  --cc-card-border: rgba(55, 65, 81, 1);
  --cc-card-hover-border: rgba(16, 185, 129, 0.6);
  --cc-info-bg: linear-gradient(to right, rgba(30, 41, 59, 0.7), rgba(30, 41, 59, 0.5));
  --cc-value-bg: rgba(31, 41, 55, 0.5);
  --cc-value-border: rgba(75, 85, 99, 0.3);
  --cc-name-text: rgb(52, 211, 153);
  --cc-tag-bg: rgba(55, 65, 81, 0.8);
  --cc-tag-text: rgb(156, 163, 175);
  --cc-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.info-card {
  font-size: 0.875rem;
  background: var(--cc-info-bg);
  border: 1px solid var(--cc-card-border);
  color: var(--cc-text-subtle);
}

.panel-title-icon,
.panel-action-icon,
.config-meta-label,
.empty-state-description {
  color: var(--cc-text-subtle);
}

.panel-title-text,
.empty-state-title,
.config-meta-value {
  color: var(--cc-text);
}

.config-name {
  color: var(--cc-name-text);
}

.config-icon-shell,
.empty-state-icon-shell {
  background: rgba(16, 185, 129, 0.1);
}

.config-card {
  background: var(--cc-card-bg);
  border-color: var(--cc-card-border);
  box-shadow: var(--cc-shadow);

  &:hover {
    border-color: var(--cc-card-hover-border);
    transform: translateY(-2px);
  }
}

.config-value-shell {
  background: var(--cc-value-bg);
  border: 1px solid var(--cc-value-border);
  color: var(--cc-text);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.type-tag {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--cc-tag-text);
  background-color: var(--cc-tag-bg);
  padding: 3px 6px;
  line-height: 1;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  letter-spacing: 0.05em;
}

.config-disabled-tag {
  color: #ef4444;
  background-color: rgba(239, 68, 68, 0.1);
}

.config-description {
  border-left: 2px solid var(--cc-value-border);
  color: var(--cc-text-subtle);
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.upload-file-name {
  font-size: 12px;
  color: var(--cc-text-subtle);
  word-break: break-all;
}

.hidden-input {
  display: none;
}

.custom-scrollbar {
  scrollbar-width: none;
  -ms-overflow-style: none;

  &::-webkit-scrollbar {
    display: none;
  }
}
</style>
