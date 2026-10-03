"""规模与性能验收：50 活动 / 20 分区，10 年日历 < 10s，10 万次查询 < 3s，内存 < 256MiB。"""
import random
import resource
import time as time_mod
import tracemalloc
from datetime import datetime, time, timedelta, timezone

from store_calendar import Activity, StoreCalendar

UTC = timezone.utc
PARTITIONS = [f"zone-{i:02d}" for i in range(20)]
CAL_START = datetime(2025, 1, 1, tzinfo=UTC)
CAL_END = datetime(2035, 1, 1, tzinfo=UTC)  # 连续 10 年
MI_B = 1024 * 1024


def build_fleet():
    rng = random.Random(20250601)
    activities = []
    for i in range(50):
        partitions = set(rng.sample(PARTITIONS, rng.randint(1, 6)))
        start_minute = rng.randrange(0, 24 * 60)
        duration_minutes = rng.randrange(30, 8 * 60)
        end_minute = (start_minute + duration_minutes) % (24 * 60)
        ws = time(start_minute // 60, start_minute % 60)
        we = time(end_minute // 60, end_minute % 60)
        if we == ws:
            we = time((end_minute + 1) // 60 % 24, (end_minute + 1) % 60)
        weekdays = set(rng.sample(range(7), rng.randint(1, 7)))
        eff_start = datetime(2024, 6, 1, tzinfo=UTC) + timedelta(days=rng.randrange(0, 365))
        eff_end = datetime(2035, 6, 1, tzinfo=UTC) - timedelta(days=rng.randrange(0, 365))
        activities.append(
            Activity(i + 1, partitions, rng.randint(1, 10), eff_start, eff_end,
                     weekdays, ws, we)
        )
    return activities


def test_ten_year_calendar_performance():
    store = StoreCalendar("America/New_York", build_fleet())

    tracemalloc.start()
    t0 = time_mod.perf_counter()
    result = store.calendar("zone-03", CAL_START, CAL_END)
    gen_seconds = time_mod.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 日历完整性：无重叠、无遗漏、最大化合并
    entries = list(result)
    assert entries[0].start == CAL_START and entries[-1].end == CAL_END
    for prev, nxt in zip(entries, entries[1:]):
        assert prev.end == nxt.start
        assert prev.activity_id != nxt.activity_id

    # 生成后范围内 100000 次时刻查询
    rng = random.Random(42)
    span_seconds = int((CAL_END - CAL_START).total_seconds())
    instants = [CAL_START + timedelta(seconds=rng.randrange(span_seconds))
                for _ in range(100_000)]
    t0 = time_mod.perf_counter()
    hits = sum(1 for t in instants if result.winner_at(t) is not None)
    query_seconds = time_mod.perf_counter() - t0
    assert hits > 0

    peak_mib = peak_bytes / MI_B
    print(f"\n[perf] 10年日历生成: {gen_seconds:.3f}s, 条目数: {len(entries)}, "
          f"峰值内存: {peak_mib:.1f} MiB")
    print(f"[perf] 100000 次时刻查询: {query_seconds:.3f}s, 命中: {hits}")
    ru_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / MI_B
    print(f"[perf] 进程 ru_maxrss: {ru_mib:.1f} MiB")

    assert gen_seconds < 10, f"日历生成耗时 {gen_seconds:.1f}s 超过 10s"
    assert peak_bytes < 256 * MI_B, f"峰值内存 {peak_mib:.1f} MiB 超过 256 MiB"
    assert query_seconds < 3, f"时刻查询耗时 {query_seconds:.1f}s 超过 3s"


def test_all_partitions_calendar_consistency():
    """抽查：每个分区日历与逐时刻对照模型一致（抽 200 个时刻/分区）。"""
    activities = build_fleet()
    store = StoreCalendar("America/New_York", activities)
    rng = random.Random(7)
    span_seconds = int((CAL_END - CAL_START).total_seconds())
    for partition in PARTITIONS:
        result = store.calendar(partition, CAL_START, CAL_END)
        entries = list(result)
        assert entries[0].start == CAL_START and entries[-1].end == CAL_END
        for prev, nxt in zip(entries, entries[1:]):
            assert prev.end == nxt.start
            assert prev.activity_id != nxt.activity_id
        for _ in range(200):
            t = CAL_START + timedelta(seconds=rng.randrange(span_seconds))
            assert result.winner_at(t) == store.winner_at(partition, t), (partition, t)
