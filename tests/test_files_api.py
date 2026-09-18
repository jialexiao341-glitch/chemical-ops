"""文件上传、下载和附件关联测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.files import service
from app.modules.system.model import User
from .conftest import login


pytestmark = pytest.mark.integration


def test_upload_download_and_attach_file(client: TestClient, demo_password: str) -> None:
    """验证文件元数据、下载和业务附件去重。"""

    manager = login(client, "procurement_manager", demo_password)
    uploaded = client.post(
        "/api/v1/files",
        headers=manager,
        data={"file_category": "QUOTE", "access_level": "INTERNAL"},
        files={"file": ("test-attachment.txt", b"ChemicalOps test", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    metadata = client.get(f"/api/v1/files/{file_id}", headers=manager)
    assert metadata.status_code == 200
    assert metadata.json()["file_size_bytes"] == len(b"ChemicalOps test")
    downloaded = client.get(f"/api/v1/files/{file_id}/download", headers=manager)
    assert downloaded.status_code == 200
    assert downloaded.content == b"ChemicalOps test"

    attached = client.post(f"/api/v1/files/{file_id}/attachments", headers=manager, json={"resource_type": "PURCHASE_ORDER", "resource_id": 1})
    assert attached.status_code == 201, attached.text
    duplicate = client.post(f"/api/v1/files/{file_id}/attachments", headers=manager, json={"resource_type": "PURCHASE_ORDER", "resource_id": 1})
    assert duplicate.status_code == 409
    listed = client.get("/api/v1/files/attachments/PURCHASE_ORDER/1", headers=manager)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    private_upload = client.post(
        "/api/v1/files",
        headers=manager,
        data={"file_category": "PRIVATE_TEST", "access_level": "PRIVATE"},
        files={"file": ("private.txt", b"private", "text/plain")},
    )
    assert private_upload.status_code == 201, private_upload.text
    finance_manager = login(client, "finance_manager", demo_password)
    private_download = client.get(f"/api/v1/files/{private_upload.json()['id']}/download", headers=finance_manager)
    assert private_download.status_code == 404
    private_attach = client.post(f"/api/v1/files/{private_upload.json()['id']}/attachments", headers=finance_manager, json={"resource_type": "PURCHASE_ORDER", "resource_id": 1})
    assert private_attach.status_code == 404
    private_listing = client.get("/api/v1/files/attachments/PURCHASE_ORDER/1", headers=finance_manager)
    assert private_listing.status_code == 200
    assert private_listing.json()["total"] == 1
    assert private_listing.json()["items"][0]["file_id"] != private_upload.json()["id"]


def test_linked_file_requires_business_resource_permission(client: TestClient, demo_password: str) -> None:
    """具备通用文件权限但没有采购订单权限的用户不能通过文件 ID 绕过资源权限。"""

    procurement_manager = login(client, "procurement_manager", demo_password)
    uploaded = client.post(
        "/api/v1/files",
        headers=procurement_manager,
        data={"file_category": "ORDER_TEST", "access_level": "INTERNAL"},
        files={"file": ("order-note.txt", b"order note", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    attached = client.post(
        f"/api/v1/files/{file_id}/attachments",
        headers=procurement_manager,
        json={"resource_type": "PURCHASE_ORDER", "resource_id": 1},
    )
    assert attached.status_code == 201, attached.text

    warehouse_receiver = login(client, "warehouse_receiver", demo_password)
    assert client.get(f"/api/v1/files/{file_id}", headers=warehouse_receiver).status_code == 404
    assert client.get(f"/api/v1/files/{file_id}/download", headers=warehouse_receiver).status_code == 404
    assert client.get("/api/v1/files/attachments/PURCHASE_ORDER/1", headers=warehouse_receiver).status_code == 404


def test_minio_storage_adapter_round_trip(db_session) -> None:
    """使用假的 MinIO 客户端验证对象存储适配器的写入和读取路径。"""

    from types import SimpleNamespace

    class FakeResponse:
        def __init__(self, content: bytes):
            self.content = content

        def read(self) -> bytes:
            return self.content

        def close(self) -> None:
            pass

        def release_conn(self) -> None:
            pass

    class FakeClient:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def bucket_exists(self, bucket: str) -> bool:
            return True

        def put_object(self, bucket: str, key: str, stream, length: int, content_type: str) -> None:
            self.objects[key] = stream.read()

        def get_object(self, bucket: str, key: str) -> FakeResponse:
            return FakeResponse(self.objects[key])

        def remove_object(self, bucket: str, key: str) -> None:
            self.objects.pop(key, None)

    fake_client = FakeClient()
    settings = service.get_settings()
    fake_values = settings.model_dump()
    fake_values.update(file_storage_backend="minio", minio_access_key="access", minio_secret_key="secret", minio_bucket="bucket")
    fake_settings = SimpleNamespace(**fake_values)
    original_user = db_session.scalar(select(User).where(User.username == "system_admin"))
    assert original_user is not None
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(service, "_minio_client", lambda: fake_client)
    try:
        value = service.upload_file(db_session, original_user, file_name="adapter.txt", mime_type="text/plain", content=b"adapter", file_category="TEST", access_level="INTERNAL")
        stored, content = service.read_file(db_session, original_user, value.id)
        assert stored.object_key in fake_client.objects
        assert content == b"adapter"
    finally:
        monkeypatch.undo()


def test_upload_rejects_unsupported_or_mismatched_files(client: TestClient, demo_password: str) -> None:
    """上传入口拒绝未知扩展名、错误 MIME 和不匹配的二进制文件内容。"""

    manager = login(client, "procurement_manager", demo_password)
    unsupported = client.post(
        "/api/v1/files",
        headers=manager,
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert unsupported.status_code == 400

    mismatched_mime = client.post(
        "/api/v1/files",
        headers=manager,
        files={"file": ("report.pdf", b"%PDF-1.7", "text/plain")},
    )
    assert mismatched_mime.status_code == 400

    mismatched_signature = client.post(
        "/api/v1/files",
        headers=manager,
        files={"file": ("report.pdf", b"not a pdf", "application/pdf")},
    )
    assert mismatched_signature.status_code == 400
