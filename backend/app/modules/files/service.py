"""文件本地存储、下载和业务附件权限校验。"""

from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, get_settings
from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery
from app.modules.finance.model import FinanceInvoice
from app.modules.files.schema import FileAttachmentCreate
from app.modules.files.scanner import scan_content
from app.modules.inventory_returns.model import InventoryReturnRequest
from app.modules.operation_exceptions.model import OperationException
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.replenishments.model import ReplenishmentRequest
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.file_model import SysFile, SysFileAttachment
from app.modules.system.model import User


RESOURCE_MODELS = {
    "PURCHASE_ORDER": PurchaseOrder,
    "DELIVERY": Delivery,
    "QUALITY_ACCEPTANCE": QualityAcceptance,
    "OPERATION_EXCEPTION": OperationException,
    "FINANCE_INVOICE": FinanceInvoice,
    "INVENTORY_RETURN": InventoryReturnRequest,
    "REPLENISHMENT": ReplenishmentRequest,
}

RESOURCE_READ_PERMISSIONS = {
    "PURCHASE_ORDER": "procurement.orders.read",
    "DELIVERY": "warehouse.deliveries.read",
    "QUALITY_ACCEPTANCE": "quality.acceptances.read",
    "OPERATION_EXCEPTION": "operations.exceptions.read",
    "FINANCE_INVOICE": "finance.invoices.read",
    "INVENTORY_RETURN": "warehouse.inventory.return.read",
    "REPLENISHMENT": "procurement.replenishment.read",
}

_GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
_EXTENSION_MIME_TYPES: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "doc": {"application/msword"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xls": {"application/vnd.ms-excel"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "ppt": {"application/vnd.ms-powerpoint"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "csv": {"text/csv", "text/plain", "application/vnd.ms-excel"},
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/plain"},
    "json": {"application/json", "text/plain"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
}


def _normalise_mime_type(mime_type: str) -> str:
    """去掉 MIME 参数，避免浏览器附带 charset 导致误判。"""
    return (mime_type or "").split(";", 1)[0].strip().lower()


def _validate_file_signature(extension: str, content: bytes) -> None:
    """对常见二进制文件做轻量魔数校验；这不是病毒扫描的替代品。"""
    signatures = {
        "pdf": content.startswith(b"%PDF"),
        "png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": content.startswith(b"\xff\xd8\xff"),
        "jpeg": content.startswith(b"\xff\xd8\xff"),
        "doc": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "xls": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "ppt": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "docx": content.startswith(b"PK"),
        "xlsx": content.startswith(b"PK"),
        "pptx": content.startswith(b"PK"),
    }
    if extension in signatures and not signatures[extension]:
        raise BusinessValidationError("文件内容与扩展名不匹配，已拒绝上传")


def storage_root() -> Path:
    """返回存储根目录，并保证它位于项目目录内。"""
    configured = Path(get_settings().file_storage_root)
    root = configured if configured.is_absolute() else PROJECT_ROOT / configured
    root = root.resolve()
    project_root = PROJECT_ROOT.resolve()
    if project_root not in root.parents and root != project_root:
        raise BusinessValidationError("文件存储目录必须位于项目目录内")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _storage_backend() -> str:
    """读取并校验文件存储后端。"""
    backend = get_settings().file_storage_backend.strip().lower()
    if backend not in {"local", "minio", "s3"}:
        raise BusinessValidationError("文件存储后端只支持 local 或 minio/s3")
    return backend


def _minio_bucket_for_key(object_key: str) -> str:
    """按对象键将原始文档和解析结果分到不同 MinIO 桶。"""

    settings = get_settings()
    return settings.minio_result_bucket if object_key.startswith("results/") else settings.minio_document_bucket or settings.minio_bucket


def _minio_client():
    """创建 MinIO/S3 兼容客户端，避免本地模式强制依赖对象存储。"""
    settings = get_settings()
    if not settings.minio_access_key or not settings.minio_secret_key:
        raise BusinessValidationError("对象存储未配置访问密钥")
    try:
        from minio import Minio
    except ImportError as exc:
        raise BusinessValidationError("对象存储功能缺少 minio 依赖，请重新安装后端依赖") from exc
    client = Minio(settings.minio_endpoint, access_key=settings.minio_access_key, secret_key=settings.minio_secret_key, secure=settings.minio_secure, region=settings.minio_region)
    for bucket in {settings.minio_document_bucket or settings.minio_bucket, settings.minio_result_bucket or settings.minio_bucket}:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket, location=settings.minio_region)
    return client


def _put_object(object_key: str, content: bytes, mime_type: str) -> None:
    """将文件内容写入当前对象存储。"""
    if _storage_backend() == "local":
        target = storage_root() / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return
    settings = get_settings()
    _minio_client().put_object(_minio_bucket_for_key(object_key), object_key, BytesIO(content), length=len(content), content_type=mime_type)


def _delete_object(object_key: str) -> None:
    """删除数据库写入失败时已创建的对象。"""
    if _storage_backend() == "local":
        target = (storage_root() / object_key).resolve()
        root = storage_root().resolve()
        if root in target.parents and target.exists():
            target.unlink()
        return
    _minio_client().remove_object(_minio_bucket_for_key(object_key), object_key)


def store_parse_result(file_id: int, markdown: str) -> str | None:
    """保存解析后的 Markdown 到 results 对象空间，并返回对象键。"""

    if not markdown.strip():
        return None
    object_key = f"results/{file_id}/{uuid4().hex}.md"
    _put_object(object_key, markdown.encode("utf-8"), "text/markdown; charset=utf-8")
    return object_key


def _require_file(db: Session, file_id: int) -> SysFile:
    """查询文件元数据。"""
    value = db.get(SysFile, file_id)
    if value is None:
        raise ResourceNotFoundError(f"文件 {file_id} 不存在")
    return value


def _is_system_admin(db: Session, user: User) -> bool:
    """判断用户是否拥有跨业务资源的系统管理员权限。"""

    return "SYS_ADMIN" in get_user_role_codes(db, user.id)


def _can_read_resource(db: Session, user: User, resource_type: str) -> bool:
    """判断用户是否拥有指定业务资源的读取权限。"""

    if _is_system_admin(db, user):
        return True
    required_permission = RESOURCE_READ_PERMISSIONS.get(resource_type)
    return required_permission is not None and required_permission in get_user_permission_codes(db, user.id)


def _check_resource_access(db: Session, user: User, resource_type: str, resource_id: int) -> None:
    """校验业务附件接口不会绕过对应业务资源的读取权限。"""

    model = RESOURCE_MODELS.get(resource_type)
    if model is None:
        raise BusinessValidationError("该资源类型暂不支持附件权限校验")
    if not _can_read_resource(db, user, resource_type):
        raise ResourceNotFoundError(f"业务资源 {resource_type}:{resource_id} 不存在")
    if db.get(model, resource_id) is None:
        raise ResourceNotFoundError(f"业务资源 {resource_type}:{resource_id} 不存在")


def _check_file_access(db: Session, user: User, value: SysFile) -> None:
    """校验文件自身权限，并阻止通过文件 ID 绕过已关联资源权限。"""

    is_admin = _is_system_admin(db, user)
    if value.access_level == "PRIVATE" and value.uploader_id != user.id and not is_admin:
        raise ResourceNotFoundError(f"文件 {value.id} 不存在")
    if is_admin or (value.access_level == "PRIVATE" and value.uploader_id == user.id):
        return
    linked_resources = db.scalars(select(SysFileAttachment).where(SysFileAttachment.file_id == value.id)).all()
    if linked_resources and not any(_can_read_resource(db, user, item.resource_type) for item in linked_resources):
        raise ResourceNotFoundError(f"文件 {value.id} 不存在")


def recover_stale_parses(db: Session, *, stale_after_seconds: int) -> int:
    """将进程中断后长期停留的解析任务标记为失败，允许用户重新提交。"""

    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds 必须大于 0")
    cutoff = datetime.now() - timedelta(seconds=stale_after_seconds)
    values = list(
        db.scalars(
            select(SysFile).where(SysFile.parse_status == "PROCESSING", SysFile.updated_at < cutoff)
        ).all()
    )
    for value in values:
        value.parse_status = "FAILED"
        value.parse_error = "解析任务因服务中断或超时结束，请重新提交"
    if values:
        db.commit()
    return len(values)


def upload_file(db: Session, user: User, *, file_name: str, mime_type: str, content: bytes, file_category: str, access_level: str) -> SysFile:
    """校验文件并写入本地对象存储，再保存文件元数据。"""
    safe_name = Path(file_name or "").name
    if not safe_name or safe_name in {".", ".."}:
        raise BusinessValidationError("文件名不能为空")
    extension = Path(safe_name).suffix.lower().lstrip(".")
    allowed = {item.strip().lower() for item in get_settings().document_allowed_extensions.split(",") if item.strip()}
    if extension not in allowed:
        raise BusinessValidationError(f"不支持的文件类型：{extension or '无扩展名'}")
    normalised_mime_type = _normalise_mime_type(mime_type)
    expected_mime_types = _EXTENSION_MIME_TYPES.get(extension, set())
    if expected_mime_types and normalised_mime_type not in _GENERIC_MIME_TYPES and normalised_mime_type not in expected_mime_types:
        raise BusinessValidationError("文件扩展名与 MIME 类型不匹配，已拒绝上传")
    _validate_file_signature(extension, content)
    max_bytes = get_settings().document_max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise BusinessValidationError(f"文件大小不能超过 {get_settings().document_max_size_mb} MB")
    if access_level not in {"PRIVATE", "INTERNAL", "PUBLIC"}:
        raise BusinessValidationError("文件访问级别不正确")
    scan_result = scan_content(content)
    if scan_result.status == "INFECTED":
        raise BusinessValidationError("文件未通过安全扫描，已拒绝上传")
    if scan_result.status not in {"SKIPPED", "CLEAN"}:
        raise BusinessValidationError("文件安全扫描服务不可用，暂时无法上传")
    object_key = f"documents/{uuid4().hex}{Path(safe_name).suffix.lower()}"
    stored_mime_type = normalised_mime_type or "application/octet-stream"
    _put_object(object_key, content, stored_mime_type)
    value = SysFile(file_name=safe_name, object_key=object_key, mime_type=stored_mime_type, file_size_bytes=len(content), sha256_hash=sha256(content).hexdigest(), file_category=file_category, access_level=access_level, uploader_id=user.id, parse_status="NOT_STARTED")
    db.add(value)
    try:
        db.flush()
        add_audit_log(db, actor_id=user.id, action_type="UPLOAD", resource_type="SYS_FILE", resource_id=value.id, request_summary=f"上传文件 {safe_name}", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        try:
            _delete_object(object_key)
        except Exception:
            pass
        raise
    return _require_file(db, value.id)


def get_file(db: Session, user: User, file_id: int) -> SysFile:
    """查询文件元数据。"""
    value = _require_file(db, file_id)
    _check_file_access(db, user, value)
    return value


def read_file(db: Session, user: User, file_id: int) -> tuple[SysFile, bytes]:
    """读取文件对象内容，并同时校验文件元数据。"""
    value = _require_file(db, file_id)
    _check_file_access(db, user, value)
    if _storage_backend() == "local":
        root = storage_root().resolve()
        target = (root / value.object_key).resolve()
        if root not in target.parents or not target.is_file():
            raise ResourceNotFoundError("文件对象不存在或已失效")
        return value, target.read_bytes()
    response = None
    try:
        response = _minio_client().get_object(_minio_bucket_for_key(value.object_key), value.object_key)
        return value, response.read()
    except BusinessValidationError:
        raise
    except Exception as exc:
        raise ResourceNotFoundError("文件对象不存在或已失效") from exc
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def attach_file(db: Session, user: User, file_id: int, data: FileAttachmentCreate) -> SysFileAttachment:
    """将文件关联到已存在的业务资源。"""
    file_value = _require_file(db, file_id)
    _check_file_access(db, user, file_value)
    _check_resource_access(db, user, data.resource_type, data.resource_id)
    if db.scalar(select(SysFileAttachment).where(SysFileAttachment.file_id == file_id, SysFileAttachment.resource_type == data.resource_type, SysFileAttachment.resource_id == data.resource_id)) is not None:
        raise DuplicateResourceError("该文件已经关联到此业务资源")
    value = SysFileAttachment(file_id=file_id, resource_type=data.resource_type, resource_id=data.resource_id, created_by=user.id)
    db.add(value)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="ATTACH", resource_type="SYS_FILE", resource_id=file_id, request_summary=f"关联附件到 {data.resource_type}:{data.resource_id}", result_status="SUCCESS")
    db.commit()
    return db.get(SysFileAttachment, value.id)


def list_attachments(db: Session, user: User, resource_type: str, resource_id: int, *, page: int, page_size: int):
    """按当前用户可访问范围分页查询业务对象附件。"""
    _check_resource_access(db, user, resource_type, resource_id)
    condition = [
        SysFileAttachment.resource_type == resource_type,
        SysFileAttachment.resource_id == resource_id,
    ]
    if not _is_system_admin(db, user):
        condition.append(or_(SysFile.access_level != "PRIVATE", SysFile.uploader_id == user.id))
    total = db.scalar(select(func.count(SysFileAttachment.id)).join(SysFile, SysFile.id == SysFileAttachment.file_id).where(*condition)) or 0
    items = list(db.scalars(select(SysFileAttachment).join(SysFile, SysFile.id == SysFileAttachment.file_id).where(*condition).order_by(SysFileAttachment.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total
