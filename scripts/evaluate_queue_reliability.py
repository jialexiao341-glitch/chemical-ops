"""1000 唯一任务的隔离 MySQL/RabbitMQ 故障评测；业务执行使用明确测试替身。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
sys.path.insert(0, str(ROOT))

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, text, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from app.core.config import Settings
from app.models.base import Base
from app.modules.ai.model import AIAgentTask
from app.modules.system import model as system_model  # Resolve user foreign keys before DDL.
from app.modules.jobs.model import SchedulerJobRun
from app.modules.task_queue import broker, dispatcher, service, worker
from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock


GROUPS = {'normal': 200, 'duplicate_delivery': 200, 'ack_lost': 150,
          'publisher_crash': 150, 'worker_crash': 100, 'broker_outage': 100, 'stage_retry': 100}


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*fraction)-1)] if values else None


def metrics(rows):
    groups = {}
    for group in GROUPS:
        selected = [r for r in rows if r['group'] == group]
        recovery = [r['recovery_seconds'] for r in selected if r.get('recovery_seconds') is not None]
        groups[group] = dict(unique_tasks=len(selected), correct=sum(r['correct'] for r in selected),
            duplicate_side_effects=sum(r['duplicate_side_effects'] for r in selected),
            missing_side_effects=sum(r['missing_side_effects'] for r in selected),
            recovery_samples=len(recovery), recovery_p50_seconds=percentile(recovery,.5), recovery_p95_seconds=percentile(recovery,.95))
    return dict(unique_tasks=len(rows), correct=sum(r['correct'] for r in rows),
        success_rate=sum(r['correct'] for r in rows)/len(rows) if rows else None,
        duplicate_side_effects=sum(r['duplicate_side_effects'] for r in rows),
        unrecovered=sum(not r['correct'] for r in rows), groups=groups)


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    report['metrics'] = metrics(report['tasks'])
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# 异步任务固定规模可靠性评测', '', f"日期：{report['started_at']}；运行：{report['run_id']}；状态：{report['status']}。",
        '', '范围：独立临时 MySQL 库、独立 RabbitMQ 容器、真实 outbox/投递/claim/消费者 handle/恢复代码。',
        '业务主体为两阶段 SQL 写入测试替身，分别使用 agent.run/documents.ingest 路由；不是完整资料解析、向量索引或真实 Agent 回答评测。',
        'Worker 崩溃组使用真实独立进程：claim、提交第一阶段及 checkpoint 后突然退出；恢复器等待真实租约过期再恢复。',
        'Broker 停机组停止本次创建的独立容器；丢 ACK 组在结果提交后关闭未确认消息的 channel，并逐任务断言真实 redelivered 重投。',
        '任务租约与投递租约均为 15 秒；阶段重试使用产品真实 30 秒退避，不提前修改到期时间。',
        '恢复时间从 Broker 重启命令完成或故障进程退出或阶段失败提交开始，到该任务正确结果提交；包含健康等待、租约/退避及排队时间。',
        '统计分母为唯一逻辑任务；每种预期阶段只应写入一次。副作用表没有唯一键，避免数据库约束掩盖重复执行。', '',
        '| 条件 | 唯一任务 | 正确处理 | 重复副作用 | 恢复样本 | P50 秒 | P95 秒 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for group, m in report['metrics']['groups'].items():
        def fmt(value): return f'{value:.3f}' if value is not None else '—'
        lines.append(f"| {group} | {m['unique_tasks']} | {m['correct']} | {m['duplicate_side_effects']} | {m['recovery_samples']} | {fmt(m['recovery_p50_seconds'])} | {fmt(m['recovery_p95_seconds'])} |")
    m = report['metrics']
    lines += ['', f"已观测 {m['unique_tasks']}/{report['planned_tasks']} 个任务；正确处理 {m['correct']}，重复副作用 {m['duplicate_side_effects']} 次，未正确恢复 {m['unrecovered']} 个。",
        '各条件独立报告恢复分位数，不混合成一个受场景比例影响的 P95。不推导生产可用率、吞吐能力或真实业务效率。',
        '', '## 复现与清理', '', f"代码：{report['code_revision']}；脚本 SHA-256：{report['script_sha256']}。",
        f"清理：{report.get('cleanup', '尚未执行')}。完整逐任务状态、阶段次数、尝试次数和恢复时间见同名 JSON。"]
    if report.get('error_type'): lines.append(f"运行错误类别：{report['error_type']}；未将未执行样本计为通过。")
    path.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def connect_database(name):
    if not re.fullmatch(r'chemicalops_reliability_[0-9a-f]{12}',name): raise ValueError('Unsafe acceptance database')
    values = dotenv_values(ROOT/'.env')
    url = URL.create('mysql+pymysql',username='root',password=values['MYSQL_ROOT_PASSWORD'],
        host=values.get('MYSQL_HOST','127.0.0.1'),port=int(values.get('MYSQL_PORT','3306')))
    return create_engine(url,connect_args={'connect_timeout':5}),create_engine(url.set(database=name),
        pool_size=8,max_overflow=8,connect_args={'connect_timeout':5})


def docker(*args, env=None):
    result = subprocess.run(['docker',*args],env=env,capture_output=True,text=True,timeout=60)
    if result.returncode: raise RuntimeError('Acceptance container operation failed')
    return result.stdout.strip()


def crash_child(path):
    request = json.loads(path.read_text(encoding='utf-8'))
    admin, engine = connect_database(request['database'])
    factory = sessionmaker(engine,expire_on_commit=False)
    if request['kind'] == 'worker':
        for execution_id in request['ids']:
            with factory() as db:
                execution = service.claim_execution(db,execution_id,0,'crash-child',15)
                db.execute(text("INSERT INTO eval_effects(execution_id,stage) VALUES (:id,'parsed')"),{'id':execution.id})
                execution.checkpoint={'parsed':True,'process_pid':os.getpid(),'host':socket.gethostname()}
                db.commit()
        os._exit(23)
    settings = Settings(_env_file=None,rabbitmq_host='127.0.0.1',rabbitmq_port=int(os.environ['EVAL_RABBIT_PORT']),
        rabbitmq_username='evaluation',rabbitmq_password=os.environ['EVAL_RABBIT_PASSWORD'],rabbitmq_vhost='/')
    async def publish_before_crash():
        async with broker.connection(settings) as connection:
            channel = await connection.channel(publisher_confirms=True,on_return_raises=True)
            exchange = await broker.topology(channel)
            for _ in request['ids']:
                with factory() as db:
                    outbox = service.claim_delivery(db,'crash-publisher',15)
                    assert outbox.execution_id in request['ids']
                    execution_id = outbox.execution_id
                    execution = db.get(TaskExecution,execution_id)
                    await broker.publish(exchange,message_id=outbox.id,route=outbox.routing_key,
                        body=broker.TaskMessage(execution_id=execution_id,delivery_generation=0,task_type=execution.task_type))
            os._exit(24)
    asyncio.run(publish_before_crash())


class UnackedMessage:
    """结果已提交后故意不 ACK；由关闭 AMQP channel 触发 Broker 重投。"""
    def __init__(self,message): self.body=message.body
    async def ack(self): pass


async def run(args, report):
    database = 'chemicalops_reliability_'+report['run_id']
    container = 'chemicalops-reliability-'+report['run_id']
    admin, engine = connect_database(database)
    factory = sessionmaker(engine,expire_on_commit=False)
    created_database = created_container = False
    original_execute = worker.execute
    port = args.port
    password = uuid4().hex
    env = os.environ.copy()
    env.update(RABBITMQ_DEFAULT_USER='evaluation',RABBITMQ_DEFAULT_PASS=password,
        EVAL_RABBIT_PORT=str(port),EVAL_RABBIT_PASSWORD=password)
    settings = Settings(_env_file=None,rabbitmq_username='evaluation',rabbitmq_password=password,
        rabbitmq_port=port,rabbitmq_vhost='/',task_lease_seconds=15,task_heartbeat_seconds=1)
    child_path = args.output.with_suffix('.child.json')
    completion, fault_start, expectations = {}, {}, {}
    deliveries = {}
    try:
        with admin.begin() as db: db.execute(text(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4'))
        created_database = True
        with admin.connect() as db: report['mysql_version']=db.scalar(text('SELECT VERSION()'))
        with engine.begin() as db:
            migration = (ROOT/'database/migrations/041_async_task_dispatch.sql').read_text(encoding='utf-8')
            for statement in migration.split(';'):
                if statement.strip(): db.execute(text(statement))
        Base.metadata.create_all(engine,tables=[model.__table__ for model in
            (system_model.Department,system_model.User,AIAgentTask,SchedulerJobRun)])
        with engine.begin() as db:
            db.execute(text('CREATE TABLE eval_effects (id BIGINT AUTO_INCREMENT PRIMARY KEY, execution_id VARCHAR(32), stage VARCHAR(16))'))
        docker('run','--detach','--name',container,'--label','chemicalops.reliability='+report['run_id'],
            '-p',f'127.0.0.1:{port}:5672','-p',f'127.0.0.1:{port+10000}:15672',
            '--env','RABBITMQ_DEFAULT_USER','--env','RABBITMQ_DEFAULT_PASS','rabbitmq:4.3.6-management',env=env)
        created_container = True
        async def wait_ready():
            deadline = time.monotonic()+60
            while time.monotonic()<deadline:
                try:
                    async with httpx.AsyncClient(trust_env=False,timeout=2,auth=('evaluation',password)) as client:
                        response=await client.get(f'http://127.0.0.1:{port+10000}/api/overview')
                        if response.status_code==200:
                            report['rabbitmq_version']=response.json()['rabbitmq_version']
                            return
                except httpx.HTTPError: pass
                await asyncio.sleep(1)
            raise TimeoutError('Acceptance broker startup')
        await wait_ready()

        async def execute_substitute(factory, config, execution):
            with factory() as db:
                row=service.locked_execution(db,execution.id,execution.fencing_token)
                group=expectations[row.id]['group']
                if group=='stage_retry' and not row.checkpoint.get('parsed'):
                    db.execute(text("INSERT INTO eval_effects(execution_id,stage) VALUES (:id,'parsed')"),{'id':row.id})
                    row.checkpoint={'parsed':True}
                    service.finish(db,row.id,row.fencing_token,status='FAILED',retryable=True,error_code='EVAL_TEMPORARY_STAGE')
                    db.commit()
                    fault_start[row.id]=time.monotonic()
                    return
                stage='indexed' if group in {'worker_crash','stage_retry'} else 'result'
                db.execute(text('INSERT INTO eval_effects(execution_id,stage) VALUES (:id,:stage)'),{'id':row.id,'stage':stage})
                service.finish(db,row.id,row.fencing_token,status='SUCCEEDED')
                db.commit()
                completion[row.id]=time.monotonic()
        worker.execute=execute_substitute

        async def drain(source, channel, queue, *, lose_ack=False):
            while True:
                messages=[]
                for _ in range(4):
                    message=await source.get(timeout=2,fail=False)
                    if message is not None:
                        envelope=broker.TaskMessage.model_validate_json(message.body)
                        deliveries.setdefault(envelope.execution_id,[]).append(dict(generation=envelope.delivery_generation,redelivered=message.redelivered))
                        messages.append(message)
                if not messages: return
                await asyncio.gather(*(worker.handle(UnackedMessage(m) if lose_ack else m,factory,settings,queue,uuid4().hex,channel) for m in messages))

        async def dispatch_all(exchange):
            while await dispatcher.dispatch_one(factory,exchange,'evaluation'): pass

        async def process_group(ids, group):
            async with broker.connection(settings) as connection:
                channel=await connection.channel(publisher_confirms=True,on_return_raises=True)
                exchange=await broker.topology(channel)
                await dispatch_all(exchange)
                if group=='duplicate_delivery':
                    for execution_id in ids:
                        with factory() as db: execution=db.get(TaskExecution,execution_id)
                        for _ in range(2):
                            await broker.publish(exchange,message_id=uuid4().hex,route=service.TASK_ROUTES[execution.task_type],
                                body=broker.TaskMessage(execution_id=execution_id,delivery_generation=execution.delivery_generation,task_type=execution.task_type))
                for queue in ('agent','documents'):
                    source=await channel.get_queue('chemicalops.'+queue)
                    await drain(source,channel,queue,lose_ack=group=='ack_lost')
                if group=='ack_lost':
                    await channel.close()
                    channel=await connection.channel(publisher_confirms=True,on_return_raises=True)
                    for queue in ('agent','documents'):
                        await drain(await channel.get_queue('chemicalops.'+queue),channel,queue)

        for group,count in GROUPS.items():
            ids=[]
            for index in range(count):
                with factory() as db:
                    execution=service.enqueue(db,task_type='agent.run' if index%2==0 else 'documents.ingest',
                        business_id=uuid4().hex,actor_id=1,generation=0,payload={})
                    db.commit()
                    ids.append(execution.id)
                    expectations[execution.id]={'group':group,'expected_stages':['parsed','indexed'] if group in {'worker_crash','stage_retry'} else ['result']}
            if group in {'worker_crash','publisher_crash'}:
                child_path.write_text(json.dumps({'database':database,'ids':ids,'kind':'worker' if group=='worker_crash' else 'publisher'}),encoding='utf-8')
                child=subprocess.run([sys.executable,str(Path(__file__)),'--crash-child',str(child_path)],env=env,
                    capture_output=True,text=True,timeout=60,cwd=ROOT)
                if child.returncode != (23 if group=='worker_crash' else 24): raise RuntimeError('Fault child failed before intended exit')
                began=time.monotonic()
                fault_start.update({execution_id:began for execution_id in ids})
                # 不改数据库时间；等实际租约过期后调用真实恢复器。
                while True:
                    with factory() as db:
                        model=TaskExecution if group=='worker_crash' else TaskOutbox
                        lease=db.scalar(select(model.lease_until).where(model.id.in_(ids) if group=='worker_crash' else model.execution_id.in_(ids)).order_by(model.lease_until.desc()).limit(1))
                    if lease is not None and lease<service.now(): break
                    await asyncio.sleep(.5)
                if group=='worker_crash':
                    recovered=worker.recover(factory,settings)
                    if recovered!=len(ids): raise AssertionError('Incomplete recovery')
                    for execution_id in ids:
                        with factory() as db:
                            try: service.finish(db,execution_id,1,status='SUCCEEDED')
                            except service.ExecutionLost: db.rollback()
                            else: raise AssertionError('Old token was allowed to commit')
            if group=='broker_outage':
                docker('stop',container)
                try:
                    await dispatcher.run(settings,factory,once=True)
                except RuntimeError: pass
                else: raise AssertionError('Stopped broker unexpectedly accepted publication')
                with factory() as db:
                    pending=list(db.scalars(select(TaskOutbox).where(TaskOutbox.execution_id.in_(ids))))
                    if len(pending)!=count or any(r.status!='PENDING' for r in pending): raise AssertionError('Outbox intent lost')
                docker('start',container)
                began=time.monotonic()
                fault_start.update({execution_id:began for execution_id in ids})
                await wait_ready()
            await process_group(ids,group)
            if group=='stage_retry':
                while True:
                    with factory() as db:
                        due=db.scalar(select(TaskExecution.next_attempt_at).where(TaskExecution.id.in_(ids)).order_by(TaskExecution.next_attempt_at.desc()).limit(1))
                    if due is not None and due<=service.now(): break
                    await asyncio.sleep(.5)
                await process_group(ids,group)
            with factory() as db:
                for execution_id in ids:
                    execution=db.get(TaskExecution,execution_id)
                    stages=[r[0] for r in db.execute(text('SELECT stage FROM eval_effects WHERE execution_id=:id'),{'id':execution_id})]
                    expected=expectations[execution_id]['expected_stages']
                    received=deliveries.get(execution_id,[])
                    expected_messages=3 if group=='duplicate_delivery' else 2 if group in {'ack_lost','publisher_crash','worker_crash','stage_retry'} else 1
                    if len(received)!=expected_messages: raise AssertionError('Missing fault redelivery')
                    if group=='ack_lost' and not any(m['redelivered'] for m in received): raise AssertionError('ACK loss did not trigger real broker redelivery')
                    outbox_status=list(db.scalars(select(TaskOutbox.status).where(TaskOutbox.execution_id==execution_id)))
                    if any(status!='SENT' for status in outbox_status): raise AssertionError('Unsettled outbox')
                    duplicate=sum(max(0,stages.count(stage)-1) for stage in set(stages))
                    missing=sum(stage not in stages for stage in expected)
                    correct=execution.status=='SUCCEEDED' and sorted(stages)==sorted(expected)
                    report['tasks'].append(dict(execution_id=execution_id,task_type=execution.task_type,group=group,status=execution.status,
                        attempt_count=execution.attempt_count,expected_stages=expected,actual_stages=stages,
                        received_messages=received,outbox_status=outbox_status,
                        duplicate_side_effects=duplicate,missing_side_effects=missing,correct=correct,
                        recovery_seconds=round(completion[execution_id]-fault_start[execution_id],6) if execution_id in fault_start and execution_id in completion else None))
            save_report(args.output,report)
            print(f"{group}: {sum(r['correct'] for r in report['tasks'] if r['group']==group)}/{count} ({len(report['tasks'])}/1000)",flush=True)
        report['status']='COMPLETED'
    except Exception as exc:
        report['status']='ERROR'
        report['error_type']=type(exc).__name__
        raise
    finally:
        worker.execute=original_execute
        child_path.unlink(missing_ok=True)
        engine.dispose()
        cleanup=[]
        if created_container:
            docker('rm','--force',container)
            cleanup.append('本次独立容器已删除')
        if created_database:
            with admin.begin() as db: db.execute(text(f'DROP DATABASE `{database}`'))
            cleanup.append('本次临时数据库已删除')
        admin.dispose()
        report['cleanup']='；'.join(cleanup)
        save_report(args.output,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/evaluation/queue-reliability-1000-20261009.json')
    parser.add_argument('--port',type=int,default=5674)
    parser.add_argument('--crash-child',type=Path)
    args=parser.parse_args()
    if args.crash_child:
        crash_child(args.crash_child)
        return 1
    if not 1024<=args.port<=55535: parser.error('port 必须为 1024..55535')
    report=dict(started_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),run_id=uuid4().hex[:12],
        code_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),planned_tasks=sum(GROUPS.values()),
        runtime_source_sha256={name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name,module in {'broker':broker,'dispatcher':dispatcher,'service':service,'worker':worker}.items()},
        platform=platform.platform(),python_version=platform.python_version(),
        status='RUNNING',tasks=[],settings={'task_lease_seconds':15,'delivery_lease_seconds':15,'retry_backoff_seconds':30,'consumer_batch':4})
    save_report(args.output,report)
    asyncio.run(run(args,report))
    return int(report['metrics']['unrecovered']>0)


if __name__=='__main__':
    raise SystemExit(main())
