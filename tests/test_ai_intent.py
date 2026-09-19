from app.modules.ai.agent_prompt import PROJECT_CAPABILITY_REPLY, UNSUPPORTED_REPLY, build_project_reply
from app.modules.ai.intent import Intent, classify_intent


def test_intent_recognizes_supported_categories():
    assert classify_intent("\u4f60\u597d").intent is Intent.GREETING
    assert classify_intent("\u76ee\u524d\u9879\u76ee\u6709\u54ea\u4e9b\u529f\u80fd").intent is Intent.PROJECT
    assert classify_intent("\u4f60\u662f\u5e72\u4ec0\u4e48\u7684").intent is Intent.PROJECT
    assert classify_intent("\u4f60\u80fd\u5e72\u4ec0\u4e48").intent is Intent.PROJECT
    assert classify_intent("\u4f60\u597d\uff0c\u4f60\u80fd\u5e2e\u6211\u4ec0\u4e48").intent is Intent.PROJECT
    assert classify_intent("\u67e5\u8be2\u6700\u8fd1\u91c7\u8d2d\u8ba2\u5355\u6570\u91cf").intent is Intent.QUERY
    assert classify_intent("\u4eca\u5929\u676d\u5dde\u5929\u6c14\u600e\u4e48\u6837").intent is Intent.UNSUPPORTED


def test_agent_replies_are_chinese_and_outside_scope_is_explicit():
    assert "\u53ea\u652f\u6301\u67e5\u8be2\u548c\u5206\u6790" in PROJECT_CAPABILITY_REPLY
    assert "\u4e0d\u5728" in UNSUPPORTED_REPLY


def test_project_reply_composes_relevant_examples():
    reply = build_project_reply("\u4f60\u6709\u4ec0\u4e48\u529f\u80fd\uff1f\u6211\u60f3\u770b\u5e93\u5b58")
    assert "\u5206\u6790\u5f53\u524d\u5e93\u5b58\u9884\u8b66" in reply
    assert "\u652f\u6301\u67e5\u8be2\u548c\u5206\u6790" in reply
