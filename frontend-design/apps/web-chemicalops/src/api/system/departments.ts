import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace SystemDepartmentApi {
  /** 部门，对应后端 DepartmentRead */
  export interface SystemDepartment {
    children?: SystemDepartment[];
    created_at?: string;
    department_code: string;
    department_name: string;
    id: number;
    manager_id?: null | number;
    parent_id?: null | number;
    status: string;
    updated_at?: string;
  }

  export interface DepartmentPayload {
    department_code: string;
    department_name: string;
    manager_id?: null | number;
    parent_id?: null | number;
    status?: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询部门 */
export async function getDepartmentListApi(
  params?: SystemDepartmentApi.ListParams,
) {
  return requestClient.get<PageResult<SystemDepartmentApi.SystemDepartment>>(
    '/system/departments',
    { params },
  );
}

/** 查询部门详情 */
export async function getDepartmentApi(id: number) {
  return requestClient.get<SystemDepartmentApi.SystemDepartment>(
    `/system/departments/${id}`,
  );
}

/** 新增部门 */
export async function createDepartmentApi(
  data: SystemDepartmentApi.DepartmentPayload,
) {
  return requestClient.post<SystemDepartmentApi.SystemDepartment>(
    '/system/departments',
    data,
  );
}

/** 更新部门 */
export async function updateDepartmentApi(
  id: number,
  data: Partial<SystemDepartmentApi.DepartmentPayload>,
) {
  return requestClient.request<SystemDepartmentApi.SystemDepartment>(`/system/departments/${id}`, { data, method: 'PATCH' });
}

/** 停用部门（软删除） */
export async function deleteDepartmentApi(id: number) {
  return requestClient.delete<SystemDepartmentApi.SystemDepartment>(
    `/system/departments/${id}`,
  );
}
