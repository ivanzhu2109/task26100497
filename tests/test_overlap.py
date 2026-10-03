"""跨午夜窗口 + 多活动竞争叠加：逐秒验证、单时刻查询一致性、覆盖与合并。"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from store_calendar import Activity, StoreCalendar

UTC = timezone.utc
TZ = ZoneInfo("Asia/Shanghai")  # UTC+8，无夏令时，便于手工推算
SUNDAY = date(2025, 6, 1)  # 2025-06-01 是周日
# 周日 22:00 -> 周一 02:00（本地），即 UTC 周日 14:00 -> 18:00
RANGE_START = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
RANGE_END = datetime(2025, 6, 1, 20, 0, tzinfo=UTC)


def utc(hour, minute=0):
    return datetime(2025, 6, 1, hour, minute, tzinfo=UTC)


def build_activities():
    full = (datetime(2025, 5, 1, tzinfo=UTC), datetime(2025, 7, 1, tzinfo=UTC))
    return [
        # 基础活动：周日跨午夜窗口 22:00->02:00，优先级 5
        Activity(10, {"p"}, 5, full[0], full[1], {6}, time(22, 0), time(2, 0)),
        # 更高优先级：周日 23:00->01:00（UTC 15:00-17:00）
        Activity(20, {"p"}, 7, full[0], full[1], {6}, time(23, 0), time(1, 0)),
        # 与 20 同优先级同窗口但编号更大：完全被平局规则遮蔽
        Activity(30, {"p"}, 7, full[0], full[1], {6}, time(23, 0), time(1, 0)),
        # 生效区间恰在窗口内部开始并结束（UTC 15:35-16:25），优先级最高
        Activity(40, {"p"}, 9, utc(15, 35), utc(16, 25), {6}, time(23, 0), time(1, 0)),
        # 与 10 同窗口但优先级更低：完全被遮蔽
        Activity(50, {"p"}, 1, full[0], full[1], {6}, time(22, 0), time(2, 0)),
        # 生效区间在窗口内部开始（14:30）并提前结束（15:10）
        Activity(60, {"p"}, 8, utc(14, 30), utc(15, 10), {6}, time(22, 0), time(2, 0)),
    ]


def brute_force_winner(activities, partition, instant):
    """按业务规则独立逐时刻求值，作为对照模型。"""
    local = instant.astimezone(TZ)
    lt, ld = local.time(), local.date()
    best = None
    for act in activities:
        if partition not in act.partitions:
            continue
        if not act.effective_start <= instant < act.effective_end:
            continue
        ws, we = act.window_start, act.window_end
        if we > ws:
            if not ws <= lt < we:
                continue
            wdate = ld
        else:
            if lt >= ws:
                wdate = ld
            elif lt < we:
                wdate = ld - timedelta(days=1)
            else:
                continue
        if wdate.weekday() not in act.weekdays:
            continue
        key = (-act.priority, act.activity_id)
        if best is None or key < best:
            best = key
    return best[1] if best else None


def expected_timeline():
    """手工推算的获胜区间（UTC，左闭右开）。"""
    return [
        (utc(14, 0), utc(14, 30), 10),
        (utc(14, 30), utc(15, 10), 60),
        (utc(15, 10), utc(15, 35), 20),
        (utc(15, 35), utc(16, 25), 40),
        (utc(16, 25), utc(17, 0), 20),
        (utc(17, 0), utc(18, 0), 10),
    ]


def test_cross_midnight_competition_second_by_second():
    activities = build_activities()
    store = StoreCalendar("Asia/Shanghai", activities)
    result = store.calendar("p", RANGE_START, RANGE_END)

    # 获胜区间与手工推算一致
    wins = [(e.start, e.end, e.activity_id) for e in result if e.activity_id is not None]
    assert wins == expected_timeline()

    # 短范围内每一秒：日历、单时刻查询、对照模型三者一致
    t = RANGE_START
    while t < RANGE_END:
        expected = brute_force_winner(activities, "p", t)
        assert result.winner_at(t) == expected, t
        assert store.winner_at("p", t) == expected, t
        t += timedelta(seconds=1)


def test_calendar_coverage_and_maximal_merge():
    activities = build_activities()
    store = StoreCalendar("Asia/Shanghai", activities)
    result = store.calendar("p", RANGE_START, RANGE_END)
    entries = list(result)

    # 无重叠、无遗漏地覆盖请求范围
    assert entries[0].start == RANGE_START
    assert entries[-1].end == RANGE_END
    for prev, nxt in zip(entries, entries[1:]):
        assert prev.end == nxt.start
        assert prev.start < prev.end

    # 最大化合并：相邻片段结果必不相同（落败活动边界不产生多余分段）
    for prev, nxt in zip(entries, entries[1:]):
        assert prev.activity_id != nxt.activity_id

    # 请求范围两端为空结果
    assert entries[0].activity_id is None
    assert entries[-1].activity_id is None


def test_shadowed_activities_never_win():
    activities = build_activities()
    store = StoreCalendar("Asia/Shanghai", activities)
    result = store.calendar("p", RANGE_START, RANGE_END)
    winners = {e.activity_id for e in result if e.activity_id is not None}
    assert 30 not in winners  # 同优先级平局，编号大者被遮蔽
    assert 50 not in winners  # 同窗口低优先级被遮蔽
    assert winners == {10, 20, 40, 60}


def test_midnight_portion_belongs_to_window_start_day():
    # 仅周日生效的跨午夜窗口：周一 00:00-02:00（UTC 周日 16:00-18:00）仍获胜；
    # 周一深夜 22:00（UTC 周一 14:00）不再开窗，因为窗口开始日是周一。
    act = Activity(
        1, {"p"}, 5, datetime(2025, 5, 1, tzinfo=UTC), datetime(2025, 7, 1, tzinfo=UTC),
        {6}, time(22, 0), time(2, 0),
    )
    store = StoreCalendar("Asia/Shanghai", [act])
    assert store.winner_at("p", datetime(2025, 6, 1, 17, 0, tzinfo=UTC)) == 1  # 周一 01:00 本地
    assert store.winner_at("p", datetime(2025, 6, 2, 14, 0, tzinfo=UTC)) is None  # 周一 22:00 本地
