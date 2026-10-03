"""核心引擎：资格区间计算、竞争裁决与日历生成。"""
from __future__ import annotations

import heapq
from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .models import Activity, CalendarEntry
from .tzutil import find_offset_transitions

_ONE_DAY = timedelta(days=1)
_PAD = timedelta(days=2)  # 覆盖最大 UTC 偏移（14h）与跨午夜窗口的余量
_MAX_OFFSET = timedelta(hours=14)


def _window_utc_intervals(
    tz: ZoneInfo,
    transitions: List[Tuple[datetime, timedelta]],
    window_date: date,
    window_start: time,
    window_end: time,
) -> List[Tuple[datetime, datetime]]:
    """计算某本地日期上日内窗口对应的 UTC 区间集合（左闭右开）。

    夏令时跳过的本地时刻不产生区间；重复出现的本地时刻两段都保留。
    相邻相接的区间会被合并，被跳过时刻隔开的区间保持分离。
    """
    start_dt = datetime.combine(window_date, window_start)
    if window_end > window_start:
        end_dt = datetime.combine(window_date, window_end)
    else:  # 跨午夜：结束时刻归次日，但仍属窗口开始日
        end_dt = datetime.combine(window_date + _ONE_DAY, window_end)

    # 该窗口可能覆盖的 UTC 范围（含偏移余量）
    span_lo = (start_dt - _MAX_OFFSET).replace(tzinfo=timezone.utc)
    span_hi = (end_dt + _MAX_OFFSET).replace(tzinfo=timezone.utc)

    # 按偏移转换点切分；每个分段内 local = utc + offset 为线性映射
    bounds = [span_lo]
    bounds.extend(t for t, _ in transitions if span_lo < t < span_hi)
    bounds.append(span_hi)

    intervals: List[Tuple[datetime, datetime]] = []
    for i in range(len(bounds) - 1):
        seg_lo, seg_hi = bounds[i], bounds[i + 1]
        offset = seg_lo.astimezone(tz).utcoffset()
        # 本地窗口 [start_dt, end_dt) 在该偏移下对应的 UTC 区间
        win_lo = (start_dt - offset).replace(tzinfo=timezone.utc)
        win_hi = (end_dt - offset).replace(tzinfo=timezone.utc)
        lo = max(win_lo, seg_lo)
        hi = min(win_hi, seg_hi)
        if lo < hi:
            intervals.append((lo, hi))

    # 合并相接区间（偏移变化本身不产生断点；被跳过的本地时刻留下真实空隙）
    merged: List[List[datetime]] = []
    for lo, hi in intervals:
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


class CalendarResult(Sequence[CalendarEntry]):
    """一段 UTC 范围内的完整日历，支持范围内秒级快速查询。"""

    def __init__(self, entries: List[CalendarEntry]) -> None:
        self._entries = entries
        self._starts = [e.start for e in entries]

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index):
        return self._entries[index]

    def __iter__(self) -> Iterator[CalendarEntry]:
        return iter(self._entries)

    @property
    def entries(self) -> List[CalendarEntry]:
        return list(self._entries)

    def winner_at(self, instant: datetime) -> Optional[int]:
        """查询日历覆盖范围内某 UTC 时刻的获胜活动编号。"""
        if instant.tzinfo is None:
            raise ValueError("instant 必须带时区信息（UTC 时刻）")
        instant = instant.astimezone(timezone.utc)
        idx = bisect_right(self._starts, instant) - 1
        if idx < 0:
            raise ValueError("instant 不在日历覆盖范围内")
        entry = self._entries[idx]
        if not entry.start <= instant < entry.end:
            raise ValueError("instant 不在日历覆盖范围内")
        return entry.activity_id


class StoreCalendar:
    """单门店活动获胜日历。配置在构造后视为不变，结果仅存进程内存。"""

    def __init__(self, timezone_name: str, activities: Iterable[Activity]) -> None:
        self._tz = ZoneInfo(timezone_name)
        self._by_partition: Dict[str, List[Activity]] = {}
        seen_ids = set()
        for act in activities:
            if not isinstance(act, Activity):
                raise TypeError("activities 必须只包含 Activity 实例")
            if act.activity_id in seen_ids:
                raise ValueError(f"activity_id 重复: {act.activity_id}")
            seen_ids.add(act.activity_id)
            for partition in act.partitions:
                self._by_partition.setdefault(partition, []).append(act)
        # 偏移转换点缓存：(_lo, _hi, transitions)
        self._trans_lo: Optional[datetime] = None
        self._trans_hi: Optional[datetime] = None
        self._transitions: List[Tuple[datetime, timedelta]] = []

    # ---- 内部：偏移转换点缓存 ----

    def _ensure_transitions(self, lo: datetime, hi: datetime) -> None:
        if (
            self._trans_lo is None
            or lo < self._trans_lo
            or hi > self._trans_hi
        ):
            new_lo = min(lo, self._trans_lo) if self._trans_lo else lo
            new_hi = max(hi, self._trans_hi) if self._trans_hi else hi
            self._transitions = find_offset_transitions(self._tz, new_lo, new_hi)
            self._trans_lo, self._trans_hi = new_lo, new_hi

    def _transitions_between(
        self, lo: datetime, hi: datetime
    ) -> List[Tuple[datetime, timedelta]]:
        self._ensure_transitions(lo, hi)
        times = [t for t, _ in self._transitions]
        left = bisect_left(times, lo)
        right = bisect_right(times, hi)
        return self._transitions[left:right]

    # ---- 内部：单活动的资格 UTC 区间 ----

    def _activity_intervals(
        self, act: Activity, range_start: datetime, range_end: datetime
    ) -> List[Tuple[datetime, datetime, int, int]]:
        """返回活动在 [range_start, range_end) 内的资格区间 (start, end, priority, id)。"""
        eff_lo = max(act.effective_start, range_start)
        eff_hi = min(act.effective_end, range_end)
        if eff_lo >= eff_hi:
            return []

        transitions = self._transitions_between(eff_lo - _PAD, eff_hi + _PAD)
        # 窗口开始本地日期可能落在 UTC 范围前后各 2 天
        first_date = (eff_lo.astimezone(self._tz) - _PAD).date()
        last_date = (eff_hi.astimezone(self._tz) + _PAD).date()

        out: List[Tuple[datetime, datetime, int, int]] = []
        day = first_date
        while day <= last_date:
            if day.weekday() in act.weekdays:
                for lo, hi in _window_utc_intervals(
                    self._tz, transitions, day, act.window_start, act.window_end
                ):
                    lo = max(lo, eff_lo)
                    hi = min(hi, eff_hi)
                    if lo < hi:
                        out.append((lo, hi, act.priority, act.activity_id))
            day += _ONE_DAY
        return out

    # ---- 公开 API ----

    def winner_at(self, partition: str, instant: datetime) -> Optional[int]:
        """查询指定分区在某个 UTC 时刻的获胜活动编号，无候选返回 None。"""
        if instant.tzinfo is None:
            raise ValueError("instant 必须带时区信息（UTC 时刻）")
        instant = instant.astimezone(timezone.utc)
        local = instant.astimezone(self._tz)
        local_time = local.time().replace(microsecond=0)
        local_date = local.date()

        best: Optional[Tuple[int, int]] = None  # (-priority, activity_id)
        for act in self._by_partition.get(partition, ()):
            if not act.effective_start <= instant < act.effective_end:
                continue
            ws, we = act.window_start, act.window_end
            if we > ws:  # 当日窗口
                if not ws <= local_time < we:
                    continue
                window_date = local_date
            else:  # 跨午夜窗口
                if local_time >= ws:
                    window_date = local_date
                elif local_time < we:
                    window_date = local_date - _ONE_DAY
                else:
                    continue
            if window_date.weekday() not in act.weekdays:
                continue
            key = (-act.priority, act.activity_id)
            if best is None or key < best:
                best = key
        return best[1] if best else None

    def calendar(
        self, partition: str, start: datetime, end: datetime
    ) -> CalendarResult:
        """生成 [start, end) 的完整日历：无重叠、无遗漏、相邻同结果已合并。"""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start/end 必须带时区信息（UTC 时刻）")
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        if not start < end:
            raise ValueError("start 必须早于 end")

        self._ensure_transitions(start - _PAD, end + _PAD)
        intervals: List[Tuple[datetime, datetime, int, int]] = []
        for act in self._by_partition.get(partition, ()):
            intervals.extend(self._activity_intervals(act, start, end))
        intervals.sort(key=lambda x: (x[0], x[1]))

        # 扫描线：边界集合 + 懒删除堆，裁决规则为优先级大者胜、同优先级编号小者胜
        boundaries = {start, end}
        for lo, hi, _, _ in intervals:
            boundaries.add(lo)
            boundaries.add(hi)
        points = sorted(boundaries)

        entries: List[CalendarEntry] = []
        heap: List[Tuple[int, int, datetime]] = []  # (-priority, id, end)
        idx = 0
        count = len(intervals)
        for k in range(len(points) - 1):
            a, b = points[k], points[k + 1]
            while idx < count and intervals[idx][0] <= a:
                lo, hi, prio, act_id = intervals[idx]
                heapq.heappush(heap, (-prio, act_id, hi))
                idx += 1
            while heap and heap[0][2] <= a:
                heapq.heappop(heap)
            winner = heap[0][1] if heap else None
            if entries and entries[-1].activity_id == winner:
                last = entries[-1]
                entries[-1] = CalendarEntry(last.start, b, last.activity_id)
            else:
                entries.append(CalendarEntry(a, b, winner))
        return CalendarResult(entries)
