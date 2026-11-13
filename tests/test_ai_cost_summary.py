"""成本看板接口：仅管理员可读，聚合不返回任务原文或用户身份。"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import AuthorizationError
from app.modules.ai_agent.controller import agent_cost_summary
from app.modules.ai_agent.model import AIAgentTask
from app.modules.system_management.model import User


def test_cost_summary_requires_admin(db_session):
    buyer = db_session.scalar(select(User).where(User.username == 'BuyerUser'))

    with pytest.raises(AuthorizationError, match="仅管理员"):
        agent_cost_summary(days=30, db=db_session, user=buyer)


def test_cost_summary_aggregates_usage_without_user_identity(db_session):
    admin = db_session.scalar(select(User).where(User.username == 'SystemAdmin'))
    now = datetime.utcnow()
    task = AIAgentTask(
        id=uuid4().hex, user_id=admin.id, status='SUCCEEDED', revision=1,
        payload={
            'messages': ['查询测试乙醇库存'],
            'trace': [],
            'memory_state': {'goal': {'intent': 'inventory_query'}},
            'run_meta': {
                'model': {'name': 'deepseek-flash'},
                'prompt_versions': {'planner': 'planner@1-cost-test'},
                'usage_totals': {
                    'calls': 2, 'input_tokens': 1000, 'output_tokens': 500,
                    'total_tokens': 1500, 'unmetered_calls': 0,
                    'split_unavailable_calls': 0,
                },
            },
            'token_budget': {'used_tokens': 1500},
        },
        reply='done', created_at=now, updated_at=now + timedelta(seconds=10))
    db_session.add(task)
    db_session.flush()

    result = agent_cost_summary(days=30, db=db_session, user=admin)

    assert result['summary']['tasks'] >= 1
    assert result['coverage']['run_meta_usage'] >= 1
    assert 'by_scene' in result and 'by_model' in result and 'by_prompt_version' in result
    group = next(row for row in result['by_prompt_version']
                 if row['prompt_version'] == 'planner@1-cost-test')
    assert group['total_tokens'] >= 1500
    assert '查询测试乙醇库存' not in str(result)