import { request } from '@/utils/request';
import { useProjectStore } from '@/store/projectStore';
import type { ApiClientCertificate, ClientCertValidationResult } from '../types/clientCertificate';
import { wrapListResponse, wrapOneResponse } from './responseHelpers';

const base = (projectId: number) => `/projects/${projectId}/client-certificates`;

export const clientCertificateService = {
  list: (projectId: number, params?: Record<string, any>) =>
    request<ApiClientCertificate[]>({ url: `${base(projectId)}/`, method: 'GET', params }),

  get: (projectId: number, id: number) =>
    request<ApiClientCertificate>({ url: `${base(projectId)}/${id}/`, method: 'GET' }),

  create: (projectId: number, data: Partial<ApiClientCertificate>) =>
    request<ApiClientCertificate>({ url: `${base(projectId)}/`, method: 'POST', data }),

  update: (projectId: number, id: number, data: Partial<ApiClientCertificate>) =>
    request<ApiClientCertificate>({ url: `${base(projectId)}/${id}/`, method: 'PUT', data }),

  patch: (projectId: number, id: number, data: Partial<ApiClientCertificate>) =>
    request<ApiClientCertificate>({ url: `${base(projectId)}/${id}/`, method: 'PATCH', data }),

  delete: (projectId: number, id: number) =>
    request<void>({ url: `${base(projectId)}/${id}/`, method: 'DELETE' }),

  /** 试加载证书并返回告警（不阻断保存，供「校验」按钮使用） */
  validate: (projectId: number, id: number) =>
    request<ClientCertValidationResult>({ url: `${base(projectId)}/${id}/validate/`, method: 'POST' }),
};

// ---------------------------------------------------------------------------
// Compatibility exports（与 databaseConfigService 保持一致的调用风格）
// ---------------------------------------------------------------------------

function _pid(): number {
  return useProjectStore().currentProjectId ?? 0;
}

export type ClientCertificate = Partial<ApiClientCertificate> & Record<string, any>;
export type CreateClientCertificateData = Partial<ApiClientCertificate> & { project?: number };
export type UpdateClientCertificateData = Partial<ApiClientCertificate>;

export async function getClientCertificates(projectId?: number) {
  const pid = projectId ?? _pid();
  return wrapListResponse(await clientCertificateService.list(pid));
}

export async function getClientCertificate(id: number) {
  return wrapOneResponse(await clientCertificateService.get(_pid(), id));
}

export async function createClientCertificate(data: any) {
  const pid = data.project ? Number(data.project) : _pid();
  const payload = { ...data };
  delete payload.project;
  return wrapOneResponse(await clientCertificateService.create(pid, payload));
}

export async function updateClientCertificate(id: number, data: any) {
  const pid = data.project ? Number(data.project) : _pid();
  const payload = { ...data };
  delete payload.project;
  return wrapOneResponse(await clientCertificateService.update(pid, id, payload));
}

export async function deleteClientCertificate(id: number) {
  return wrapOneResponse(await clientCertificateService.delete(_pid(), id));
}

export async function validateClientCertificate(id: number) {
  return wrapOneResponse(await clientCertificateService.validate(_pid(), id));
}
