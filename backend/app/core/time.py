"""新功能时间契约。调用方必须明确来源，不能据此重标未知历史 DATETIME。

现代业务日采用上海 UTC+08:00（1992 年起无夏令时）；更早历史不在自动转换范围。
不依赖宿主机时区，也不修改数据库连接协议或已有领域写入。
"""
from datetime import date, datetime, time, timedelta, timezone

UTC = timezone.utc
BUSINESS_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")


def utc_now() -> datetime:
    """返回明确来源为 UTC 的无时区存储值，适用于已采用本协议的新字段。"""
    return datetime.now(UTC).replace(tzinfo=None)


def business_today(now: datetime | None = None) -> date:
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("business_today requires an aware instant")
    if instant.year < 1992:
        raise ValueError("historical Shanghai daylight saving requires a verified timezone database")
    return instant.astimezone(BUSINESS_TIMEZONE).date()


def business_date_window(start: date, end: date) -> tuple[datetime, datetime]:
    """上海闭区间业务日期转换为 UTC naive 半开时间区间 [start, end+1)。"""
    if isinstance(start, datetime) or isinstance(end, datetime) or start > end:
        raise ValueError("expected an ordered pair of business dates")
    if start.year < 1992:
        raise ValueError("historical Shanghai daylight saving requires a verified timezone database")
    lower = datetime.combine(start, time.min, BUSINESS_TIMEZONE)
    upper = datetime.combine(end + timedelta(days=1), time.min, BUSINESS_TIMEZONE)
    return lower.astimezone(UTC).replace(tzinfo=None), upper.astimezone(UTC).replace(tzinfo=None)


def serialize_timestamp(value: datetime, *, source_timezone: str | None = None) -> str:
    """只将已知来源输出为带 Z 的 UTC；未知 naive 保持无时区信息。

    source_timezone 由服务端已验证的存储协议提供，不接受模型推断或用户指定。
    已带时区的值自带来源，不允许再次传入来源覆盖它。
    """
    aware = value.tzinfo is not None and value.utcoffset() is not None
    if aware and source_timezone is not None:
        raise ValueError("aware timestamp must not be assigned another source timezone")
    if not aware:
        if source_timezone is None:
            return value.isoformat()
        if source_timezone == "UTC":
            value = value.replace(tzinfo=UTC)
        elif source_timezone == "Asia/Shanghai" and value.year >= 1992:
            value = value.replace(tzinfo=BUSINESS_TIMEZONE)
        else:
            raise ValueError("unsupported or unverified source timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
