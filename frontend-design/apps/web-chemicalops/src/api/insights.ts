import { requestClient } from '#/api/request';

export namespace BusinessInsightApi {
  export interface Evidence {
    label: string;
    value: string;
    source: string;
    path: null | string;
  }

  export interface Insight {
    kind: string;
    title: string;
    audience: string;
    summary: string;
    evidence: Evidence[];
    suggestions: string[];
    limitations: string[];
  }

  export interface Snapshot {
    id: number;
    kind: string;
    object_id: number;
    result_json: Insight;
    created_by: number;
    created_at: string;
  }

  export interface CheckItem {
    id: number;
    batch_id: number;
    balance_id: null | number;
    transaction_id: null | number;
    target_label: string;
    snapshot_id: number;
    assignee_id: null | number;
    status: string;
    finding: null | string;
    checked_by: null | number;
    checked_at: null | string;
    reviewed_by: null | number;
    reviewed_at: null | string;
  }

  export interface CheckEvent {
    id: number;
    check_id: number;
    actor_id: number;
    status: string;
    assignee_id: null | number;
    finding: null | string;
    created_at: string;
  }

  export interface RecallReport {
    version?: number;
    kind: string;
    balance_id: number;
    batch_id: number;
    batch_no: string;
    warehouse_ids: number[];
    visible_transaction_count: number;
    missing_source_count: number;
    conflict_source_count?: number;
    open_check_count: number;
    missing_check_count: number;
    status: 'INCOMPLETE' | 'READY_FOR_REVIEW';
    slots: {
      balance_id: null | number;
      warehouse_id: number;
      location_id: number;
      unit_id: number;
      quantity: null | string;
      locked_quantity: null | string;
      movement_net: string;
      difference: null | string;
      status: string;
      check_status: string;
    }[];
    outflows: {
      transaction_id: number;
      transaction_no: string;
      warehouse_id: number;
      location_id: number;
      unit_id: number;
      quantity: string;
      source_type: null | string;
      source_id: null | number;
      source_found: boolean;
      source_status?: string;
      source_item_id?: null | number;
      source_reason?: string;
      check_status: string;
      finding: null | string;
    }[];
    transfer_differences: { request_id: number; unit_id: number; net: string }[];
    source_matches?: {
      transaction_id: number;
      transaction_no: string;
      transaction_type: string;
      quantity: string;
      unit_id: number;
      warehouse_id: number;
      location_id: number;
      source_type: null | string;
      source_id: null | number;
      item_id: null | number;
      expected_quantity: null | string;
      status: string;
      reason: string;
    }[];
    transfer_pairs?: {
      request_id: number;
      item_id: number;
      unit_id: number;
      status: string;
      review_status: string;
      outbound_ids: number[];
      inbound_ids: number[];
      outbound_quantity: null | string;
      inbound_quantity: null | string;
    }[];
    limitations: string[];
    checks?: Pick<CheckItem, 'id' | 'balance_id' | 'transaction_id' | 'assignee_id' | 'status' | 'finding' | 'checked_by' | 'reviewed_by' | 'checked_at' | 'reviewed_at'>[];
  }

  export interface RecallReportSnapshot extends Omit<Snapshot, 'result_json'> {
    result_json: RecallReport;
    workflow: {
      owner_id: null | number;
      owner_name: null | string;
      status: string;
      conclusion: null | string;
      submitted_by: null | number;
      submitted_by_name: null | string;
      submitted_at: null | string;
      review_reason: null | string;
      reviewed_by: null | number;
      reviewed_by_name: null | string;
      reviewed_at: null | string;
      completed_at: null | string;
      events: {
        id: number;
        actor_id: number;
        actor_name: string;
        action: string;
        status: string;
        owner_id: null | number;
        conclusion: null | string;
        review_reason: null | string;
        created_at: string;
      }[];
    };
  }

  export interface ExceptionDecision {
    id: number;
    exception_id: number;
    snapshot_id: number;
    decision: 'ADOPTED' | 'REJECTED';
    reason: string;
    task_id: null | number;
    actor_id: number;
  }

  export interface ExceptionDecisionEvent extends ExceptionDecision {
    decision_id: number;
    created_at: string;
  }

  export interface FinanceCheck {
    id: number;
    order_id: number;
    scope_key: string;
    target_label: string;
    snapshot_id: number;
    assignee_id: null | number;
    status: string;
    finding: null | string;
    checked_by: null | number;
    checked_at: null | string;
    reviewed_by: null | number;
    reviewed_at: null | string;
  }
}

/** 获取指定业务对象的只读分析结果。 */
export async function getBusinessInsightApi(kind: string, objectId: number) {
  return requestClient.get<BusinessInsightApi.Insight>(
    `/insights/${kind}/${objectId}`,
  );
}

export async function getInsightSnapshotsApi(kind: string, objectId: number) {
  return requestClient.get<BusinessInsightApi.Snapshot[]>(`/insights/${kind}/${objectId}/snapshots`);
}

export async function saveInsightSnapshotApi(kind: string, objectId: number) {
  return requestClient.post<BusinessInsightApi.Snapshot>(`/insights/${kind}/${objectId}/snapshots`);
}

export async function getBatchChecksApi(balanceId: number) {
  return requestClient.get<BusinessInsightApi.CheckItem[]>(`/insights/batch-impact/${balanceId}/checks`);
}

export async function createBatchChecksApi(balanceId: number, snapshotId: number) {
  return requestClient.post<BusinessInsightApi.CheckItem[]>(`/insights/batch-impact/${balanceId}/checks`, undefined, { params: { snapshot_id: snapshotId } });
}

export async function updateBatchCheckApi(balanceId: number, checkId: number, data: { assignee_id?: null | number; finding?: string; status?: string }) {
  return requestClient.request<BusinessInsightApi.CheckItem>(`/insights/batch-impact/${balanceId}/checks/${checkId}`, { data, method: 'PATCH' });
}

export async function getBatchAssigneesApi(balanceId: number) {
  return requestClient.get<Record<number, { id: number; name: string }[]>>(`/insights/batch-impact/${balanceId}/assignees`);
}

export async function getBatchCheckEventsApi(balanceId: number, checkId: number) {
  return requestClient.get<BusinessInsightApi.CheckEvent[]>(`/insights/batch-impact/${balanceId}/checks/${checkId}/events`);
}

export async function getBatchRecallReportsApi(balanceId: number) {
  return requestClient.get<BusinessInsightApi.RecallReportSnapshot[]>(`/insights/batch-impact/${balanceId}/recall-reports`);
}

export async function createBatchRecallReportApi(balanceId: number) {
  return requestClient.post<BusinessInsightApi.RecallReportSnapshot>(`/insights/batch-impact/${balanceId}/recall-reports`);
}

export async function getRecallReportOwnersApi(balanceId: number, reportId: number) {
  return requestClient.get<{ id: number; name: string }[]>(`/insights/batch-impact/${balanceId}/recall-reports/${reportId}/owners`);
}

export async function updateRecallReportWorkflowApi(balanceId: number, reportId: number, data: { action: 'ASSIGN' | 'COMPLETE' | 'RETURN' | 'SUBMIT'; owner_id?: number; conclusion?: string; reason?: string }) {
  return requestClient.post<BusinessInsightApi.RecallReportSnapshot>(`/insights/batch-impact/${balanceId}/recall-reports/${reportId}/workflow`, data);
}

export async function getExceptionDecisionApi(exceptionId: number) {
  return requestClient.get<BusinessInsightApi.ExceptionDecision | null>(`/insights/exception-action/${exceptionId}/decision`);
}

export async function getExceptionDecisionEventsApi(exceptionId: number) {
  return requestClient.get<BusinessInsightApi.ExceptionDecisionEvent[]>(`/insights/exception-action/${exceptionId}/decision/events`);
}

export async function decideExceptionActionApi(exceptionId: number, decision: 'ADOPTED' | 'REJECTED', reason: string) {
  return requestClient.post<BusinessInsightApi.ExceptionDecision>(`/insights/exception-action/${exceptionId}/decision`, { decision, reason });
}

export async function getFinanceChecksApi(orderId: number) {
  return requestClient.get<BusinessInsightApi.FinanceCheck[]>(`/insights/finance-difference/${orderId}/checks`);
}

export async function createFinanceChecksApi(orderId: number, snapshotId: number) {
  return requestClient.post<BusinessInsightApi.FinanceCheck[]>(`/insights/finance-difference/${orderId}/checks`, undefined, { params: { snapshot_id: snapshotId } });
}

export async function updateFinanceCheckApi(orderId: number, checkId: number, data: { assignee_id?: null | number; finding?: string; status?: string }) {
  return requestClient.request<BusinessInsightApi.FinanceCheck>(`/insights/finance-difference/${orderId}/checks/${checkId}`, { data, method: 'PATCH' });
}

export async function getFinanceCheckEventsApi(orderId: number, checkId: number) {
  return requestClient.get<BusinessInsightApi.CheckEvent[]>(`/insights/finance-difference/${orderId}/checks/${checkId}/events`);
}

export async function getFinanceAssigneesApi(orderId: number) {
  return requestClient.get<{ id: number; name: string }[]>(`/insights/finance-difference/${orderId}/assignees`);
}
