from app.modules.ai.agent_prompt import PROJECT_CAPABILITY_REPLY, UNSUPPORTED_REPLY, build_project_reply
from app.modules.ai.schema import Intent
from app.modules.ai.evaluation import classify_intent


def test_intent_recognizes_supported_categories():
    assert classify_intent("\u4f60\u597d").intent is Intent.GREETING
    assert classify_intent("\u76ee\u524d\u9879\u76ee\u6709\u54ea\u4e9b\u529f\u80fd").intent is Intent.PROJECT
    assert classify_intent("\u4f60\u662f\u5e72\u4ec0\u4e48\u7684").intent is Intent.PROJECT
    assert classify_intent("\u4f60\u80fd\u5e72\u4ec0\u4e48").intent is Intent.PROJECT
    assert classify_intent("\u4f60\u597d\uff0c\u4f60\u80fd\u5e2e\u6211\u4ec0\u4e48").intent is Intent.PROJECT
    assert classify_intent("\u6211\u53ef\u4ee5\u95ee\u4f60\u4ec0\u4e48\u91c7\u8d2d\u7684\u95ee\u9898\u5462").intent is Intent.PROJECT
    assert classify_intent("\u80fd\u95ee\u4f60\u54ea\u4e9b\u8d28\u91cf\u95ee\u9898").intent is Intent.PROJECT
    assert classify_intent("\u67e5\u8be2\u6700\u8fd1\u91c7\u8d2d\u8ba2\u5355\u6570\u91cf").intent is Intent.QUERY
    assert classify_intent("\u4eca\u5929\u676d\u5dde\u5929\u6c14\u600e\u4e48\u6837").intent is Intent.UNSUPPORTED


def test_agent_replies_are_chinese_and_outside_scope_is_explicit():
    assert "\u53ea\u652f\u6301\u67e5\u8be2\u548c\u5206\u6790" in PROJECT_CAPABILITY_REPLY
    assert "\u4e0d\u5728" in UNSUPPORTED_REPLY


def test_project_reply_composes_relevant_examples():
    reply = build_project_reply("\u4f60\u6709\u4ec0\u4e48\u529f\u80fd\uff1f\u6211\u60f3\u770b\u5e93\u5b58")
    assert "\u5206\u6790\u5f53\u524d\u5e93\u5b58\u9884\u8b66" in reply
    assert "\u652f\u6301\u67e5\u8be2\u548c\u5206\u6790" in reply


def test_project_question_about_what_to_ask_returns_examples_not_live_data():
    question = "\u6211\u53ef\u4ee5\u95ee\u4f60\u4ec0\u4e48\u91c7\u8d2d\u7684\u95ee\u9898\u5462"
    assert classify_intent(question).intent is Intent.PROJECT
    reply = build_project_reply(question)
    assert "\u53ef\u4ee5\u3002\u4f60\u53ef\u4ee5\u53c2\u8003\u4e0b\u9762\u8fd9\u4e9b\u95ee\u6cd5" in reply
    assert "\u67e5\u8be2\u672c\u6708\u5404\u4f9b\u5e94\u5546\u7684\u91c7\u8d2d\u8ba2\u5355\u91d1\u989d\u6392\u540d" in reply
    assert "413" not in reply
