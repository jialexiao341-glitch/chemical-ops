import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace SystemRoleApi {
  /** 角色，对应后端 RoleRead */
  export interface SystemRole {
    created_at?: string;
    description?: null | string;
    id: number;
    role_code: string;
    role_name: string;
    status: string;
    updated_at?: string;
  }

  export interface RolePayload {
    description?: null | string;
    permission_ids?: number[];
    role_code: string;
    role_name: string;
    status?: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询角色 */
export async function getRoleListApi(params?: SystemRoleApi.ListParams) {
  return requestClient.get<PageResult<SystemRoleApi.SystemRole>>(
    '/system/roles',
    { params },
  );
}

/** 查询角色详情 */
export async function getRoleApi(id: number) {
  return requestClient.get<SystemRoleApi.SystemRole>(`/system/roles/${id}`);
}

/** 新增角色 */
export async function createRoleApi(data: SystemRoleApi.RolePayload) {
  return requestClient.post<SystemRoleApi.SystemRole>('/system/roles', data);
}

/** 更新角色，可通过 permission_ids 重设权限关联 */
export async function updateRoleApi(
  id: number,
  data: Partial<SystemRoleApi.RolePayload>,
) {
  return requestClient.request<SystemRoleApi.SystemRole>(`/system/roles/${id}`, { data, method: 'PATCH' });
}

/** 停用角色（软删除） */
export async function deleteRoleApi(id: number) {
  return requestClient.delete<SystemRoleApi.SystemRole>(`/system/roles/${id}`);
}
