import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';
import { notifyNotificationChanged } from '../core/notification';

export namespace OperationExceptionApi {
  /** 运营异常，对应后端 OperationExceptionRead */
  export interface Exception {
    closing_note?: null | string;
    closed_at?: null | string;
    closed_by?: null | number;
    created_at?: string;
    delivery_id?: null | number;
    delivery_item_id?: null | number;
    description: string;
    due_at?: null | string;
    exception_no: string;
    exception_type: string;
    id: number;
    owner_id?: null | number;
    po_id?: null | number;
    responsible_department_id?: null | number;
    severity: string;
    source_id: number;
    source_type: string;
    status: string;
    updated_at?: string;
  }

  export interface AssigneeOption {
    display_name: string;
    id: number;
    username: string;
  }

  /** 异常处理任务 */
  export interface Task {
    assignee_id?: null | number;
    completion_note?: null | string;
    completed_at?: null | string;
    created_at?: string;
    due_at?: null | string;
    exception_id: number;
    id: number;
    priority: string;
    status: string;
    title: string;
    updated_at?: string;
  }

  export interface MyTask extends Task { exception_no: string }

  /** 任务处理记录 */
  export interface Comment {
    attachment_file_id?: null | number;
    commenter_id: number;
    content: string;
    created_at?: string;
    id: number;
    task_id: number;
  }

  /** 更新异常（指派负责人 / 推进状态） */
  export interface ExceptionUpdate {
    closing_note?: string;
    due_at?: null | string;
    owner_id?: null | number;
    /** PROCESSING | RESOLVED | CLOSED | CANCELLED，按当前状态后端校验合法流转 */
    status?: string;
  }

  export interface TaskPayload {
    assignee_id?: null | number;
    due_at?: null | string;
    priority?: string;
    title: string;
  }

  export interface TaskUpdate {
    assignee_id?: null | number;
    completion_note?: string;
    due_at?: null | string;
    priority?: string;
    /** PROCESSING | COMPLETED | CANCELLED */
    status?: string;
    title?: string;
  }

  export interface ListParams extends PageQuery {
    exception_type?: string;
    status?: string;
  }
}

/** 按当前部门范围查询异常经办人候选项 */
export async function getExceptionAssigneeOptionsApi() {
  return requestClient.get<OperationExceptionApi.AssigneeOption[]>(
    '/operation-exceptions/assignees',
  );
}

/** 分页查询运营异常 */
export async function getExceptionListApi(
  params?: OperationExceptionApi.ListParams,
) {
  return requestClient.get<PageResult<OperationExceptionApi.Exception>>(
    '/operation-exceptions',
    { params },
  );
}

/** 查询异常详情 */
export async function getExceptionApi(id: number) {
  return requestClient.get<OperationExceptionApi.Exception>(
    `/operation-exceptions/${id}`,
  );
}

/** 指派负责人并推进异常状态 */
export async function updateExceptionApi(
  id: number,
  data: OperationExceptionApi.ExceptionUpdate,
) {
  return requestClient.request<OperationExceptionApi.Exception>(
    `/operation-exceptions/${id}`,
    { data, method: 'PATCH' },
  );
}

/** 分页查询异常下的处理任务 */
export async function getTaskListApi(
  exceptionId: number,
  params?: PageQuery,
) {
  return requestClient.get<PageResult<OperationExceptionApi.Task>>(
    `/operation-exceptions/${exceptionId}/tasks`,
    { params },
  );
}

/** 按当前负责人分页读取待办；详情会再次核验是否已改派。 */
export async function getMyOperationTasksApi(page: number, pageSize: number, status = 'ACTIVE') {
  return requestClient.get<PageResult<OperationExceptionApi.MyTask>>('/operation-exceptions/my-tasks', { params: { page, page_size: pageSize, status } });
}
export async function getMyOperationTaskApi(taskId: number) {
  return requestClient.get<OperationExceptionApi.MyTask>(`/operation-exceptions/my-tasks/${taskId}`);
}
export async function getOperationTaskApi(exceptionId: number, taskId: number) {
  return requestClient.get<OperationExceptionApi.Task>(`/operation-exceptions/${exceptionId}/tasks/${taskId}`);
}

/** 创建处理任务（后端会把 OPEN/RESOLVED 异常推进为 PROCESSING） */
export async function createTaskApi(
  exceptionId: number,
  data: OperationExceptionApi.TaskPayload,
) {
  const result = await requestClient.post<OperationExceptionApi.Task>(
    `/operation-exceptions/${exceptionId}/tasks`,
    data,
  );
  notifyNotificationChanged();
  return result;
}

/** 更新任务负责人、优先级、截止时间或状态 */
export async function updateTaskApi(
  exceptionId: number,
  taskId: number,
  data: OperationExceptionApi.TaskUpdate,
) {
  const result = await requestClient.request<OperationExceptionApi.Task>(
    `/operation-exceptions/${exceptionId}/tasks/${taskId}`,
    { data, method: 'PATCH' },
  );
  notifyNotificationChanged();
  return result;
}

/** 追加任务处理记录 */
export async function createCommentApi(
  exceptionId: number,
  taskId: number,
  content: string,
) {
  return requestClient.post<OperationExceptionApi.Comment>(
    `/operation-exceptions/${exceptionId}/tasks/${taskId}/comments`,
    { content },
  );
}

/** 分页查询任务处理记录 */
export async function getCommentListApi(
  exceptionId: number,
  taskId: number,
  params?: PageQuery,
) {
  return requestClient.get<PageResult<OperationExceptionApi.Comment>>(
    `/operation-exceptions/${exceptionId}/tasks/${taskId}/comments`,
    { params },
  );
}
