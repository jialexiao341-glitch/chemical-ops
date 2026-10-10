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
    /** 头像 data URL（data:image/...;base64,...），无头像为 null */
    avatar?: null | string;
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

  /** 个人中心可更新的资料字段（角色/部门/状态不在此列，后端也会丢弃） */
  export interface ProfileParams {
    display_name?: string;
    email?: null | string;
    phone?: null | string;
    /** 头像 base64（可带 data: 前缀）；null 表示清除头像 */
    avatar_base64?: null | string;
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

export interface RegistrationPayload {
  avatar_base64?: string;
  username: string;
  password: string;
  display_name: string;
  role_code: string;
  email?: string;
  phone?: string;
}

export async function getRegistrationRolesApi() {
  return requestClient.get<{ role_code: string; role_name: string }[]>('/auth/registration-roles');
}

export async function registerApi(data: RegistrationPayload) {
  return requestClient.post<{ status: string; username: string }>('/auth/register', data);
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
 * 更新个人资料（昵称/邮箱/手机）。
 *
 * 后端只接受白名单字段，角色与部门无法通过此接口修改。
 */
export async function updateProfileApi(data: AuthApi.ProfileParams) {
  return requestClient.request<AuthApi.CurrentUser>('/auth/me', {
    data,
    method: 'PATCH',
  });
}

/**
 * 修改个人登录密码（校验原密码）。
 *
 * 修改成功后后端撤销该账号所有已签发令牌，界面需要重新登录。
 */
export async function changePasswordApi(data: AuthApi.ChangePasswordParams) {
  return requestClient.request<{ changed: boolean }>('/auth/me/password', {
    data,
    method: 'PUT',
  });
}

/**
 * 退出登录。
 *
 * 撤销该账号所有设备的现有访问令牌，再清理本地登录状态。
 */
export async function logoutApi() {
  return requestClient.request<{ revoked: boolean }>('/auth/logout', {
    method: 'POST',
  });
}
