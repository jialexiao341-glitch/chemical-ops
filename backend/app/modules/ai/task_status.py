"""Agent 与多意图执行状态；状态值用于存储/API，中文说明用于展示。"""

from enum import StrEnum


class TaskStatus(StrEnum):
    """单项只读任务从规划到终止的状态；等待补充与依赖阻塞不视为成功。"""
    PENDING = "PENDING"  # 已识别，尚未生成执行计划
    PLANNED = "PLANNED"  # 计划已生成并通过校验
    RUNNING = "RUNNING"  # 正在执行只读查询
    WAITING_INPUT = "WAITING_INPUT"  # 缺少参数或存在候选歧义，需要补充
    SUCCEEDED = "SUCCEEDED"  # 已执行且有可核验结果；空结果也是成功
    FAILED = "FAILED"  # 校验、权限、模型或执行失败
    BLOCKED = "BLOCKED"  # 前置任务未成功，当前任务没有执行
    CANCELLED = "CANCELLED"  # 用户取消，后续任务没有执行


class BatchStatus(StrEnum):
    """由全部子任务终态计算的批次结果，不覆盖各项的具体失败原因。"""
    SUCCEEDED = "SUCCEEDED"  # 所有子任务成功
    PARTIAL = "PARTIAL"  # 至少一项成功，仍有未完成子任务
    WAITING_INPUT = "WAITING_INPUT"  # 没有成功结果，且需要用户补充
    FAILED = "FAILED"  # 没有成功结果，存在失败或阻塞
    CANCELLED = "CANCELLED"  # 整批在执行前取消


TASK_STATUS_LABELS = {
    TaskStatus.PENDING: "待规划", TaskStatus.PLANNED: "待执行", TaskStatus.RUNNING: "执行中",
    TaskStatus.WAITING_INPUT: "待补充", TaskStatus.SUCCEEDED: "已完成", TaskStatus.FAILED: "失败",
    TaskStatus.BLOCKED: "依赖阻塞", TaskStatus.CANCELLED: "已取消", BatchStatus.PARTIAL: "部分完成",
}
