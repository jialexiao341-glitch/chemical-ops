"""AI 请求意图识别。

意图识别先在后端完成，避免把天气、新闻等范围外问题交给业务数据查询链。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    """AI 当前支持的四类入口意图。"""

    QUERY = "query"
    PROJECT = "project"
    GREETING = "greeting"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    reason: str


# 打招呼：命中后直接返回固定问候，不调用数据库和大模型。
GREETING_MARKERS = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "hello",
    "hi",
    "hey",
    "在吗",
    "有人吗",
    "早上好",
    "上午好",
    "中午好",
    "下午好",
    "晚上好",
    "辛苦了",
)


# 项目功能咨询：优先级高于通用“有哪些/支持哪些”查询词。
PROJECT_MARKERS = (
    "你能干什么",
    "你能做什么",
    "你可以做什么",
    "你是干什么的",
    "你是做什么的",
    "你是干嘛的",
    "你是谁",
    "你是什么",
    "你会什么",
    "你的作用",
    "你的职责",
    "可以帮我什么",
    "能帮我什么",
    "能帮忙做什么",
    "能提供什么",
    "能解决什么问题",
    "请介绍一下你自己",
    "介绍一下你自己",
    "介绍下你自己",
    "ai能做什么",
    "ai可以做什么",
    "能做哪些事情",
    "能做哪些",
    "有什么功能",
    "有哪些功能",
    "支持哪些功能",
    "支持哪些能力",
    "支持什么",
    "项目有什么功能",
    "项目有哪些功能",
    "项目当前状态",
    "项目做到什么程度",
    "目前做到什么程度",
    "现在做到什么程度",
    "当前能做什么",
    "怎么使用",
    "如何使用",
    "使用方法",
    "使用说明",
    "操作说明",
    "功能介绍",
    "系统介绍",
    "帮助",
)


# 范围外问题：明确拦截，不进入业务查询和通用模型回答。
UNSUPPORTED_MARKERS = (
    "天气",
    "天气预报",
    "新闻",
    "热点",
    "热搜",
    "微博热搜",
    "股票",
    "股价",
    "基金",
    "彩票",
    "写诗",
    "作诗",
    "讲故事",
    "写小说",
    "旅游攻略",
    "旅行攻略",
    "外卖",
    "电影推荐",
    "电视剧推荐",
    "歌曲推荐",
    "唱歌",
)


# 查询咨询：这些词只表示“可能是业务查询”，最终仍由 Text2SQL 白名单和权限校验兜底。
QUERY_MARKERS = (
    "采购",
    "采购申请",
    "采购订单",
    "订单",
    "库存",
    "库存余额",
    "库存批次",
    "到货",
    "收货",
    "入库",
    "入库单",
    "质量",
    "质量验收",
    "验收",
    "合格",
    "不合格",
    "异常",
    "逾期",
    "财务",
    "对账",
    "发票",
    "付款",
    "结算",
    "供应商",
    "供应商数量",
    "查询",
    "查一下",
    "查查",
    "看一下",
    "帮我看",
    "告诉我",
    "多少",
    "数量",
    "金额",
    "总额",
    "合计",
    "统计",
    "列表",
    "明细",
    "记录",
    "排名",
    "占比",
    "平均",
    "趋势",
    "最近",
    "今年",
    "本月",
    "上月",
    "按",
    "分组",
)


def classify_intent(text: str) -> IntentResult:
    """按确定性规则识别入口意图；不确定时默认拒绝。"""

    normalized = text.strip().lower()
    if not normalized:
        return IntentResult(Intent.UNSUPPORTED, "empty")
    if any(marker in normalized for marker in PROJECT_MARKERS):
        return IntentResult(Intent.PROJECT, "project_marker")
    if any(marker in normalized for marker in GREETING_MARKERS):
        return IntentResult(Intent.GREETING, "greeting_marker")
    if any(marker in normalized for marker in UNSUPPORTED_MARKERS):
        return IntentResult(Intent.UNSUPPORTED, "unsupported_marker")
    if any(marker in normalized for marker in QUERY_MARKERS):
        return IntentResult(Intent.QUERY, "business_query_marker")
    return IntentResult(Intent.UNSUPPORTED, "no_supported_marker")
