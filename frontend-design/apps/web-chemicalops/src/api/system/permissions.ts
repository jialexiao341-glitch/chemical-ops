import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace SystemPermissionApi {
  /** 权限，对应后端 PermissionRead */
  export interface SystemPermission {
    action: string;
    created_at?: string;
    description?: null | string;
    id: number;
    permission_code: string;
    permission_name: string;
    permission_type: string;
    resource: string;
    updated_at?: string;
  }

  export interface PermissionPayload {
    action: string;
    description?: null | string;
    permission_code: string;
    permission_name: string;
    permission_type: string;
    resource: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    permission_type?: string;
  }
}

/** 分页查询权限 */
export async function getPermissionListApi(
  params?: SystemPermissionApi.ListParams,
) {
  return requestClient.get<PageResult<SystemPermissionApi.SystemPermission>>(
    '/system/permissions',
    { params },
  );
}

/** 新增权限 */
export async function createPermissionApi(
  data: SystemPermissionApi.PermissionPayload,
) {
  return requestClient.post<SystemPermissionApi.SystemPermission>(
    '/system/permissions',
    data,
  );
}

/** 更新权限 */
export async function updatePermissionApi(
  id: number,
  data: Partial<SystemPermissionApi.PermissionPayload>,
) {
  return requestClient.request<SystemPermissionApi.SystemPermission>(`/system/permissions/${id}`, { data, method: 'PATCH' });
}

/**
 * 删除权限。
 * 已绑定角色的权限不能删除，后端会返回 400 中文提示。
 */
export async function deletePermissionApi(id: number) {
  return requestClient.delete<SystemPermissionApi.SystemPermission>(
    `/system/permissions/${id}`,
  );
}
