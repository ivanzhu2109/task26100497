"""验收场景：夏令时跳过与重复时刻（含非 1 小时偏移变化）。"""
from datetime import datetime, time, timezone

from winner_calendar import Campaign, StoreCalendar

UTC = timezone.utc


def _single_campaign_cal(tz: str, window_start: time, window_end: time) -> StoreCalendar:
    campaign = Campaign(
        campaign_id=1,
        zones=frozenset({"A"}),
        priority=5,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 1, 1, tzinfo=UTC),
        weekdays=frozenset(range(7)),
        window_start=window_start,
        window_end=window_end,
    )
    return StoreCalendar(tz, [campaign])


def _winning_segments(cal: StoreCalendar, start: datetime, end: datetime):
    segments = cal.generate("A", start, end)
    # 完整覆盖请求范围
    assert segments[0].start == start
    assert segments[-1].end == end
    for prev, nxt in zip(segments, segments[1:]):
        assert prev.end == nxt.start
        assert prev.winner != nxt.winner  # 相邻同结果必须已合并
    return [(s.start, s.end) for s in segments if s.winner == 1]


def test_new_york_spring_forward_gap():
    cal = _single_campaign_cal("America/New_York", time(2, 10), time(3, 10))
    winning = _winning_segments(
        cal, datetime(2025, 3, 9, tzinfo=UTC), datetime(2025, 3, 10, tzinfo=UTC)
    )
    assert winning == [
        (datetime(2025, 3, 9, 7, 0, tzinfo=UTC), datetime(2025, 3, 9, 7, 10, tzinfo=UTC))
    ]


def test_new_york_fall_back_repeated_hour():
    cal = _single_campaign_cal("America/New_York", time(1, 15), time(1, 45))
    winning = _winning_segments(
        cal, datetime(2025, 11, 2, tzinfo=UTC), datetime(2025, 11, 3, tzinfo=UTC)
    )
    assert winning == [
        (datetime(2025, 11, 2, 5, 15, tzinfo=UTC), datetime(2025, 11, 2, 5, 45, tzinfo=UTC)),
        (datetime(2025, 11, 2, 6, 15, tzinfo=UTC), datetime(2025, 11, 2, 6, 45, tzinfo=UTC)),
    ]


def test_lord_howe_thirty_minute_fallback():
    cal = _single_campaign_cal("Australia/Lord_Howe", time(1, 40), time(1, 50))
    winning = _winning_segments(
        cal, datetime(2025, 4, 5, tzinfo=UTC), datetime(2025, 4, 6, tzinfo=UTC)
    )
    assert winning == [
        (datetime(2025, 4, 5, 14, 40, tzinfo=UTC), datetime(2025, 4, 5, 14, 50, tzinfo=UTC)),
        (datetime(2025, 4, 5, 15, 10, tzinfo=UTC), datetime(2025, 4, 5, 15, 20, tzinfo=UTC)),
    ]


def test_empty_result_fills_request_range():
    cal = _single_campaign_cal("America/New_York", time(2, 10), time(3, 10))
    segments = cal.generate("A", datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 2, tzinfo=UTC))
    # 2025-06-01 是周日以外的普通日期窗口仍存在；改用不含窗口的分区验证空结果
    segments = cal.generate("B", datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 2, tzinfo=UTC))
    assert len(segments) == 1
    assert segments[0].winner is None
    assert segments[0].start == datetime(2025, 6, 1, tzinfo=UTC)
    assert segments[0].end == datetime(2025, 6, 2, tzinfo=UTC)
