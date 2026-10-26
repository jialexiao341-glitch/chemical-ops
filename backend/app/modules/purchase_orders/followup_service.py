"""门户催办协同；领域记录、交期变更、审计与通知共用事务。"""
import hashlib
import json
from datetime import timezone
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.core.time import business_today, utc_now
from app.modules.ai.model import AIAgentActionProposal
from app.modules.notifications.service import notify_users
from app.modules.purchase_orders import service as order_service
from app.modules.purchase_orders.followup import build_followup
from app.modules.purchase_orders.followup_model import DeliveryFollowup
from app.modules.purchase_orders.followup_schema import FollowupPage, FollowupRead, FollowupReply, FollowupSend
from app.modules.purchase_orders.model import PurchaseOrderEvent, PurchaseOrderItem
from app.modules.supplier_portal import service as portal_service
from app.modules.supplier_portal.model import SupplierPortalAccount
from app.modules.supplier_portal.schema import SupplierDeliveryDateUpdate
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


def _authorize(db, user, *permissions):
    if user.status != 'ACTIVE':
        raise AuthorizationError('当前账号已停用')
    if 'SYS_ADMIN' not in get_user_role_codes(db, user.id) and not set(permissions) <= set(get_user_permission_codes(db, user.id)):
        raise AuthorizationError('当前账号没有处理催办的权限')


def _active(order):
    return order.status in {'ORDERED', 'PARTIAL'} and any(i.order_quantity > i.received_quantity for i in order.items)


def _lock_order_items(db, order):
    # selectinload 是一致性读；取得主单锁后显式当前读明细，避免等待期间收货变化被旧快照遮蔽。
    items = list(db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == order.id)
        .order_by(PurchaseOrderItem.line_no).with_for_update().execution_options(populate_existing=True)).all())
    set_committed_value(order, 'items', items)


def _read(row, order, *, can_reply=False):
    return FollowupRead(id=row.id, order_id=order.id, po_no=order.po_no, message=row.message, status=row.status,
        sent_at=row.sent_at.replace(tzinfo=timezone.utc),
        replied_at=row.replied_at.replace(tzinfo=timezone.utc) if row.replied_at else None,
        reply_message=row.reply_message, reply_expected_date=row.reply_expected_date,
        can_reply=can_reply and row.status == 'SENT' and _active(order))


def _portal_recipients(db, supplier_id):
    ids = db.scalars(select(SupplierPortalAccount.user_id).join(User, User.id == SupplierPortalAccount.user_id).where(
        SupplierPortalAccount.supplier_id == supplier_id, SupplierPortalAccount.status == 'ACTIVE', User.status == 'ACTIVE')).all()
    return sorted(uid for uid in set(ids) if set(get_user_role_codes(db, uid)) == {'SUPPLIER_PORTAL'}
                  and 'supplier.portal.delivery.read' in get_user_permission_codes(db, uid))


def send_followup(db: Session, user, order_id: int, data: FollowupSend) -> FollowupRead:
    try:
        _authorize(db,user,'procurement.orders.read','procurement.orders.write','ai.workspace.read')
        order = order_service.get_order(db,user,order_id,for_update=True)
        _lock_order_items(db, order)
        proposal = db.scalar(select(AIAgentActionProposal).where(
            AIAgentActionProposal.confirmation_id == data.confirmation_id,
            AIAgentActionProposal.user_id == user.id).with_for_update())
        if proposal is None or proposal.action_type != 'deliveries.followup_draft' or proposal.resource_id != str(order_id):
            raise ResourceNotFoundError('催办草稿不存在')
        if proposal.preview_version != data.preview_version or proposal.status != 'EXECUTED':
            raise DuplicateResourceError('请先核对并保存当前版本催办草稿')
        # 当前读绕过授权查询建立的 RR 快照，等待订单锁后仍能看到并发发送结果。
        existing = db.scalar(select(DeliveryFollowup).where(DeliveryFollowup.proposal_id == proposal.id).with_for_update())
        if existing:
            if existing.supplier_id != order.supplier_id:
                raise ResourceNotFoundError('催办记录不属于当前供应商')
            return _read(existing,order)
        if not _active(order):
            raise BusinessValidationError('当前订单没有可催办的待收明细')
        draft = build_followup(db,user,order_id,note=proposal.payload.get('followup_note',''),for_update=True)
        if proposal.expected_resource_snapshot != draft['snapshot'] or (proposal.result or {}).get('message') != draft['message']:
            raise BusinessValidationError('订单来源或草稿正文已变化，请重新生成并核对')
        recipients = _portal_recipients(db,order.supplier_id)
        if not recipients:
            raise BusinessValidationError('供应商没有可接收催办的有效门户账号')
        row = DeliveryFollowup(order_id=order.id,supplier_id=order.supplier_id,proposal_id=proposal.id,
            sent_by=user.id,message=draft['message'],source_snapshot=draft['snapshot'],status='SENT')
        db.add(row); db.flush()
        order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type='DELIVERY_FOLLOWUP_SENT',
            from_status=order.status, to_status=order.status, event_time=utc_now(), created_at=utc_now(),
            event_note=f'向供应商门户发送交期催办 #{row.id}'))
        notify_users(db,recipient_ids=recipients,notification_type='DELIVERY_FOLLOWUP',title='订单交期催办',
            content='您收到一条订单交期催办，请进入供应商门户核对并回复。',related_type='DELIVERY_FOLLOWUP',related_id=row.id)
        add_audit_log(db,actor_id=user.id,action_type='SEND_FOLLOWUP',resource_type='PURCHASE_ORDER',
            resource_id=order.id,request_summary='向供应商门户发送交期催办',result_status='SUCCESS')
        db.commit()
        return _read(row,order)
    except IntegrityError:
        db.rollback()
        # 唯一约束兜底竞争；重新鉴权后只返回该用户、该订单的同一来源记录。
        _authorize(db,user,'procurement.orders.read','procurement.orders.write','ai.workspace.read')
        order = order_service.get_order(db,user,order_id,for_update=True)
        existing = db.scalar(select(DeliveryFollowup).join(AIAgentActionProposal,
            AIAgentActionProposal.id == DeliveryFollowup.proposal_id).where(
                AIAgentActionProposal.confirmation_id == data.confirmation_id,
                AIAgentActionProposal.user_id == user.id,
                AIAgentActionProposal.action_type == 'deliveries.followup_draft',
                AIAgentActionProposal.preview_version == data.preview_version,
                AIAgentActionProposal.status == 'EXECUTED',
                DeliveryFollowup.order_id == order.id,
                DeliveryFollowup.supplier_id == order.supplier_id).with_for_update())
        if existing is not None:
            return _read(existing,order)
        raise
    except Exception:
        db.rollback()
        raise


def list_followups(db: Session, user, order_id: int, *, supplier=False, page=1, page_size=20) -> FollowupPage:
    if page < 1 or not 1 <= page_size <= 100:
        raise BusinessValidationError('分页参数不正确')
    if supplier:
        _authorize(db,user,'supplier.portal.delivery.read')
        order = portal_service._require_order(db,user,order_id)
        can_reply = 'supplier.portal.delivery.update' in get_user_permission_codes(db,user.id)
    else:
        _authorize(db,user,'procurement.orders.read')
        order = order_service.get_order(db,user,order_id)
        can_reply = False
    conditions = (DeliveryFollowup.order_id == order.id,DeliveryFollowup.supplier_id == order.supplier_id)
    total = db.scalar(select(func.count(DeliveryFollowup.id)).where(*conditions)) or 0
    rows = db.scalars(select(DeliveryFollowup).where(*conditions).order_by(DeliveryFollowup.id.desc())
        .offset((page-1)*page_size).limit(page_size)).all()
    return FollowupPage(items=[_read(row,order,can_reply=can_reply) for row in rows],total=total,page=page,page_size=page_size)


def _reply_recipients(db, order, sender):
    recipients=[]
    for uid,department_id in db.execute(select(User.id,User.department_id).where(
        User.id.in_({order.buyer_id,sender}),User.status == 'ACTIVE')).all():
        try:
            candidate=SimpleNamespace(id=uid,department_id=department_id,status='ACTIVE')
            _authorize(db,candidate,'procurement.orders.read')
            order_service.get_order(db,candidate,order.id)
        except (AuthorizationError,ResourceNotFoundError):
            continue
        recipients.append(uid)
    return recipients


def reply_followup(db: Session, user, order_id: int, followup_id: int, data: FollowupReply) -> FollowupRead:
    try:
        _authorize(db,user,'supplier.portal.delivery.read','supplier.portal.delivery.update')
        order = portal_service._require_order(db,user,order_id,for_update=True)
        _lock_order_items(db, order)
        row = db.scalar(select(DeliveryFollowup).where(DeliveryFollowup.id == followup_id,
            DeliveryFollowup.order_id == order.id,DeliveryFollowup.supplier_id == order.supplier_id).with_for_update())
        if row is None:
            raise ResourceNotFoundError('催办记录不存在')
        payload_hash = hashlib.sha256(json.dumps(data.model_dump(mode='json'),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if row.status == 'REPLIED':
            if row.replied_by == user.id and row.reply_request_key == data.request_key and row.reply_payload_hash == payload_hash:
                return _read(row,order)
            raise DuplicateResourceError('该催办已回复，不能再次提交或改写')
        if not _active(order):
            raise BusinessValidationError('当前订单已结束或没有待收数量，不能回复催办')
        if data.expected_date and data.expected_date < business_today():
            raise BusinessValidationError('预计交期不能早于今天')
        if data.expected_date:
            portal_service.update_expected_delivery(db,user,order.id,
                SupplierDeliveryDateUpdate(expected_date=data.expected_date,note=data.message),commit=False)
        row.status='REPLIED'; row.replied_by=user.id; row.replied_at=utc_now()
        row.reply_message=data.message; row.reply_expected_date=data.expected_date
        row.reply_request_key=data.request_key; row.reply_payload_hash=payload_hash
        order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type='SUPPLIER_FOLLOWUP_REPLY',
            from_status=order.status, to_status=order.status, event_time=utc_now(), created_at=utc_now(),
            event_note=f'供应商回复交期催办 #{row.id}'))
        recipients=_reply_recipients(db,order,row.sent_by)
        notify_users(db,recipient_ids=recipients,notification_type='DELIVERY_FOLLOWUP_REPLY',title='交期催办已回复',
            content='供应商已回复交期催办，请进入订单详情查看。',related_type='DELIVERY_FOLLOWUP',related_id=row.id)
        add_audit_log(db,actor_id=user.id,action_type='REPLY_FOLLOWUP',resource_type='PURCHASE_ORDER',
            resource_id=order.id,request_summary='供应商回复交期催办',result_status='SUCCESS')
        db.commit()
        return _read(row,order)
    except Exception:
        db.rollback()
        raise


def resolve_followup(db: Session, user, followup_id: int, *, supplier=False) -> FollowupRead:
    """通知只携带催办 ID；读取正文或导航前重新核验当前订单范围。"""
    _authorize(db,user,'supplier.portal.delivery.read' if supplier else 'procurement.orders.read')
    row = db.get(DeliveryFollowup,followup_id)
    if row is None:
        raise ResourceNotFoundError('催办记录不存在')
    order = portal_service._require_order(db,user,row.order_id) if supplier else order_service.get_order(db,user,row.order_id)
    if row.supplier_id != order.supplier_id:
        raise ResourceNotFoundError('催办记录不存在')
    can_reply = supplier and 'supplier.portal.delivery.update' in get_user_permission_codes(db,user.id)
    return _read(row,order,can_reply=can_reply)
