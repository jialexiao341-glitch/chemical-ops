import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace ChemicalApi {
  /** 化学品主数据，对应后端 ChemicalRead */
  export interface Chemical {
    alias_text?: null | string;
    cas_no?: null | string;
    chemical_formula?: null | string;
    chemical_name: string;
    created_at?: string;
    english_name?: null | string;
    hazard_class?: null | string;
    id: number;
    /** 分子量，后端 DECIMAL 以字符串返回 */
    molecular_weight?: null | string;
    source_text?: null | string;
    status: string;
    updated_at?: string;
  }

  /** 新增/更新入参 */
  export interface ChemicalPayload {
    alias_text?: null | string;
    cas_no?: null | string;
    chemical_formula?: null | string;
    chemical_name: string;
    english_name?: null | string;
    hazard_class?: null | string;
    molecular_weight?: null | number | string;
    source_text?: null | string;
    status?: string;
  }

  export interface ListParams extends PageQuery {
    keyword?: string;
    status?: string;
  }
}

/** 分页查询化学品 */
export async function getChemicalListApi(params?: ChemicalApi.ListParams, options?: { silent?: boolean }) {
  return requestClient.get<PageResult<ChemicalApi.Chemical>>('/chemicals', {
    ...options,
    params,
  });
}

/** 查询化学品详情 */
export async function getChemicalApi(id: number) {
  return requestClient.get<ChemicalApi.Chemical>(`/chemicals/${id}`);
}

/** 新增化学品 */
export async function createChemicalApi(data: ChemicalApi.ChemicalPayload) {
  return requestClient.post<ChemicalApi.Chemical>('/chemicals', data);
}

/** 更新化学品 */
export async function updateChemicalApi(
  id: number,
  data: Partial<ChemicalApi.ChemicalPayload>,
) {
  return requestClient.request<ChemicalApi.Chemical>(`/chemicals/${id}`, { data, method: 'PATCH' });
}

/** 停用化学品（软删除，状态置为 INACTIVE） */
export async function deleteChemicalApi(id: number) {
  return requestClient.delete<ChemicalApi.Chemical>(`/chemicals/${id}`);
}
