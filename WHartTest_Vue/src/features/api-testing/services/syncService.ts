import { request } from '@/utils/request';
import { useProjectStore } from '@/store/projectStore';
import type { ApiSyncConfig, ApiSyncHistory, ApiGlobalSyncConfig } from '../types/sync';

const syncBase = (projectId: number) => `/projects/${projectId}/api-sync-configs`;
const historyBase = (projectId: number) => `/projects/${projectId}/api-sync-histories`;
const globalBase = (projectId: number) => `/projects/${projectId}/api-global-sync-configs`;

export const syncService = {
  // --- Sync Configs ---
  listConfigs: (projectId: number, params?: Record<string, any>) =>
    request<ApiSyncConfig[]>({ url: `${syncBase(projectId)}/`, method: 'GET', params }),

  getConfig: (projectId: number, id: number) =>
    request<ApiSyncConfig>({ url: `${syncBase(projectId)}/${id}/`, method: 'GET' }),

  createConfig: (projectId: number, data: Partial<ApiSyncConfig>) =>
    request<ApiSyncConfig>({ url: `${syncBase(projectId)}/`, method: 'POST', data }),

  updateConfig: (projectId: number, id: number, data: Partial<ApiSyncConfig>) =>
    request<ApiSyncConfig>({ url: `${syncBase(projectId)}/${id}/`, method: 'PUT', data }),

  deleteConfig: (projectId: number, id: number) =>
    request<void>({ url: `${syncBase(projectId)}/${id}/`, method: 'DELETE' }),

  syncNow: (projectId: number, id: number) =>
    request<any>({ url: `${syncBase(projectId)}/${id}/sync_now/`, method: 'POST' }),

  batchSync: (projectId: number, data: { config_ids?: number[]; interface_step_pairs?: any[] }) =>
    request<any>({ url: `${syncBase(projectId)}/batch_sync/`, method: 'POST', data }),

  // --- Sync History ---
  listHistories: (projectId: number, params?: Record<string, any>) =>
    request<ApiSyncHistory[]>({ url: `${historyBase(projectId)}/`, method: 'GET', params }),

  getHistory: (projectId: number, id: number) =>
    request<ApiSyncHistory>({ url: `${historyBase(projectId)}/${id}/`, method: 'GET' }),

  rollback: (projectId: number, historyId: number) =>
    request<any>({ url: `${historyBase(projectId)}/${historyId}/rollback/`, method: 'POST' }),

  // --- Global Sync Config ---
  listGlobalConfigs: (projectId: number, params?: Record<string, any>) =>
    request<ApiGlobalSyncConfig[]>({ url: `${globalBase(projectId)}/`, method: 'GET', params }),

  getGlobalConfig: (projectId: number, id: number) =>
    request<ApiGlobalSyncConfig>({ url: `${globalBase(projectId)}/${id}/`, method: 'GET' }),

  createGlobalConfig: (projectId: number, data: Partial<ApiGlobalSyncConfig>) =>
    request<ApiGlobalSyncConfig>({ url: `${globalBase(projectId)}/`, method: 'POST', data }),

  updateGlobalConfig: (projectId: number, id: number, data: Partial<ApiGlobalSyncConfig>) =>
    request<ApiGlobalSyncConfig>({ url: `${globalBase(projectId)}/${id}/`, method: 'PUT', data }),

  deleteGlobalConfig: (projectId: number, id: number) =>
    request<void>({ url: `${globalBase(projectId)}/${id}/`, method: 'DELETE' }),

  setActive: (projectId: number, id: number) =>
    request<void>({ url: `${globalBase(projectId)}/${id}/set_active/`, method: 'POST' }),

  currentConfig: (projectId: number) =>
    request<ApiGlobalSyncConfig>({ url: `${globalBase(projectId)}/current_config/`, method: 'GET' }),
};

// ---------------------------------------------------------------------------
// Compatibility exports
// ---------------------------------------------------------------------------

function _pid(): number {
  return useProjectStore().currentProjectId ?? 0;
}

// Type aliases for component imports
export type SyncConfig = ApiGlobalSyncConfig & Record<string, any>;
export type SyncHistory = ApiSyncHistory & Record<string, any>;
export type { ApiSyncConfig };
export type ApiInterface = { id: number; name: string; method: string; url: string; module?: any; [k: string]: any };
export type TestCase = { id: number; name: string; steps?: any[]; [k: string]: any };
export type TestStep = { id: number; name: string; order: number; interface_info?: any; [k: string]: any };

export const syncApi = {
  // --- Global Sync Config (shown as "SyncConfig" in SyncConfigPanel) ---
  getConfigs: async (projectId: number) => {
    const res = await syncService.listGlobalConfigs(projectId);
    const configs = res.data ?? [];
    const activeConfig = configs.find((c: any) => c.is_active);
    return { data: { configs, active_config_id: activeConfig?.id ?? null } };
  },
  createConfig: async (data: any) => {
    const pid = data.project ? Number(data.project) : _pid();
    delete data.project;
    return syncService.createGlobalConfig(pid, data);
  },
  updateConfig: async (id: number, data: any) => {
    const pid = _pid();
    return syncService.updateGlobalConfig(pid, id, data);
  },
  deleteConfig: async (id: number) => {
    const pid = _pid();
    return syncService.deleteGlobalConfig(pid, id);
  },
  setActiveConfig: async (id: number) => {
    const pid = _pid();
    return syncService.setActive(pid, id);
  },

  // --- Sync History ---
  getHistories: async (params: Record<string, any> = {}): Promise<any> => {
    const pid = params.project_id ? Number(params.project_id) : _pid();
    delete params.project_id;
    const res = await syncService.listHistories(pid, params);
    return { data: { results: res.data ?? [], count: res.total ?? 0 } };
  },
  getHistoryDetail: async (id: number): Promise<any> => {
    const pid = _pid();
    return syncService.getHistory(pid, id);
  },
  rollbackHistory: async (id: number) => {
    const pid = _pid();
    return syncService.rollback(pid, id);
  },

  // --- API Sync Configs (per-interface configs) ---
  getApiConfigs: async (projectId: number) => {
    const res = await syncService.listConfigs(projectId);
    return { data: { results: res.data ?? [], count: res.total ?? 0 } };
  },
  getConfigDetail: async (id: number) => {
    const pid = _pid();
    return syncService.getConfig(pid, id);
  },
  createApiConfig: async (data: any) => {
    const pid = _pid();
    return syncService.createConfig(pid, data);
  },
  updateApiConfig: async (id: number, data: any) => {
    const pid = _pid();
    return syncService.updateConfig(pid, id, data);
  },
  deleteApiConfig: async (id: number) => {
    const pid = _pid();
    return syncService.deleteConfig(pid, id);
  },
  syncNowConfig: async (id: number) => {
    const pid = _pid();
    return syncService.syncNow(pid, id);
  },

  // --- Helpers for ApiConfigForm (interface/testcase/step lists) ---
  getInterfaces: async (projectId: number) => {
    const res = await request<any>({ url: `/projects/${projectId}/api-interfaces/`, method: 'GET', params: { page_size: 1000 } });
    return { data: { results: res.data ?? [] } };
  },
  getTestCases: async (projectId: number) => {
    const res = await request<any>({ url: `/projects/${projectId}/api-testcases/`, method: 'GET', params: { page_size: 1000 } });
    return { data: { results: res.data ?? [] } };
  },
  getTestSteps: async (testcaseId: number) => {
    const pid = _pid();
    const res = await request<any>({ url: `/projects/${pid}/api-testcases/${testcaseId}/`, method: 'GET' });
    return { data: { steps: res.data?.steps ?? [] } };
  },
};
