"""回归用例导出：保留手工用例顺序，同名已批准用例覆盖，新用例追加。"""

from scripts.export_regression_cases import merge_cases


def test_merge_keeps_existing_order_and_appends_new_cases():
    existing = [
        {"id": "PR-old", "question": "旧问题", "expected_tasks": []},
        {"id": "PR-shared", "question": "旧共享用例", "expected_tasks": []},
    ]
    approved = [
        {"id": "PR-shared", "question": "新共享用例", "expected_tasks": ["inventory"]},
        {"id": "PR-new", "question": "新问题", "expected_tasks": ["quotes"]},
    ]

    merged = merge_cases(existing, approved)

    assert [row["id"] for row in merged] == ["PR-old", "PR-shared", "PR-new"]
    assert merged[1]["question"] == "新共享用例"
    assert merged[1]["expected_tasks"] == ["inventory"]


def test_merge_without_existing_uses_approved_list():
    approved = [{"id": "PR-new", "question": "新问题"}]
    assert merge_cases([], approved) == approved
