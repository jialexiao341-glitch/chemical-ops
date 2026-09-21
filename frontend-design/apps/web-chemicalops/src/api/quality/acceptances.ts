import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace QualityAcceptanceApi {
  /** 质量验收记录，对应后端 QualityAcceptanceRead */
  export interface Acceptance {
    acceptance_no: string;
    certificate_complete: number;
    conclusion?: null | string;
    created_at?: string;
    delivery_id: number;
    id: number;
    inspection_time?: null | string;
    inspector_id?: number;
    report_file_id?: null | number;
    result: null | string;
    test_result?: any;
    updated_at?: string;
  }

  export interface ResultPayload {
    certificate_complete?: boolean;
    conclusion?: null | string;
    report_file_id?: null | number;
    /** PASSED | PARTIAL | FAILED | REINSPECTION */
    result: string;
    test_result?: any;
  }

  export interface ListParams extends PageQuery {
    /** 后端参数名为 result */
    result?: string;
  }
}

/** 分页查询质量验收 */
export async function getAcceptanceListApi(
  params?: QualityAcceptanceApi.ListParams,
) {
  return requestClient.get<PageResult<QualityAcceptanceApi.Acceptance>>(
    '/quality-acceptances',
    { params },
  );
}

/** 查询验收详情 */
export async function getAcceptanceApi(id: number) {
  return requestClient.get<QualityAcceptanceApi.Acceptance>(
    `/quality-acceptances/${id}`,
  );
}

/**
 * 为已收货的到货单创建待检验记录。
 * 后端会把到货单置为 INSPECTING。
 */
export async function createAcceptanceApi(deliveryId: number) {
  return requestClient.post<QualityAcceptanceApi.Acceptance>(
    '/quality-acceptances',
    { delivery_id: deliveryId },
  );
}

/**
 * 录入检测结果。
 * PASSED 时到货单进入 ACCEPTED；PARTIAL / FAILED 进入 EXCEPTION 并自动创建质量异常。
 */
export async function submitAcceptanceResultApi(
  id: number,
  data: QualityAcceptanceApi.ResultPayload,
) {
  return requestClient.post<QualityAcceptanceApi.Acceptance>(
    `/quality-acceptances/${id}/result`,
    data,
  );
}
