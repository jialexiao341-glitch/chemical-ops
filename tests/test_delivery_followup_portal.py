"""门户催办的隔离事务回归；不连接开发业务库或调用模型。"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import DefaultClause, create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai.model import AIAgentActionProposal
from app.modules.purchase_orders import followup_service as service
from app.modules.purchase_orders.followup_model import DeliveryFollowup
from app.modules.purchase_orders.followup_schema import FollowupReply, FollowupSend
from app.modules.supplier_portal.schema import SupplierDeliveryDateUpdate

real_update_expected_delivery = service.portal_service.update_expected_delivery


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine('sqlite://')
    for name in ('created_at', 'updated_at'):
        monkeypatch.setattr(AIAgentActionProposal.__table__.c[name], 'server_default', DefaultClause(text('CURRENT_TIMESTAMP')))
    monkeypatch.setattr(AIAgentActionProposal.__table__.c.updated_at, 'onupdate', None)
    AIAgentActionProposal.__table__.create(engine)
    DeliveryFollowup.__table__.create(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE sys_users (id INTEGER PRIMARY KEY, status TEXT, department_id INTEGER)')
        conn.exec_driver_sql("INSERT INTO sys_users VALUES (1,'ACTIVE',1),(2,'ACTIVE',NULL),(3,'ACTIVE',NULL),(4,'ACTIVE',NULL)")
        conn.exec_driver_sql('CREATE TABLE supplier_portal_accounts (id INTEGER PRIMARY KEY, user_id INTEGER, supplier_id INTEGER, status TEXT)')
        conn.exec_driver_sql("INSERT INTO supplier_portal_accounts VALUES (1,2,7,'ACTIVE'),(2,3,8,'ACTIVE'),(3,4,7,'ACTIVE')")
    permissions = {1: {'procurement.orders.read','procurement.orders.write','ai.workspace.read'},
                   2: {'supplier.portal.delivery.read','supplier.portal.delivery.update'},
                   3: {'supplier.portal.delivery.read','supplier.portal.delivery.update'},
                   4: {'supplier.portal.delivery.read'}}
    roles = {1: ['BUYER'], 2: ['SUPPLIER_PORTAL'], 3: ['SUPPLIER_PORTAL'], 4: ['BUYER','SUPPLIER_PORTAL']}
    monkeypatch.setattr(service, 'get_user_permission_codes', lambda db, uid: permissions[uid])
    monkeypatch.setattr(service, 'get_user_role_codes', lambda db, uid: roles[uid])
    order = NS(id=41, po_no='PO-TEST', supplier_id=7, buyer_id=1, status='PARTIAL', events=[],
               items=[NS(order_quantity=Decimal(20),received_quantity=Decimal(5))], expected_arrival_date=date(2026,10,28))
    def get_order(db,user,oid,**kwargs):
        if oid != order.id: raise ResourceNotFoundError('订单不存在')
        return order
    monkeypatch.setattr(service.order_service, 'get_order', get_order)
    monkeypatch.setattr(service, '_lock_order_items', lambda *args: None)
    def portal_order(db,user,oid,**kwargs):
        if roles[user.id] != ['SUPPLIER_PORTAL'] or (user.id == 3) or order.supplier_id != 7:
            raise ResourceNotFoundError('订单不存在')
        return get_order(db,user,oid)
    monkeypatch.setattr(service.portal_service, '_require_order', portal_order)
    def build(db,user,oid,**kwargs):
        return {'message': '请反馈交期', 'snapshot': {'order_id':41,'supplier_id':order.supplier_id,
                'expected_date': str(order.expected_arrival_date)}, 'warnings': []}
    monkeypatch.setattr(service, 'build_followup', build)
    notifications, audits, eta = [], [], []
    monkeypatch.setattr(service, 'notify_users', lambda db, **kw: notifications.append(kw))
    monkeypatch.setattr(service, 'add_audit_log', lambda db, **kw: audits.append(kw))
    monkeypatch.setattr(service, 'business_today', lambda: date(2026,10,26))
    def update(db,user,oid,data,*,commit=True):
        assert commit is False
        eta.append(data.expected_date)
    monkeypatch.setattr(service.portal_service, 'update_expected_delivery', update)
    with Session(engine) as db:
        p=AIAgentActionProposal(confirmation_id='a'*32,user_id=1,action_type='deliveries.followup_draft',
            resource_type='PURCHASE_ORDER',resource_id='41',preview_version=1,payload={'order_id':41},
            payload_hash='hash',expected_resource_snapshot=build(db,None,41)['snapshot'],diff=[],evidence=[],
            warnings=[],blockers=[],permission_code='procurement.orders.write',risk_level='LOW',
            idempotency_key='draft1',expires_at=datetime.now()+timedelta(days=1),status='EXECUTED',
            result={'message':'请反馈交期','status':'DRAFT','sent':False})
        db.add(p); db.commit()
        yield NS(db=db, order=order, proposal=p, buyer=NS(id=1,status='ACTIVE'), supplier=NS(id=2,status='ACTIVE'),
                 other=NS(id=3,status='ACTIVE'),permissions=permissions,notifications=notifications,audits=audits,eta=eta)
    engine.dispose()


def send(s):
    return service.send_followup(s.db,s.buyer,41,FollowupSend(confirmation_id='a'*32,preview_version=1,confirm=True))


def test_send_is_explicit_and_idempotent_with_filtered_recipients(setup):
    s=setup
    row=send(s)
    assert row.status == 'SENT' and row.message == '请反馈交期'
    assert send(s).id == row.id
    assert s.db.scalar(select(func.count(DeliveryFollowup.id))) == 1
    assert s.notifications[0]['recipient_ids'] == [2]
    assert '请反馈交期' not in s.notifications[0]['content']
    assert len(s.notifications) == 1 and len(s.audits) == 1
    assert s.proposal.result['sent'] is False
    assert s.order.events[-1].event_type=='DELIVERY_FOLLOWUP_SENT'


@pytest.mark.parametrize('change',['facts','pending','version','owner','order','message'])
def test_send_rejects_unreviewed_or_foreign_draft(setup,change):
    s=setup
    if change=='facts': s.order.expected_arrival_date=date(2026,10,30)
    if change=='pending': s.proposal.status='PENDING'
    if change=='version': s.proposal.preview_version=2
    if change=='owner': s.proposal.user_id=3
    if change=='order': s.proposal.resource_id='99'
    if change=='message': s.proposal.result={**s.proposal.result,'message':'篡改正文'}
    s.db.commit()
    with pytest.raises((BusinessValidationError,ResourceNotFoundError,DuplicateResourceError)):
        send(s)
    assert s.db.scalar(select(func.count(DeliveryFollowup.id))) == 0


def test_no_recipient_and_revoked_idempotent_replay_are_rejected(setup):
    s=setup
    s.permissions[2].clear()
    with pytest.raises(BusinessValidationError): send(s)
    s.permissions[2].add('supplier.portal.delivery.read')
    row=send(s)
    s.permissions[1].clear()
    with pytest.raises(AuthorizationError): send(s)
    assert row.id


@pytest.mark.parametrize('with_eta',[False,True])
def test_reply_once_with_optional_eta_and_idempotency(setup,with_eta):
    s=setup; row=send(s)
    data=FollowupReply(request_key='reply-one',message=' 已确认安排 ',expected_date=date(2026,10,29) if with_eta else None)
    result=service.reply_followup(s.db,s.supplier,41,row.id,data)
    assert result.status=='REPLIED' and result.reply_message=='已确认安排'
    assert s.order.events[-1].event_type=='SUPPLIER_FOLLOWUP_REPLY'
    assert service.reply_followup(s.db,s.supplier,41,row.id,data).id == row.id
    assert s.eta == ([date(2026,10,29)] if with_eta else [])
    assert len(s.notifications)==2
    with pytest.raises(DuplicateResourceError):
        service.reply_followup(s.db,s.supplier,41,row.id,FollowupReply(request_key='another',message='重复回复'))
    with pytest.raises(DuplicateResourceError):
        service.reply_followup(s.db,s.supplier,41,row.id,FollowupReply(request_key='reply-one',message='改写'))


@pytest.mark.parametrize('change',['other_supplier','closed','no_pending','past_date','permission'])
def test_reply_enforces_current_business_and_supplier_boundary(setup,change):
    s=setup; row=send(s)
    user=s.other if change=='other_supplier' else s.supplier
    if change=='closed': s.order.status='COMPLETED'
    if change=='no_pending': s.order.items[0].received_quantity=Decimal(20)
    if change=='permission': s.permissions[2].clear()
    data=FollowupReply(request_key='r',message='回复',expected_date=date(2026,10,25) if change=='past_date' else None)
    with pytest.raises((AuthorizationError,ResourceNotFoundError,BusinessValidationError)):
        service.reply_followup(s.db,user,41,row.id,data)
    assert s.db.get(DeliveryFollowup,row.id).status=='SENT'


def test_supplier_history_is_paginated_and_hides_internal_proposal(setup):
    s=setup; send(s)
    page=service.list_followups(s.db,s.supplier,41,supplier=True,page=1,page_size=1)
    assert page.total==1 and len(page.items)==1
    assert 'proposal_id' not in page.items[0].model_dump()
    with pytest.raises(ResourceNotFoundError):
        service.list_followups(s.db,s.other,41,supplier=True)


def test_notification_failure_rolls_back_reply_and_eta_call_participates_in_transaction(setup,monkeypatch):
    s=setup; row=send(s)
    def update(db,user,oid,data,*,commit=True):
        assert commit is False
        db.execute(text("UPDATE sys_users SET status='CHANGED' WHERE id=1"))
    monkeypatch.setattr(service.portal_service,'update_expected_delivery',update)
    def fail(*a,**kw): raise RuntimeError('notification failure')
    monkeypatch.setattr(service,'notify_users',fail)
    with pytest.raises(RuntimeError):
        service.reply_followup(s.db,s.supplier,41,row.id,FollowupReply(request_key='r',message='反馈',expected_date=date(2026,10,29)))
    assert s.db.get(DeliveryFollowup,row.id).status=='SENT'
    assert s.db.scalar(text('SELECT status FROM sys_users WHERE id=1'))=='ACTIVE'


def test_existing_eta_service_can_participate_without_committing(setup,monkeypatch):
    s=setup
    s.order.events=[]
    monkeypatch.setattr(service.portal_service,'business_today',lambda:date(2026,10,26))
    monkeypatch.setattr(service.portal_service,'add_audit_log',lambda *a,**kw:None)
    s.db.execute(text('CREATE TABLE supplier_delivery_updates (id INTEGER PRIMARY KEY, po_id INTEGER, supplier_id INTEGER, previous_date DATE, expected_date DATE, note TEXT, submitted_by INTEGER, submitted_at DATETIME)'))
    s.db.commit()
    commits=[]
    original_commit=s.db.commit
    monkeypatch.setattr(s.db,'commit',lambda:commits.append(True))
    result=real_update_expected_delivery(s.db,s.supplier,41,
        SupplierDeliveryDateUpdate(expected_date=date(2026,10,29),note='回复催办'),commit=False)
    assert result.expected_date==date(2026,10,29) and not commits
    assert s.order.items[0].planned_arrival_date==date(2026,10,29)
    assert s.order.events[-1].event_type=='SUPPLIER_ETA_UPDATE'
    s.db.rollback()
    assert s.db.scalar(text('SELECT COUNT(*) FROM supplier_delivery_updates'))==0
    monkeypatch.setattr(s.db,'commit',original_commit)


@pytest.mark.parametrize('data',[
    {'confirmation_id':'a'*32,'preview_version':1,'confirm':False},
    {'confirmation_id':'a'*32,'preview_version':True,'confirm':True},
    {'confirmation_id':'a'*32,'preview_version':1,'confirm':1},
    {'confirmation_id':'a'*32,'preview_version':1,'confirm':True,'message':'伪造'},
])
def test_send_schema_requires_explicit_confirmation_without_fact_overrides(data):
    from pydantic import ValidationError
    with pytest.raises(ValidationError): FollowupSend.model_validate(data)


def test_resolve_and_replay_recheck_supplier_binding_and_permissions(setup):
    s=setup; row=send(s)
    assert service.resolve_followup(s.db,s.supplier,row.id,supplier=True).order_id==41
    with pytest.raises(ResourceNotFoundError): service.resolve_followup(s.db,s.other,row.id,supplier=True)
    data=FollowupReply(request_key='one',message='已安排')
    service.reply_followup(s.db,s.supplier,41,row.id,data)
    s.permissions[2].clear()
    with pytest.raises(AuthorizationError): service.reply_followup(s.db,s.supplier,41,row.id,data)
    with pytest.raises(AuthorizationError): service.resolve_followup(s.db,s.supplier,row.id,supplier=True)


def test_send_notification_failure_rolls_back_record(setup,monkeypatch):
    s=setup
    def fail(*a,**kw): raise RuntimeError('notify failed')
    monkeypatch.setattr(service,'notify_users',fail)
    with pytest.raises(RuntimeError): send(s)
    assert s.db.scalar(select(func.count(DeliveryFollowup.id)))==0


def test_send_replay_uses_current_read_after_authorization_snapshot(setup,monkeypatch):
    s=setup; first=send(s)
    original=s.db.scalar
    def snapshot(statement,*a,**kw):
        # 模拟 RR：授权已建立快照，只有锁定读可看到刚提交的催办。
        descriptions=getattr(statement,'column_descriptions',[])
        if descriptions and descriptions[0].get('expr') is DeliveryFollowup and statement._for_update_arg is None:
            return None
        return original(statement,*a,**kw)
    monkeypatch.setattr(s.db,'scalar',snapshot)
    assert send(s).id==first.id
    assert len(s.notifications)==1


def test_unique_conflict_recovers_only_after_rollback_and_reauthorization(setup,monkeypatch):
    s=setup; first=send(s)
    original=s.db.scalar
    hidden=[False]
    def race(statement,*a,**kw):
        descriptions=getattr(statement,'column_descriptions',[])
        if not hidden[0] and descriptions and descriptions[0].get('expr') is DeliveryFollowup:
            hidden[0]=True
            return None
        return original(statement,*a,**kw)
    monkeypatch.setattr(s.db,'scalar',race)
    assert send(s).id==first.id
    assert s.db.is_active and len(s.notifications)==1
