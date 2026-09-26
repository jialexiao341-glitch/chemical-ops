"""批量主数据操作的端到端规则。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import login


def test_batch_requires_login(client: TestClient) -> None:
    response = client.post("/api/v1/batch/master.chemicals/delete", json={"ids": [1]})
    assert response.status_code == 401


def test_chemical_batch_disable_and_export(client: TestClient, demo_password: str) -> None:
    headers = login(client, "system_admin", demo_password)
    suffix = uuid4().hex[:12]
    ids = []
    for number in range(2):
        response = client.post(
            "/api/v1/chemicals",
            headers=headers,
            json={"chemical_name": f"批量测试-{suffix}-{number}"},
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])

    exported = client.post(
        "/api/v1/batch/master.chemicals/export", headers=headers, json={"ids": ids}
    )
    assert exported.status_code == 200, exported.text
    assert exported.content.startswith(b"\xef\xbb\xbf")
    assert f"批量测试-{suffix}-0" in exported.text

    disabled = client.post(
        "/api/v1/batch/master.chemicals/delete", headers=headers, json={"ids": ids}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"action": "disabled", "count": 2}
    for chemical_id in ids:
        item = client.get(f"/api/v1/chemicals/{chemical_id}", headers=headers)
        assert item.status_code == 200
        assert item.json()["status"] == "INACTIVE"


def test_batch_import_is_atomic_on_invalid_row(client: TestClient, demo_password: str) -> None:
    headers = login(client, "system_admin", demo_password)
    suffix = uuid4().hex[:12]
    name = f"导入测试-{suffix}"
    csv_content = f'chemical_name\n{name}\n""\n'.encode("utf-8")

    response = client.post(
        "/api/v1/batch/master.chemicals/import",
        headers=headers,
        files={"file": ("chemicals.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 400, response.text
    listed = client.get("/api/v1/chemicals", headers=headers, params={"keyword": name})
    assert listed.status_code == 200
    assert listed.json()["total"] == 0
