"""规模与性能验收：50 个活动、20 个分区、单分区 10 年日历与 10 万次查询。"""
import random
import time as time_mod
import tracemalloc
from datetime import datetime, time, timedelta, timezone

import pytest

from winner_calendar import Campaign, StoreCalendar

UTC = timezone.utc
ZONES = [f"zone-{i:02d}" for i in range(20)]
RANGE_START = datetime(2025, 1, 1, tzinfo=UTC)
RANGE_END = datetime(2035, 1, 1, tzinfo=UTC)  # 连续 10 年


def _build_scale_calendar() -> StoreCalendar:
    rng = random.Random(20250601)
    campaigns = []
    for cid in range(1, 51):
        zones = frozenset(rng.sample(ZONES, rng.randint(1, 8)))
        start_minute = rng.randint(0, 23 * 60)
        duration = timedelta(minutes=rng.randint(30, 8 * 60))
        ws = time(start_minute // 60, start_minute % 60)
        end_dt = datetime(2000, 1, 1) + timedelta(minutes=start_minute) + duration
        we = time(end_dt.hour, end_dt.minute)
        eff_from = RANGE_START + timedelta(days=rng.randint(0, 365))
        eff_to = RANGE_END - timedelta(days=rng.randint(0, 365))
        campaigns.append(Campaign(
            campaign_id=cid,
            zones=zones,
            priority=rng.randint(1, 10),
            effective_from=eff_from,
            effective_to=eff_to,
            weekdays=frozenset(rng.sample(range(7), rng.randint(1, 7))),
            window_start=ws,
            window_end=we,
        ))
    return StoreCalendar("America/New_York", campaigns)


@pytest.fixture(scope="module")
def scale_result():
    cal = _build_scale_calendar()
    tracemalloc.start()
    t0 = time_mod.perf_counter()
    segments = cal.generate("zone-00", RANGE_START, RANGE_END)
    gen_seconds = time_mod.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rng = random.Random(42)
    span = (RANGE_END - RANGE_START).total_seconds()
    moments = [RANGE_START + timedelta(seconds=rng.randrange(int(span))) for _ in range(100_000)]
    t0 = time_mod.perf_counter()
    winners = [cal.winner_at("zone-00", m) for m in moments]
    query_seconds = time_mod.perf_counter() - t0

    print(f"\n[规模] 10 年日历生成: {gen_seconds:.2f}s (限 10s), "
          f"区间数: {len(segments)}, 峰值内存: {peak_bytes / 2**20:.1f} MiB (限 256 MiB)")
    print(f"[规模] 100000 次单时刻查询: {query_seconds:.2f}s (限 3s)")
    return cal, segments, moments, winners, gen_seconds, query_seconds, peak_bytes


def test_generation_within_10_seconds(scale_result):
    assert scale_result[4] < 10


def test_peak_memory_within_256_mib(scale_result):
    assert scale_result[6] < 256 * 2**20


def test_100k_queries_within_3_seconds(scale_result):
    assert scale_result[5] < 3


def test_generated_calendar_covers_range(scale_result):
    _, segments, *_ = scale_result
    assert segments[0].start == RANGE_START
    assert segments[-1].end == RANGE_END
    for prev, nxt in zip(segments, segments[1:]):
        assert prev.end == nxt.start
        assert prev.winner != nxt.winner


def test_point_queries_match_calendar(scale_result):
    cal, segments, moments, winners, *_ = scale_result
    starts = [s.start for s in segments]
    from bisect import bisect_right
    for moment, winner in zip(moments[:1000], winners[:1000]):
        idx = bisect_right(starts, moment) - 1
        assert segments[idx].winner == winner
