/**
 * ChemicalOps 请求客户端。
 *
 * 与 vben 默认约定的区别：
 * - 后端（FastAPI）成功时直接返回业务数据本身，没有 `{ code, data }` 外层包装。
 *   因此这里用 `successCode: () => true` + `dataField: (body) => body`，
 *   以「HTTP 2xx 即成功」为准，并把整个响应体作为结果返回。
 * - 失败时后端返回 `{ code, message, detail }`，`message` 已经是中文提示，
 *   优先透传给用户，而不是使用按状态码生成的通用文案。
 * - 后端没有 refresh token 接口，401 直接走重新登录。
 */
import type { RequestClientOptions } from '@vben/request';

import { useAppConfig } from '@vben/hooks';
import { preferences } from '@vben/preferences';
import {
  authenticateResponseInterceptor,
  defaultResponseInterceptor,
  RequestClient,
} from '@vben/request';
import { useAccessStore } from '@vben/stores';

import { message } from 'antdv-next';

import { useAuthStore } from '#/store';

const { apiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);

/** 后端统一错误响应体 */
interface ChemicalOpsErrorBody {
  code?: number;
  detail?: unknown;
  message?: string;
}

function createIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');

  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * 从后端错误响应中提取可以直接展示给用户的中文提示。
 *
 * 后端的错误体是 `{ code, message, detail }`：
 * - `message` 是按状态码给的通用文案（如「数据已存在」「资源不存在」）
 * - `detail` 才是具体的业务原因（如「CAS 号 64-17-5 已存在」）
 *
 * 因此优先展示 `detail`，否则用户只能看到笼统的「数据已存在」，
 * 不知道到底哪里冲突。422 参数校验错误的 `detail` 是数组，
 * 逐项拼成人话；数组为空或没有 detail 时才退回 `message`。
 */
function resolveErrorMessage(error: any): string {
  const body: ChemicalOpsErrorBody = error?.response?.data ?? {};
  const baseMessage = typeof body.message === 'string' ? body.message : '';

  // detail 为数组：参数校验错误，逐项描述字段问题
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const details = body.detail
      .map((item: any) => {
        if (typeof item === 'string') {
          return item;
        }
        const location = Array.isArray(item?.location)
          ? item.location.filter((part: unknown) => part !== 'body').join('.')
          : '';
        const text = item?.message ?? '';
        return location ? `${location}: ${text}` : text;
      })
      .filter(Boolean)
      .slice(0, 3)
      .join('；');
    if (details) {
      // 通用文案与首条明细常常重复，仅在确实不同才拼接
      return details === baseMessage ? details : `${baseMessage}：${details}`;
    }
  }

  // detail 为字符串：具体业务原因，比 message 更有信息量
  if (typeof body.detail === 'string' && body.detail.trim()) {
    return body.detail.trim();
  }

  if (baseMessage) {
    return baseMessage;
  }

  const status = error?.response?.status;
  if (status === 401) {
    return '登录状态已失效，请重新登录';
  }
  if (status === 403) {
    return '没有权限执行该操作';
  }
  if (!error?.response) {
    return '网络异常，请检查后端服务是否已启动';
  }
  return '请求处理失败';
}

function createRequestClient(baseURL: string, options?: RequestClientOptions) {
  const client = new RequestClient({
    ...options,
    baseURL,
  });

  /**
   * 401 之后的重新认证：清除令牌并退出登录。
   * 后端未提供 refresh token 接口，因此不做静默续期。
   */
  async function doReAuthenticate() {
    const accessStore = useAccessStore();
    const authStore = useAuthStore();
    accessStore.setAccessToken(null);
    if (
      preferences.app.loginExpiredMode === 'modal' &&
      accessStore.isAccessChecked
    ) {
      accessStore.setLoginExpired(true);
    } else {
      await authStore.logout();
    }
  }

  // 请求头处理
  client.addRequestInterceptor({
    fulfilled: async (config) => {
      const method = String(config.method ?? 'get').toUpperCase();
      if (
        ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) &&
        !config.headers['Idempotency-Key']
      ) {
        config.headers['Idempotency-Key'] = createIdempotencyKey();
      }
      const accessStore = useAccessStore();
      const token = accessStore.accessToken;
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      config.headers['Accept-Language'] = preferences.app.locale;
      return config;
    },
  });

  // 响应解包：HTTP 2xx 直接返回响应体
  client.addResponseInterceptor(
    defaultResponseInterceptor({
      codeField: 'code',
      dataField: (response: any) => response,
      successCode: () => true,
    }),
  );

  // 401 处理
  client.addResponseInterceptor(
    authenticateResponseInterceptor({
      client,
      doReAuthenticate,
      doRefreshToken: async () => '',
      enableRefreshToken: false,
      formatToken: (token) => (token ? `Bearer ${token}` : null),
    }),
  );

  // 通用错误提示：优先使用后端返回的中文 message
  client.addResponseInterceptor({
    rejected: (error: any) => {
      // 登录接口自身的 401 由登录页处理，避免重复弹出全局提示
      const isLoginRequest = String(error?.config?.url ?? '').includes(
        '/auth/login',
      );
      if (!isLoginRequest) {
        message.error(resolveErrorMessage(error));
      }
      return Promise.reject(error);
    },
  });

  return client;
}

export const requestClient = createRequestClient(apiURL, {
  responseReturn: 'data',
  timeout: 30_000,
});

/**
 * 不经过响应解包的客户端，用于下载等需要完整 Axios 响应的场景。
 */
export const baseRequestClient = new RequestClient({
  baseURL: apiURL,
  timeout: 60_000,
});

/** 后端统一分页响应 */
export interface PageResult<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

/** 分页查询的通用入参 */
export interface PageQuery {
  page?: number;
  page_size?: number;
  [key: string]: any;
}
