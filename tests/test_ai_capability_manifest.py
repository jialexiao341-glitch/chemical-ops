"""按当前用户权限构建路由能力清单。"""

import json
from types import SimpleNamespace

from app.modules.ai import capabilities
from app.modules.ai.catalog import catalog_prompt


def test_manifest_exposes_only_current_tools_datasets_and_non_identifying_scopes(monkeypatch):
    monkeypatch.setattr(capabilities, "get_user_role_codes", lambda *_: ["BUYER"])
    monkeypatch.setattr(capabilities, "get_user_permission_codes", lambda *_: {
        "master.products.read", "warehouse.inventory.read", "procurement.rfqs.read",
        "procurement.orders.read", "warehouse.deliveries.read", "ai.workspace.read",
        "master.suppliers.read", "operations.exceptions.read",
    })
    monkeypatch.setattr(capabilities, "accessible_warehouse_ids", lambda *_: {17, 42})
    monkeypatch.setattr(capabilities, "agent_enabled", lambda: True)

    manifest = capabilities.build_capability_manifest(object(), SimpleNamespace(id=7))
    payload = manifest.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False)

    assert {item["name"] for item in payload["agent_tools"]} == {
        "catalog.search_products", "inventory.query_available",
        "supplier_quotes.find_rfq_items", "supplier_quotes.compare",
        "purchase_orders.trace_by_no",
    }
    datasets = {item["key"] for item in payload["analytics_datasets"]}
    assert {"purchase_orders", "deliveries", "inventory", "weekly_order_risks"} <= datasets
    assert "accepted_orders_finance_gaps" not in datasets
    assert '"17"' not in serialized and '"42"' not in serialized
    assert "permission_codes" not in payload and "user_id" not in serialized
    assert payload["resource_scopes"] == ["currently_accessible_warehouses"]


def test_manifest_tool_metadata_is_sourced_from_registered_tool_spec(monkeypatch):
    monkeypatch.setattr(capabilities, "get_user_role_codes", lambda *_: ["SYS_ADMIN"])
    monkeypatch.setattr(capabilities, "get_user_permission_codes", lambda *_: set())
    monkeypatch.setattr(capabilities, "accessible_warehouse_ids", lambda *_: None)
    monkeypatch.setattr(capabilities, "agent_enabled", lambda: True)

    payload = capabilities.build_capability_manifest(object(), SimpleNamespace(id=7)).model_dump(mode="json")
    expected = {name: {
        "version": spec.version,
        "risk": spec.risk,
        "retry_policy": spec.retry_policy,
        "idempotent": spec.idempotent,
        "cost_class": spec.cost_class,
        "quota_class": spec.quota_class,
    } for name, spec in capabilities.TOOLS.items()}

    actual = {item["name"]: {key: item[key] for key in expected[item["name"]]}
              for item in payload["agent_tools"]}
    assert actual == expected


def test_manifest_omits_agent_and_document_capabilities_when_disabled_or_unavailable(monkeypatch):
    monkeypatch.setattr(capabilities, "get_user_role_codes", lambda *_: ["SUPPLIER_PORTAL"])
    monkeypatch.setattr(capabilities, "get_user_permission_codes", lambda *_: {"ai.workspace.read"})
    monkeypatch.setattr(capabilities, "accessible_warehouse_ids", lambda *_: set())
    monkeypatch.setattr(capabilities, "agent_enabled", lambda: False)

    payload = capabilities.build_capability_manifest(object(), SimpleNamespace(id=7)).model_dump(mode="json")

    assert payload["agent_tools"] == []
    assert payload["analytics_datasets"] == []
    assert payload["document_search"] is True
    assert payload["resource_scopes"] == []


def test_analytics_catalog_can_be_limited_to_manifest_dataset_keys():
    visible = json.loads(catalog_prompt({"purchase_orders", "inventory"}))

    assert set(visible) == {"purchase_orders", "inventory"}
