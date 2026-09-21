import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace SystemUserApi {
  /** 系统用户，对应后端 UserRead */
  export interface SystemUser {
    created_at?: string;
    department_id?: null | number;
    display_name: string;
    email?: null | string;
    id: number;
    phone?: null | string;
    status: string;
    updated_at?: string;
    username: string;
  }

  export interface UserPayload {
    department_id?: null | number;
    display_name: string;
    email?: null | string;
    password?: string;
    phone?: null | string;
    role_ids?: number[];
    status?: string;
    username: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询系统用户 */
export async function getUserListApi(params?: SystemUserApi.ListParams) {
  return requestClient.get<PageResult<SystemUserApi.SystemUser>>(
    '/system/users',
    { params },
  );
}

/** 查询用户详情 */
export async function getUserApi(id: number) {
  return requestClient.get<SystemUserApi.SystemUser>(`/system/users/${id}`);
}

/** 新增用户 */
export async function createUserApi(data: SystemUserApi.UserPayload) {
  return requestClient.post<SystemUserApi.SystemUser>('/system/users', data);
}

/** 更新用户，仅传需要变更的字段 */
export async function updateUserApi(
  id: number,
  data: Partial<SystemUserApi.UserPayload>,
) {
  return requestClient.request<SystemUserApi.SystemUser>(`/system/users/${id}`, { data, method: 'PATCH' });
}

/** 停用用户（软删除） */
export async function deleteUserApi(id: number) {
  return requestClient.delete<SystemUserApi.SystemUser>(`/system/users/${id}`);
}
