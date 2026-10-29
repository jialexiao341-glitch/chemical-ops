"""申请状态变更必须先锁定主单并读取当前明细。"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.modules.inventory import crud, service
from app.modules.inventory.model import InventoryIssueRequest, InventoryTransferRequest, InventoryStocktakeRequest
from app.modules.replenishments import service as replenishments


class StopLookup(Exception):
    pass


@pytest.mark.parametrize(('function', 'lookup', 'has_data'), [
    ('update_issue_request', '_get_issue_for_user', True),
    ('submit_issue_request', '_get_issue_for_user', False),
    ('cancel_issue_request', '_get_issue_for_user', False),
    ('update_transfer_request', '_get_transfer_for_user', True),
    ('submit_transfer_request', '_get_transfer_for_user', False),
    ('cancel_transfer_request', '_get_transfer_for_user', False),
    ('update_stocktake_request', '_get_stocktake_for_user', True),
    ('submit_stocktake_request', '_get_stocktake_for_user', False),
    ('cancel_stocktake_request', '_get_stocktake_for_user', False),
])
def test_inventory_mutations_lock_before_check(monkeypatch, function, lookup, has_data):
    captured = []
    def lookup_row(*args, **kwargs):
        captured.append(kwargs.get('for_update', False))
        raise StopLookup
    monkeypatch.setattr(service, lookup, lookup_row)
    args = [object(), object(), 1]
    if has_data:
        args.append(object())
    with pytest.raises(StopLookup):
        getattr(service, function)(*args)
    assert captured == [True]


@pytest.mark.parametrize('function', ['submit_replenishment', 'cancel_replenishment'])
def test_replenishment_mutations_lock_before_check(monkeypatch, function):
    captured = []
    def lookup_row(*args, **kwargs):
        captured.append(kwargs.get('for_update', False))
        raise StopLookup
    monkeypatch.setattr(replenishments, 'get_replenishment', lookup_row)
    with pytest.raises(StopLookup):
        getattr(replenishments, function)(object(), object(), 1)
    assert captured == [True]


@pytest.mark.parametrize(('getter', 'model'), [
    ('get_issue_request', InventoryIssueRequest),
    ('get_transfer_request', InventoryTransferRequest),
    ('get_stocktake_request', InventoryStocktakeRequest),
])
def test_locked_request_loads_items_with_current_read(getter, model):
    row = model(id=1)
    calls = []
    db = SimpleNamespace(
        scalar=lambda statement: calls.append(statement) or row,
        scalars=lambda statement: calls.append(statement) or SimpleNamespace(all=lambda: []),
    )
    assert getattr(crud, getter)(db, 1, for_update=True) is row
    assert len(calls) == 2
    assert all('FOR UPDATE' in str(statement.compile(dialect=mysql.dialect())) for statement in calls)
    assert all(statement.get_execution_options().get('populate_existing') for statement in calls)
