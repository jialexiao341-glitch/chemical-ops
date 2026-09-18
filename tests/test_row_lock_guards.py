from unittest.mock import Mock

from app.modules.deliveries import crud as delivery_crud
from app.modules.inventory import crud as inventory_crud


def _captured_statement(callable_, *args, **kwargs):
    db = Mock()
    db.scalar.side_effect = lambda statement: statement
    return callable_(db, *args, **kwargs)


def test_delivery_query_can_lock_delivery_row():
    statement = _captured_statement(delivery_crud.get_by_id, 1, for_update=True)

    assert statement._for_update_arg is not None


def test_purchase_order_query_can_lock_order_row():
    statement = _captured_statement(delivery_crud.get_order, 1, for_update=True)

    assert statement._for_update_arg is not None


def test_inventory_balance_query_can_lock_balance_row():
    statement = _captured_statement(inventory_crud.get_balance, 1, 2, 3, 4, 5, for_update=True)

    assert statement._for_update_arg is not None
