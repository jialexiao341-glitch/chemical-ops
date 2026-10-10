/** 与后端 task_status.py 对齐；状态值用于接口，中文标签用于展示。 */
export enum AiTaskStatus {
  PENDING = 'PENDING',
  PLANNED = 'PLANNED',
  RUNNING = 'RUNNING',
  WAITING_INPUT = 'WAITING_INPUT',
  SUCCEEDED = 'SUCCEEDED',
  FAILED = 'FAILED',
  BLOCKED = 'BLOCKED',
  CANCELLED = 'CANCELLED',
}

/** 批次状态由全部子任务终态计算，PARTIAL 不表示全部完成。 */
export enum AiBatchStatus {
  SUCCEEDED = 'SUCCEEDED',
  PARTIAL = 'PARTIAL',
  WAITING_INPUT = 'WAITING_INPUT',
  FAILED = 'FAILED',
  CANCELLED = 'CANCELLED',
}

export const AI_TASK_STATUS_LABELS: Record<AiTaskStatus, string> = {
  PENDING: '待规划', PLANNED: '待执行', RUNNING: '正在查询',
  WAITING_INPUT: '等待补充', SUCCEEDED: '查询完成', FAILED: '已停止',
  BLOCKED: '依赖阻塞', CANCELLED: '已取消',
};

export const AI_BATCH_STATUS_LABELS: Record<AiBatchStatus, string> = {
  SUCCEEDED: '全部完成', PARTIAL: '部分完成', WAITING_INPUT: '等待补充',
  FAILED: '失败', CANCELLED: '已取消',
};
