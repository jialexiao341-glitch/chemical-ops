"""从 Pydantic 契约生成模型侧的严格 JSON Schema，不维护第二份字段表。"""

from pydantic import BaseModel


def schema_response_format(model: type[BaseModel], name: str) -> dict:
    schema = model.model_json_schema()

    def strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            # 当前服务的 Schema 子集不接受 format=date；模型约束 ISO 外形，Pydantic 校验真实日期。
            if node.get("format") == "date":
                node.pop("format")
                node["pattern"] = r"^\d{4}-\d{2}-\d{2}$"
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in list(node.values()):
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)

    strict(schema)
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
