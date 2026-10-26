"""显式提供隔离 MySQL URL 后验证 RR 并发发送；仅创建并清理本用例随机表。"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Barrier, local
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, String, Table, UniqueConstraint, create_engine, select
from sqlalchemy.orm import Session, registry

from app.modules.purchase_orders import followup_service as service
from app.modules.purchase_orders.followup_schema import FollowupSend


@pytest.mark.integration
@pytest.mark.concurrency
def test_mysql_repeatable_read_concurrent_send_replays_one_record(monkeypatch):
    url=os.environ.get('FOLLOWUP_TEST_MYSQL_URL')
    if not url:
        pytest.skip('需要显式 FOLLOWUP_TEST_MYSQL_URL；不使用开发业务库做并发造数')
    engine=create_engine(url,isolation_level='REPEATABLE READ',pool_size=4)
    assert engine.dialect.name=='mysql', '必须使用隔离 MySQL 数据库'
    mapper=registry()
    prefix='followup_test_'+uuid4().hex[:12]+'_'
    def clone(model,label):
        columns=[Column(c.name,c.type.copy(),primary_key=c.primary_key,nullable=c.nullable,
                        default=c.default,server_default=c.server_default) for c in model.__table__.columns]
        table=Table(prefix+label,mapper.metadata,*columns)
        cls=type('Isolated'+label,(),{})
        mapper.map_imperatively(cls,table)
        return cls
    Proposal=clone(service.AIAgentActionProposal,'proposals')
    Followup=clone(service.DeliveryFollowup,'records')
    mapper.metadata.tables[prefix+'records'].append_constraint(UniqueConstraint('proposal_id'))
    users=Table(prefix+'users',mapper.metadata,Column('id',Integer,primary_key=True),
                Column('status',String(20)),Column('department_id',Integer))
    User=type('IsolatedUser',(),{}); mapper.map_imperatively(User,users)
    accounts=Table(prefix+'accounts',mapper.metadata,Column('id',Integer,primary_key=True),
        Column('user_id',Integer),Column('supplier_id',Integer),Column('status',String(20)))
    Account=type('IsolatedAccount',(),{}); mapper.map_imperatively(Account,accounts)
    locks=Table(prefix+'orders',mapper.metadata,Column('id',Integer,primary_key=True))
    order=NS(id=41,po_no='TEST',supplier_id=7,buyer_id=1,status='PARTIAL',events=[],items=[NS(order_quantity=Decimal(20),received_quantity=Decimal(5))])
    barrier=Barrier(2); thread=local(); notices=[]
    def roles(db,uid):
        db.scalar(select(User.id).where(User.id==uid))  # 在等待订单锁前建立一致性快照。
        if uid==1 and not getattr(thread,'started',False):
            thread.started=True
            barrier.wait(timeout=10)
        return ['BUYER'] if uid==1 else ['SUPPLIER_PORTAL']
    def get_order(db,user,oid,**kw):
        db.scalar(select(locks.c.id).where(locks.c.id==oid).with_for_update())
        return order
    monkeypatch.setattr(service,'AIAgentActionProposal',Proposal)
    monkeypatch.setattr(service,'DeliveryFollowup',Followup)
    monkeypatch.setattr(service,'User',User)
    monkeypatch.setattr(service,'SupplierPortalAccount',Account)
    monkeypatch.setattr(service,'get_user_role_codes',roles)
    monkeypatch.setattr(service,'get_user_permission_codes',lambda db,uid:
        {'procurement.orders.read','procurement.orders.write','ai.workspace.read'} if uid==1 else {'supplier.portal.delivery.read'})
    monkeypatch.setattr(service.order_service,'get_order',get_order)
    monkeypatch.setattr(service,'_lock_order_items',lambda *a:None)
    monkeypatch.setattr(service,'build_followup',lambda *a,**kw:{'message':'催办','snapshot':{'order_id':41}})
    monkeypatch.setattr(service,'notify_users',lambda *a,**kw:notices.append(kw))
    monkeypatch.setattr(service,'add_audit_log',lambda *a,**kw:None)
    try:
        mapper.metadata.create_all(engine)
        with Session(engine) as db:
            db.execute(users.insert(),[{'id':1,'status':'ACTIVE'},{'id':2,'status':'ACTIVE'}])
            db.execute(accounts.insert(),{'id':1,'user_id':2,'supplier_id':7,'status':'ACTIVE'})
            db.execute(locks.insert(),{'id':41})
            db.add(Proposal(confirmation_id='a'*32,user_id=1,action_type='deliveries.followup_draft',
                resource_id='41',preview_version=1,payload={'order_id':41},payload_hash='h',
                expected_resource_snapshot={'order_id':41},diff=[],evidence=[],warnings=[],blockers=[],
                permission_code='procurement.orders.write',risk_level='LOW',idempotency_key='test',
                expires_at=datetime.now()+timedelta(days=1),status='EXECUTED',result={'message':'催办'}))
            db.commit()
        def send():
            with Session(engine) as db:
                return service.send_followup(db,NS(id=1,status='ACTIVE'),41,
                    FollowupSend(confirmation_id='a'*32,preview_version=1,confirm=True)).id
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:send(),range(2)))
        assert results[0]==results[1] and len(notices)==1
    finally:
        mapper.metadata.drop_all(engine)  # metadata 仅含本测试 UUID 命名的表。
        mapper.dispose(); engine.dispose()
