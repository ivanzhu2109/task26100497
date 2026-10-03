"""夏令时切换场景验收测试（单活动，其他资格条件均满足）。"""
from datetime import datetime, time, timezone, timedelta

from store_calendar import Activity, StoreCalendar

UTC = timezone.utc
ALL_DAYS = set(range(7))


def make_store(tz_name, window_start, window_end, eff_start, eff_end):
    act = Activity(1, {"p"}, 5, eff_start, eff_end, ALL_DAYS, window_start, window_end)
    return StoreCalendar(tz_name, [act])


def win_segments(result):
    return [(e.start, e.end) for e in result if e.activity_id is not None]


def test_ny_spring_forward_skipped_local_times():
    # 2025-03-09 America/New_York：02:00 跳到 03:00（UTC 07:00 切换）
    # 窗口 02:10-03:10 中只有 03:00-03:10 真实存在 -> UTC 07:00-07:10
    store = make_store(
        "America/New_York", time(2, 10), time(3, 10),
        datetime(2025, 3, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC),
    )
    result = store.calendar(
        "p", datetime(2025, 3, 9, tzinfo=UTC), datetime(2025, 3, 10, tzinfo=UTC)
    )
    assert win_segments(result) == [
        (datetime(2025, 3, 9, 7, 0, tzinfo=UTC), datetime(2025, 3, 9, 7, 10, tzinfo=UTC))
    ]
    # 请求范围内的空结果
    assert result[0].activity_id is None
    assert result[0].start == datetime(2025, 3, 9, tzinfo=UTC)
    assert result[0].end == datetime(2025, 3, 9, 7, 0, tzinfo=UTC)
    assert result[-1].activity_id is None
    assert result[-1].end == datetime(2025, 3, 10, tzinfo=UTC)
    # 被跳过的本地时刻（如 02:30 对应的“伪时刻”）不得顺延：07:30 应无结果
    assert store.winner_at("p", datetime(2025, 3, 9, 7, 30, tzinfo=UTC)) is None
    assert store.winner_at("p", datetime(2025, 3, 9, 7, 5, tzinfo=UTC)) == 1


def test_ny_fall_back_repeated_local_times():
    # 2025-11-02 America/New_York：02:00 回拨到 01:00（UTC 06:00 切换）
    # 窗口 01:15-01:45 出现两次 -> UTC 05:15-05:45 与 06:15-06:45，中间断开
    store = make_store(
        "America/New_York", time(1, 15), time(1, 45),
        datetime(2025, 10, 1, tzinfo=UTC), datetime(2025, 12, 1, tzinfo=UTC),
    )
    result = store.calendar(
        "p", datetime(2025, 11, 2, tzinfo=UTC), datetime(2025, 11, 3, tzinfo=UTC)
    )
    assert win_segments(result) == [
        (datetime(2025, 11, 2, 5, 15, tzinfo=UTC), datetime(2025, 11, 2, 5, 45, tzinfo=UTC)),
        (datetime(2025, 11, 2, 6, 15, tzinfo=UTC), datetime(2025, 11, 2, 6, 45, tzinfo=UTC)),
    ]
    # 两段之间必须是空结果，不能连成一段
    gap = [e for e in result if e.start == datetime(2025, 11, 2, 5, 45, tzinfo=UTC)]
    assert len(gap) == 1 and gap[0].activity_id is None
    assert gap[0].end == datetime(2025, 11, 2, 6, 15, tzinfo=UTC)
    # 逐秒核对两段各自获胜
    for base in (5, 6):
        for minute in range(15, 45):
            t = datetime(2025, 11, 2, base, minute, tzinfo=UTC)
            assert store.winner_at("p", t) == 1, t
    assert store.winner_at("p", datetime(2025, 11, 2, 6, 0, tzinfo=UTC)) is None


def test_lord_howe_thirty_minute_fallback():
    # 2025-04-06 Australia/Lord_Howe：02:00 +11:00 回拨到 01:30 +10:30
    # （UTC 2025-04-05 15:00 切换，偏移变化仅 30 分钟）
    # 窗口 01:40-01:50 出现两次 -> UTC 04-05 14:40-14:50 与 15:10-15:20
    store = make_store(
        "Australia/Lord_Howe", time(1, 40), time(1, 50),
        datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 5, 1, tzinfo=UTC),
    )
    result = store.calendar(
        "p", datetime(2025, 4, 5, tzinfo=UTC), datetime(2025, 4, 6, tzinfo=UTC)
    )
    assert win_segments(result) == [
        (datetime(2025, 4, 5, 14, 40, tzinfo=UTC), datetime(2025, 4, 5, 14, 50, tzinfo=UTC)),
        (datetime(2025, 4, 5, 15, 10, tzinfo=UTC), datetime(2025, 4, 5, 15, 20, tzinfo=UTC)),
    ]
    gap = [e for e in result if e.start == datetime(2025, 4, 5, 14, 50, tzinfo=UTC)]
    assert len(gap) == 1 and gap[0].activity_id is None
    assert gap[0].end == datetime(2025, 4, 5, 15, 10, tzinfo=UTC)
