import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace QualityAcceptanceApi {
  export interface ReviewTarget {
    delivery_item_id: number;
    product_id: number;
    product_name: string;
    product_model: null | string;
    batch_no: null | string;
    line_no: number;
  }

  export interface ReviewHistory {
    id: number;
    file_name: string;
    product_name: string;
    batch_no: null | string;
    standard_version: null | number;
    status: 'CONFIRMED' | 'CORRECTION_SUBMITTED' | 'NEEDS_CORRECTION' | 'PENDING';
    created_at: string;
    reviewed_at: null | string;
    reviewer_note: null | string;
  }

  export interface ReportFile {
    id: number;
    file_name: string;
    uploaded_at: string;
  }

  export interface ReportCheck {
    item_name: string;
    report_value: null | string;
    recorded_value: null | string;
    source_quote: null | string;
    source_location: null | string;
    status: 'MATCH' | 'MISMATCH' | 'NOT_COMPARABLE' | 'NOT_RECORDED' | 'REPORT_MISSING';
    standard_criterion: null | string;
    standard_requirement: null | string;
    standard_status: 'MISSING' | 'NOT_CONFIGURED' | 'OUTSIDE_STANDARD' | 'UNVERIFIED' | 'WITHIN_STANDARD';
  }

  export interface ReportReview {
    review_id: null | number;
    acceptance_id: number;
    delivery_item_id: null | number;
    product_name: null | string;
    product_model: null | string;
    report_product_name: null | string;
    report_product_model: null | string;
    product_status: 'MATCH' | 'MISMATCH' | 'UNVERIFIED';
    standard_id: null | number;
    standard_version: null | number;
    standard_source: null | string;
    file_id: number;
    file_name: string;
    report_batch_no: null | string;
    expected_batch_nos: string[];
    batch_status: 'MATCH' | 'MISMATCH' | 'UNVERIFIED';
    checks: ReportCheck[];
    warnings: string[];
    reviewed_at: string;
  }

  export interface Correction {
    id: number;
    review_id: number;
    item_name: string;
    status: 'OPEN' | 'RESOLVED';
    note: string;
    actor_id: number;
    created_at: string;
  }

  export interface ReportSummary {
    delivery_item_id: number;
    reviews: ReviewHistory[];
    comparisons: { item_name: string; values: { review_id: number; file_name: string; value: string; source_quote: null | string; source_location: null | string }[]; conflict: boolean }[];
    corrections: Correction[];
  }

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
    item_results?: { delivery_item_id: number; tests: Record<string, string> }[];
  }

  export interface ListParams extends PageQuery {
    /** 后端参数名为 result */
    result?: string;
  }
}

/** 查询验收单可供报告核对的到货明细。 */
export async function getAcceptanceReviewTargetsApi(id: number) {
  return requestClient.get<QualityAcceptanceApi.ReviewTarget[]>(`/quality-acceptances/${id}/review-targets`);
}

/** 查询报告核对历史及每次人工复核状态。 */
export async function getAcceptanceReviewHistoryApi(id: number) {
  return requestClient.get<QualityAcceptanceApi.ReviewHistory[]>(`/quality-acceptances/${id}/report-reviews`);
}

/** 读取指定核对记录的结果快照。 */
export async function getAcceptanceReviewRecordApi(id: number, reviewId: number) {
  return requestClient.get<QualityAcceptanceApi.ReportReview>(`/quality-acceptances/${id}/report-reviews/${reviewId}`);
}

/** 保存人工复核结论与说明，不提交验收结果。 */
export async function decideAcceptanceReviewApi(id: number, reviewId: number, status: 'CONFIRMED' | 'NEEDS_CORRECTION', reviewerNote: string, correctionItems: string[] = []) {
  return requestClient.post<QualityAcceptanceApi.ReviewHistory>(`/quality-acceptances/${id}/report-reviews/${reviewId}/decision`, {
    status,
    reviewer_note: reviewerNote,
    correction_items: correctionItems,
  });
}

export async function getAcceptanceReportSummaryApi(id: number, deliveryItemId: number) {
  return requestClient.get<QualityAcceptanceApi.ReportSummary>(`/quality-acceptances/${id}/report-summary/${deliveryItemId}`);
}

export async function getAcceptanceCorrectionsApi(id: number, reviewId: number) {
  return requestClient.get<QualityAcceptanceApi.Correction[]>(`/quality-acceptances/${id}/report-reviews/${reviewId}/corrections`);
}

export async function resolveAcceptanceCorrectionApi(id: number, reviewId: number, itemName: string, note: string) {
  return requestClient.post<QualityAcceptanceApi.Correction>(`/quality-acceptances/${id}/report-reviews/${reviewId}/corrections`, { item_name: itemName, note });
}

/** 列出关联到当前验收单的报告文件。 */
export async function getAcceptanceReportFilesApi(id: number) {
  return requestClient.get<QualityAcceptanceApi.ReportFile[]>(`/quality-acceptances/${id}/report-files`);
}

/** 上传报告文件并关联到当前验收单。 */
export async function uploadAcceptanceReportApi(id: number, file: File) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<QualityAcceptanceApi.ReportFile>(`/quality-acceptances/${id}/report-files`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

/** 指定报告与可选到货明细，发起一次只读核对并保存结果。 */
export async function reviewAcceptanceReportApi(id: number, fileId: number, deliveryItemId?: number, standardId?: number) {
  return requestClient.post<QualityAcceptanceApi.ReportReview>(`/quality-acceptances/${id}/report-review`, { file_id: fileId, delivery_item_id: deliveryItemId, standard_id: standardId });
}

/** 下载已关联的验收报告原始文件。 */
export async function downloadAcceptanceReportApi(id: number, fileId: number) {
  return requestClient.download<Blob>(`/quality-acceptances/${id}/report-files/${fileId}/download`);
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
