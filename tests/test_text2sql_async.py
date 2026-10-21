"""Text2SQL 的同步 ORM 规划分支不应占用异步事件循环。"""
import asyncio
import time

from app.modules.ai import text2sql


def test_fixed_plan_database_stage_runs_outside_event_loop(monkeypatch):
    plan = object()
    def slow_fixed_lookup(*_args):
        time.sleep(0.15)
        return plan
    monkeypatch.setattr(text2sql, "_inventory_movement_trace_plan", slow_fixed_lookup)

    async def check_heartbeat():
        progressed = False
        async def heartbeat():
            nonlocal progressed
            await asyncio.sleep(0.02)
            progressed = True
        result, _ = await asyncio.gather(
            text2sql._understand_question("查询库存", object(), object(), object()), heartbeat())
        return result is plan and progressed

    assert asyncio.run(check_heartbeat())
