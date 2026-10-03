"""边界行为：落败活动不产生多余分段、未命中分区、参数校验。"""
from datetime import datetime, time, timezone

import pytest

from winner_calendar import Campaign, StoreCalendar

UTC = timezone.utc


def _campaign(cid, priority, ws, we, zones=("A",)):
    return Campaign(
        campaign_id=cid,
        zones=frozenset(zones),
        priority=priority,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 1, 1, tzinfo=UTC),
        weekdays=frozenset(range(7)),
        window_start=ws,
        window_end=we,
    )


def test_losing_campaign_boundaries_do_not_split():
    # 活动 1 全程获胜；活动 2 的窗口边界落在其内部，不得造成分段。
    cal = StoreCalendar("UTC", [
        _campaign(1, 9, time(20, 0), time(4, 0)),
        _campaign(2, 1, time(22, 0), time(23, 0)),
    ])
    segments = cal.generate("A", datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 3, tzinfo=UTC))
    assert [(s.start, s.end, s.winner) for s in segments] == [
        (datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 1, 4, 0, tzinfo=UTC), 1),
        (datetime(2025, 6, 1, 4, 0, tzinfo=UTC), datetime(2025, 6, 1, 20, 0, tzinfo=UTC), None),
        (datetime(2025, 6, 1, 20, 0, tzinfo=UTC), datetime(2025, 6, 2, 4, 0, tzinfo=UTC), 1),
        (datetime(2025, 6, 2, 4, 0, tzinfo=UTC), datetime(2025, 6, 2, 20, 0, tzinfo=UTC), None),
        (datetime(2025, 6, 2, 20, 0, tzinfo=UTC), datetime(2025, 6, 3, tzinfo=UTC), 1),
    ]


def test_untargeted_zone_is_empty():
    cal = StoreCalendar("UTC", [_campaign(1, 5, time(20, 0), time(4, 0), zones=("A",))])
    segments = cal.generate("Z", datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 2, tzinfo=UTC))
    assert len(segments) == 1 and segments[0].winner is None
    assert cal.winner_at("Z", datetime(2025, 6, 1, 21, 0, tzinfo=UTC)) is None


def test_winner_at_outside_generated_range():
    cal = StoreCalendar("UTC", [_campaign(1, 5, time(20, 0), time(4, 0))])
    cal.generate("A", datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 2, tzinfo=UTC))
    # 缓存范围之外的时刻仍应正确计算
    assert cal.winner_at("A", datetime(2025, 7, 1, 21, 0, tzinfo=UTC)) == 1
    assert cal.winner_at("A", datetime(2025, 7, 1, 12, 0, tzinfo=UTC)) is None


def test_invalid_campaign_rejected():
    with pytest.raises(ValueError):
        _campaign(1, 5, time(2, 0), time(2, 0))  # 起止相同
    with pytest.raises(ValueError):
        _campaign(1, 0, time(2, 0), time(3, 0))  # 优先级越界


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError):
        StoreCalendar("UTC", [_campaign(1, 5, time(2, 0), time(3, 0)),
                              _campaign(1, 6, time(4, 0), time(5, 0))])


def test_invalid_range_rejected():
    cal = StoreCalendar("UTC", [])
    with pytest.raises(ValueError):
        cal.generate("A", datetime(2025, 6, 2, tzinfo=UTC), datetime(2025, 6, 1, tzinfo=UTC))
