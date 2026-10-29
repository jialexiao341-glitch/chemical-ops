"""付款占用必须使用当前锁定读，不能依赖旧事务快照。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.modules.finance import service


@pytest.mark.parametrize('paid_only', [False, True])
def test_payment_total_uses_locking_current_read(paid_only):
    statements = []
    db = SimpleNamespace(
        scalar=lambda statement: Decimal('0'),
        scalars=lambda statement: statements.append(statement) or SimpleNamespace(
            all=lambda: [Decimal('25'), Decimal('35')]),
    )
    assert service._sum_payments(db, 1, paid_only=paid_only) == Decimal('60')
    assert 'FOR UPDATE' in str(statements[0].compile(dialect=mysql.dialect()))
