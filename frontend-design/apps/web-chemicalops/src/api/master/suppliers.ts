import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace SupplierApi {
  /** 供应商主数据，对应后端 SupplierRead */
  export interface Supplier {
    address?: null | string;
    business_scope?: null | string;
    cooperation_level?: null | string;
    country_code?: string;
    created_at?: string;
    default_lead_days?: null | number;
    id: number;
    note?: null | string;
    payment_terms?: null | string;
    region?: null | string;
    status: string;
    supplier_code: string;
    supplier_name: string;
    unified_credit_code?: null | string;
    updated_at?: string;
  }

  export interface SupplierPayload {
    address?: null | string;
    business_scope?: null | string;
    cooperation_level?: null | string;
    country_code?: string;
    default_lead_days?: null | number;
    note?: null | string;
    payment_terms?: null | string;
    region?: null | string;
    status?: string;
    supplier_code: string;
    supplier_name: string;
    unified_credit_code?: null | string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    region?: string;
    status?: string;
  }
}

/** 分页查询供应商 */
export async function getSupplierListApi(params?: SupplierApi.ListParams) {
  return requestClient.get<PageResult<SupplierApi.Supplier>>('/suppliers', {
    params,
  });
}

/** 查询供应商详情 */
export async function getSupplierApi(id: number) {
  return requestClient.get<SupplierApi.Supplier>(`/suppliers/${id}`);
}

/** 新增供应商 */
export async function createSupplierApi(data: SupplierApi.SupplierPayload) {
  return requestClient.post<SupplierApi.Supplier>('/suppliers', data);
}

/** 更新供应商 */
export async function updateSupplierApi(
  id: number,
  data: Partial<SupplierApi.SupplierPayload>,
) {
  return requestClient.request<SupplierApi.Supplier>(`/suppliers/${id}`, { data, method: 'PATCH' });
}

/** 停用供应商（软删除） */
export async function deleteSupplierApi(id: number) {
  return requestClient.delete<SupplierApi.Supplier>(`/suppliers/${id}`);
}
