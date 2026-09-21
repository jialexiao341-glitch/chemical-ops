import { requestClient } from '#/api/request';

export namespace AuthApi {
  /** 登录接口参数 */
  export interface LoginParams {
    password: string;
    username: string;
  }

  /** 登录接口返回值，对应后端 TokenResponse */
  export interface LoginResult {
    access_token: string;
    expires_in: number;
    token_type: string;
  }

  /** 当前登录用户，对应后端 CurrentUserRead */
  export interface CurrentUser {
    created_at?: string;
    department_id?: null | number;
    display_name: string;
    email?: null | string;
    id: number;
    permission_codes: string[];
    phone?: null | string;
    role_codes: string[];
    status: string;
    updated_at?: string;
    username: string;
  }

  /** 修改当前用户密码 */
  export interface ChangePasswordParams {
    new_password: string;
    old_password: string;
  }
}

/**
 * 登录
 *
 * 后端返回 `access_token` / `token_type` / `expires_in`。
 */
export async function loginApi(data: AuthApi.LoginParams) {
  return requestClient.post<AuthApi.LoginResult>('/auth/login', data);
}

/**
 * 查询当前登录用户，包含角色码与权限码。
 *
 * 该接口是前端权限体系的唯一来源：后端没有菜单接口，
 * 路由与按钮权限都由 `permission_codes` 推导。
 */
export async function getCurrentUserApi() {
  return requestClient.get<AuthApi.CurrentUser>('/auth/me');
}

/**
 * 退出登录。
 *
 * 后端未提供 logout 接口，令牌由前端清除即可（JWT 无状态）。
 */
export async function logoutApi() {
  return Promise.resolve();
}
