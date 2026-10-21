"""来源明确才转换；未知历史不得自动标记为 UTC。"""
import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


def time_module():
    path = Path(__file__).resolve().parents[1] / "backend/app/core/time.py"
    assert path.exists(), "缺少统一时间协议原语"
    spec = importlib.util.spec_from_file_location("time_protocol", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_utc_now_naive():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    value = time_module().utc_now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert value.tzinfo is None
    assert before <= value <= after


def test_shanghai_date_window_crosses_utc_day():
    start, end = time_module().business_date_window(date(2026, 10, 21), date(2026, 10, 21))
    assert start == datetime(2026, 10, 20, 16)
    assert end == datetime(2026, 10, 21, 16)
    assert end - start == timedelta(days=1)


def test_business_today_uses_shanghai_even_when_host_is_utc():
    assert time_module().business_today(datetime(2026, 10, 20, 17, tzinfo=timezone.utc)) == date(2026, 10, 21)


def test_unknown_legacy_naive_timestamp_keeps_unknown_timezone():
    assert time_module().serialize_timestamp(datetime(2020, 1, 1, 8)) == "2020-01-01T08:00:00"


@pytest.mark.parametrize("value,source,expected", [
    (datetime(2026, 10, 21, 8), "Asia/Shanghai", "2026-10-21T00:00:00Z"),
    (datetime(2026, 10, 21, 8), "UTC", "2026-10-21T08:00:00Z"),
    (datetime(2026, 10, 21, 8, tzinfo=timezone(timedelta(hours=8))), None, "2026-10-21T00:00:00Z"),
])
def test_explicit_origin_serializes_utc(value, source, expected):
    assert time_module().serialize_timestamp(value, source_timezone=source) == expected


def test_ambiguous_date_window_and_conflicting_origin_are_rejected():
    module = time_module()
    with pytest.raises(ValueError):
        module.business_date_window(date(2026, 10, 22), date(2026, 10, 21))
    with pytest.raises(ValueError):
        module.business_today(datetime(2026, 10, 21))
    with pytest.raises(ValueError):
        module.serialize_timestamp(datetime(2026, 10, 21, tzinfo=timezone.utc), source_timezone="Asia/Shanghai")
