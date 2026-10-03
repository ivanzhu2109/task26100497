"""验收场景：跨午夜窗口与多活动竞争（优先级、编号、遮蔽、生效区间）。"""
from datetime import datetime, time, timedelta, timezone

from winner_calendar import Campaign, StoreCalendar

UTC = timezone.utc

# 场景：UTC 时区，周日 22:00 跨午夜进入周一 02:00 的窗口（星期按窗口开始日=周日判断）。
# 2025-06-01 是周日。
SUNDAY = datetime(2025, 6, 1, tzinfo=UTC)


def _campaign(cid, priority, ws, we, weekdays=(6,), eff_from=None, eff_to=None):
    return Campaign(
        campaign_id=cid,
        zones=frozenset({"A"}),
        priority=priority,
        effective_from=eff_from or datetime(2025, 1, 1, tzinfo=UTC),
        effective_to=eff_to or datetime(2026, 1, 1, tzinfo=UTC),
        weekdays=frozenset(weekdays),
        window_start=ws,
        window_end=we,
    )


def _build() -> StoreCalendar:
    return StoreCalendar("UTC", [
        _campaign(10, 5, time(22, 0), time(2, 0)),                      # 基准：周日 22:00-周一 02:00
        _campaign(20, 7, time(23, 0), time(1, 0)),                      # 更高优先级，遮蔽 23:00-01:00
        _campaign(30, 5, time(21, 30), time(22, 30)),                   # 同优先级，编号更大，22:00-22:30 落败
        _campaign(40, 3, time(22, 0), time(2, 0)),                      # 完全被 10 遮蔽
        _campaign(50, 9, time(22, 0), time(2, 0),                       # 生效区间恰在窗口内部
                  eff_from=datetime(2025, 6, 1, 23, 30, tzinfo=UTC),
                  eff_to=datetime(2025, 6, 2, 0, 30, tzinfo=UTC)),
        _campaign(60, 10, time(22, 0), time(2, 0), weekdays=(0,)),      # 仅周一，周日晚不出现
    ])


EXPECTED = [
    (datetime(2025, 6, 1, 20, 0, tzinfo=UTC), datetime(2025, 6, 1, 21, 30, tzinfo=UTC), None),
    (datetime(2025, 6, 1, 21, 30, tzinfo=UTC), datetime(2025, 6, 1, 22, 0, tzinfo=UTC), 30),
    (datetime(2025, 6, 1, 22, 0, tzinfo=UTC), datetime(2025, 6, 1, 23, 0, tzinfo=UTC), 10),
    (datetime(2025, 6, 1, 23, 0, tzinfo=UTC), datetime(2025, 6, 1, 23, 30, tzinfo=UTC), 20),
    (datetime(2025, 6, 1, 23, 30, tzinfo=UTC), datetime(2025, 6, 2, 0, 30, tzinfo=UTC), 50),
    (datetime(2025, 6, 2, 0, 30, tzinfo=UTC), datetime(2025, 6, 2, 1, 0, tzinfo=UTC), 20),
    (datetime(2025, 6, 2, 1, 0, tzinfo=UTC), datetime(2025, 6, 2, 2, 0, tzinfo=UTC), 10),
    (datetime(2025, 6, 2, 2, 0, tzinfo=UTC), datetime(2025, 6, 2, 4, 0, tzinfo=UTC), None),
]

RANGE_START = EXPECTED[0][0]
RANGE_END = EXPECTED[-1][1]


def test_calendar_matches_expected_segments():
    segments = _build().generate("A", RANGE_START, RANGE_END)
    assert [(s.start, s.end, s.winner) for s in segments] == EXPECTED


def test_full_coverage_and_maximal_merge():
    segments = _build().generate("A", RANGE_START, RANGE_END)
    assert segments[0].start == RANGE_START
    assert segments[-1].end == RANGE_END
    for prev, nxt in zip(segments, segments[1:]):
        assert prev.end == nxt.start, "区间必须无重叠、无遗漏"
        assert prev.winner != nxt.winner, "相邻同结果区间必须合并"


def test_every_second_consistent_with_point_query():
    cal = _build()
    segments = cal.generate("A", RANGE_START, RANGE_END)
    moment = RANGE_START
    idx = 0
    while moment < RANGE_END:
        while idx + 1 < len(segments) and moment >= segments[idx].end:
            idx += 1
        seg = segments[idx]
        assert seg.start <= moment < seg.end
        assert cal.winner_at("A", moment) == seg.winner, f"{moment} 单时刻查询与日历不一致"
        moment += timedelta(seconds=1)


def test_midnight_part_belongs_to_window_start_day():
    # 窗口按周日（开始日）筛选：周一 00:00-02:00 的部分仍由周日的窗口产生，
    # 而仅周一（weekdays={0}）的活动 60 在周日晚不会出现。
    cal = _build()
    assert cal.winner_at("A", datetime(2025, 6, 2, 1, 30, tzinfo=UTC)) == 10
    assert cal.winner_at("A", datetime(2025, 6, 1, 22, 30, tzinfo=UTC)) == 10
