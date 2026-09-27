import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace ProductApi {
  /** 产品规格，对应后端 ProductRead */
  export interface Product {
    category_id?: null | number;
    chemical_id: number;
    created_at?: string;
    id: number;
    model?: null | string;
    packaging_spec?: null | string;
    parameter_json?: Record<string, any> | null;
    product_code: string;
    product_name: string;
    purity_unit?: null | string;
    purity_value?: null | string;
    safety_stock_quantity?: null | string;
    status: string;
    unit_id: number;
    updated_at?: string;
    version_no?: number;
  }

  /** 计量单位，对应后端 UnitRead */
  export interface Unit {
    dimension?: null | string;
    id: number;
    status?: string;
    unit_code: string;
    unit_name: string;
  }

  export interface ProductPayload {
    category_id?: null | number;
    chemical_id: number;
    model?: null | string;
    packaging_spec?: null | string;
    parameter_json?: Record<string, any> | null;
    product_code: string;
    product_name: string;
    purity_unit?: string;
    purity_value?: null | number | string;
    safety_stock_quantity?: null | number | string;
    status?: string;
    unit_id: number;
  }

  export interface ListParams extends PageQuery {
    chemical_id?: number;
    keyword?: string;
    status?: string;
  }
}

/** 分页查询产品规格 */
export async function getProductListApi(params?: ProductApi.ListParams) {
  return requestClient.get<PageResult<ProductApi.Product>>('/products', {
    params,
  });
}

/** 查询产品详情 */
export async function getProductApi(id: number) {
  return requestClient.get<ProductApi.Product>(`/products/${id}`);
}

/** 查询全部计量单位（任意登录用户可读，用于表单下拉） */
export async function getUnitListApi() {
  return requestClient.get<ProductApi.Unit[]>('/products/units');
}

/** 新增产品 */
export async function createProductApi(data: ProductApi.ProductPayload) {
  return requestClient.post<ProductApi.Product>('/products', data);
}

/** 更新产品 */
export async function updateProductApi(
  id: number,
  data: Partial<ProductApi.ProductPayload>,
) {
  return requestClient.request<ProductApi.Product>(`/products/${id}`, { data, method: 'PATCH' });
}

/** 停用产品（软删除） */
export async function deleteProductApi(id: number) {
  return requestClient.delete<ProductApi.Product>(`/products/${id}`);
}
