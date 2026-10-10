"""AI 契约集中管理与底层依赖边界的回归检查。"""

import ast
from pathlib import Path

from pydantic import BaseModel

from app.modules.ai import schema


AI_ROOT = Path(schema.__file__).parent


def test_pydantic_contracts_are_declared_only_in_schema():
    """新增业务模块不能再次自行声明一套请求或模型输出契约。"""
    contract_names = {
        name for name, value in vars(schema).items()
        if isinstance(value, type) and issubclass(value, BaseModel)
    }
    for path in AI_ROOT.glob("*.py"):
        if path.name == "schema.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = {
                    base.id if isinstance(base, ast.Name) else base.attr
                    for base in node.bases if isinstance(base, (ast.Name, ast.Attribute))
                }
                assert not bases.intersection(contract_names), (path.name, node.name)


def test_schema_and_llm_do_not_depend_on_business_execution():
    """基础契约与模型客户端不能反向依赖会话或 Agent 业务执行。"""
    allowed = {"app.modules.ai.catalog", "app.modules.ai.agent_prompt", "app.modules.ai.schema"}
    for name in ("schema.py", "llm.py"):
        tree = ast.parse((AI_ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.modules.ai"):
                assert node.module in allowed, (name, node.module)


def test_conversation_store_does_not_depend_on_execution():
    tree = ast.parse((AI_ROOT / "conversation_store.py").read_text(encoding="utf-8"))
    allowed = {"app.modules.ai.model", "app.modules.ai.schema"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.modules.ai"):
            assert node.module in allowed, node.module


def test_history_access_does_not_depend_on_batch_executor():
    tree = ast.parse((AI_ROOT / "history_access.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.modules.ai.multi_intent"
            if node.module == "app.modules.ai":
                assert "multi_intent" not in {alias.name for alias in node.names}
