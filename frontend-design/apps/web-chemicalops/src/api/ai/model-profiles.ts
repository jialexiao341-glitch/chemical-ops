import { requestClient } from '#/api/request';

export namespace AIModelProfileApi {
  /** 模型配置；密钥只返回掩码 */
  export interface ModelProfile {
    api_key_masked: null | string;
    base_url: string;
    context_window: null | number;
    created_at: string;
    has_api_key: boolean;
    id: number;
    is_default: boolean;
    max_concurrency: number;
    max_retries: number;
    max_tokens: null | number;
    model: string;
    name: string;
    reasoning_effort: null | 'high' | 'low' | 'medium';
    temperature: number;
    timeout_seconds: number;
    updated_at: string;
  }

  export interface ProfilePayload {
    api_key?: string;
    base_url: string;
    context_window?: null | number;
    max_concurrency?: number;
    max_retries?: number;
    max_tokens?: null | number;
    model: string;
    name: string;
    reasoning_effort?: 'high' | 'low' | 'medium' | null;
    temperature?: number;
    timeout_seconds?: number;
  }

  export interface ProbeResult {
    latency_ms: number;
    message: string;
    model: string;
    ok: boolean;
  }
}

/** 查询模型配置列表 */
export async function getModelProfilesApi(keyword?: string) {
  return requestClient.get<{
    items: AIModelProfileApi.ModelProfile[];
    total: number;
  }>('/ai/model-profiles', { params: { keyword } });
}

/** 新增模型配置 */
export async function createModelProfileApi(
  data: AIModelProfileApi.ProfilePayload,
) {
  return requestClient.post<AIModelProfileApi.ModelProfile>(
    '/ai/model-profiles',
    data,
  );
}

/** 更新模型配置；api_key 省略表示保留已保存密钥 */
export async function updateModelProfileApi(
  id: number,
  data: Partial<AIModelProfileApi.ProfilePayload>,
) {
  return requestClient.request<AIModelProfileApi.ModelProfile>(
    `/ai/model-profiles/${id}`,
    { data, method: 'PATCH' },
  );
}

/** 删除模型配置 */
export async function deleteModelProfileApi(id: number) {
  return requestClient.delete<{ deleted: boolean }>(
    `/ai/model-profiles/${id}`,
  );
}

/** 切换当前使用模型；服务端先做连通性探测 */
export async function activateModelProfileApi(id: number) {
  return requestClient.post<AIModelProfileApi.ModelProfile>(
    `/ai/model-profiles/${id}/activate`,
  );
}

/** 检查模型连通性 */
export async function probeModelProfileApi(id: number) {
  return requestClient.post<AIModelProfileApi.ProbeResult>(
    `/ai/model-profiles/${id}/probe`,
    undefined,
    { timeout: 45_000 },
  );
}