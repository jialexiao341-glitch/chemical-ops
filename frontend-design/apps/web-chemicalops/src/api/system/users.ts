import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace SystemUserApi {
  export interface WarehouseScope {
    enabled: boolean;
    warehouse_ids: number[];
  }
  export interface DepartmentScope {
    enabled: boolean;
    department_ids: number[];
  }
  export interface SupplierBindingOption {
    id: number;
    supplier_code: string;
    supplier_name: string;
  }

  export interface SupplierBinding {
    status: string;
    supplier_code: string;
    supplier_id: number;
    supplier_name: string;
    supplier_status: string;
  }

  /** 系统用户，对应后端 UserRead */
  export interface SystemUser {
    created_at?: string;
    department_id?: null | number;
    display_name: string;
    email?: null | string;
    id: number;
    phone?: null | string;
    /** 详情/更新接口返回已绑定角色；分页列表为 null */
    role_ids?: null | number[];
    role_codes: string[];
    role_names: string[];
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

export async function getSupplierBindingOptionsApi() {
  return requestClient.get<SystemUserApi.SupplierBindingOption[]>('/system/supplier-binding-options');
}

export async function getUserSupplierBindingApi(id: number) {
  return requestClient.get<SystemUserApi.SupplierBinding | null>(`/system/users/${id}/supplier-binding`);
}

export async function setUserSupplierBindingApi(id: number, supplierId: number) {
  return requestClient.put<SystemUserApi.SupplierBinding>(`/system/users/${id}/supplier-binding`, { supplier_id: supplierId });
}

export async function getUserDepartmentScopeApi(id: number) {
  return requestClient.get<SystemUserApi.DepartmentScope>(`/system/users/${id}/department-scope`);
}

export async function setUserDepartmentScopeApi(id: number, data: SystemUserApi.DepartmentScope) {
  return requestClient.put<SystemUserApi.DepartmentScope>(`/system/users/${id}/department-scope`, data);
}

export async function getUserWarehouseScopeApi(id: number) {
  return requestClient.get<SystemUserApi.WarehouseScope>(`/system/users/${id}/warehouse-scope`);
}

export async function setUserWarehouseScopeApi(id: number, data: SystemUserApi.WarehouseScope) {
  return requestClient.put<SystemUserApi.WarehouseScope>(`/system/users/${id}/warehouse-scope`, data);
}

export async function reviewRegistrationApi(id: number, decision: 'approve' | 'reject', reason = '') {
  return requestClient.post<SystemUserApi.SystemUser>(`/system/users/${id}/registration-review`, { decision, reason });
}
