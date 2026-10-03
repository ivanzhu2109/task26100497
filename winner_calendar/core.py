"""核心计算：资格窗口展开、竞争扫描、日历生成与单时刻查询。"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import CalendarInterval, Campaign

_UTC = timezone.utc
_ONE_DAY = timedelta(days=1)
_ONE_SECOND = timedelta(seconds=1)
_SCAN_STEP = timedelta(hours=6)
# IANA 偏移范围约在 -12h 至 +14h，取 15h 余量保证窗口的 UTC 像集被完整覆盖。
_MAX_OFFSET = timedelta(hours=15)


class _TzTimeline:
    """一个 IANA 时区在一段 UTC 范围内的偏移分段时间线。

    每个分段内偏移恒定，本地时刻 = UTC + 偏移，因此窗口的 UTC 像集
    可以按分段精确求交。分段边界（偏移变化时刻）精确到秒。
    """

    def __init__(self, tz: ZoneInfo, start: datetime, end: datetime) -> None:
        self.tz = tz
        self._points: list[datetime] = [start]
        self._offsets: list[timedelta] = [self._offset_at(tz, start)]
        cursor = start
        while cursor < end:
            nxt = min(cursor + _SCAN_STEP, end)
            offset = self._offset_at(tz, nxt)
            if offset != self._offsets[-1]:
                transition = self._find_transition(tz, cursor, nxt, self._offsets[-1])
                self._points.append(transition)
                self._offsets.append(offset)
                cursor = transition
            else:
                cursor = nxt
        self._points.append(end)

    @staticmethod
    def _offset_at(tz: ZoneInfo, moment: datetime) -> timedelta:
        return moment.astimezone(tz).utcoffset()  # type: ignore[return-value]

    @staticmethod
    def _find_transition(
        tz: ZoneInfo, lo: datetime, hi: datetime, off_before: timedelta
    ) -> datetime:
        """二分查找 (lo, hi] 内第一个偏移不等于 off_before 的 UTC 时刻（精确到秒）。"""
        while hi - lo > _ONE_SECOND:
            half_seconds = int((hi - lo).total_seconds()) // 2
            mid = lo + timedelta(seconds=half_seconds)
            if _TzTimeline._offset_at(tz, mid) == off_before:
                lo = mid
            else:
                hi = mid
        return hi

    def window_image(
        self, day: date, start: time, end: time
    ) -> list[tuple[datetime, datetime]]:
        """本地日期 day 上窗口 [start, end) 的 UTC 像集（已排序、已合并相邻重叠）。

        end <= start 视为跨午夜（结束时刻落在次日）。不存在的本地时刻不产生
        展示机会也不顺延；重复出现的本地时刻两段都保留。
        """
        end_day = day + _ONE_DAY if end <= start else day
        s_naive = datetime.combine(day, start)
        e_naive = datetime.combine(end_day, end)
        lo = (s_naive - _MAX_OFFSET).replace(tzinfo=_UTC)
        hi = (e_naive + _MAX_OFFSET).replace(tzinfo=_UTC)
        intervals: list[tuple[datetime, datetime]] = []
        points = self._points
        idx = 0
        # 定位第一个右端点超过 lo 的分段。
        while idx + 1 < len(points) and points[idx + 1] <= lo:
            idx += 1
        while idx + 1 < len(points) and points[idx] < hi:
            offset = self._offsets[idx]
            img_start = (s_naive - offset).replace(tzinfo=_UTC)
            img_end = (e_naive - offset).replace(tzinfo=_UTC)
            seg_start = max(img_start, points[idx])
            seg_end = min(img_end, points[idx + 1])
            if seg_start < seg_end:
                if intervals and seg_start <= intervals[-1][1]:
                    if seg_end > intervals[-1][1]:
                        intervals[-1] = (intervals[-1][0], seg_end)
                else:
                    intervals.append((seg_start, seg_end))
            idx += 1
        return intervals


def _campaign_utc_intervals(
    campaign: Campaign, timeline: _TzTimeline, range_start: datetime, range_end: datetime
) -> list[tuple[datetime, datetime]]:
    """展开单个活动在 [range_start, range_end) UTC 内的全部资格区间（已排序、不重叠）。

    星期筛选按窗口开始的本地日期判断；结果与活动生效区间及请求范围求交。
    """
    start = max(range_start, campaign.effective_from)
    end = min(range_end, campaign.effective_to)
    if start >= end:
        return []
    # 跨午夜窗口的结束时刻可能落在窗口开始日期的次日，向前多取一天。
    first_day = (start - _ONE_DAY).astimezone(timeline.tz).date()
    last_day = end.astimezone(timeline.tz).date()
    intervals: list[tuple[datetime, datetime]] = []
    day = first_day
    while day <= last_day:
        if day.weekday() in campaign.weekdays:
            for w_start, w_end in timeline.window_image(
                day, campaign.window_start, campaign.window_end
            ):
                lo = max(w_start, start)
                hi = min(w_end, end)
                if lo < hi:
                    intervals.append((lo, hi))
        day += _ONE_DAY
    intervals.sort()
    merged: list[tuple[datetime, datetime]] = []
    for w_start, w_end in intervals:
        if merged and w_start <= merged[-1][1]:
            if w_end > merged[-1][1]:
                merged[-1] = (merged[-1][0], w_end)
        else:
            merged.append((w_start, w_end))
    return merged


class StoreCalendar:
    """单门店的获胜日历计算器。

    构造时传入 IANA 时区名与活动列表；配置在一次计算期间不变。
    所有结果仅保存在进程内存。
    """

    def __init__(self, timezone: str, campaigns: list[Campaign]) -> None:
        self._tz = ZoneInfo(timezone)
        ids = [c.campaign_id for c in campaigns]
        if len(ids) != len(set(ids)):
            raise ValueError("活动编号必须唯一")
        self._campaigns = list(campaigns)
        # 每个分区最近一次生成的日历缓存：zone -> (start, end, segments, starts)
        self._cache: dict[str, tuple[datetime, datetime, list[CalendarInterval], list[datetime]]] = {}

    def _segments(self, zone: str, start: datetime, end: datetime) -> list[CalendarInterval]:
        """扫描线合并：对每个 UTC 时刻取优先级最高、同优先级编号最小的活动。"""
        timeline = _TzTimeline(self._tz, start - 3 * _ONE_DAY, end + 3 * _ONE_DAY)
        events: list[tuple[datetime, int, int]] = []
        for campaign in self._campaigns:
            if zone not in campaign.zones:
                continue
            for w_start, w_end in _campaign_utc_intervals(campaign, timeline, start, end):
                events.append((w_start, 1, campaign.campaign_id))
                events.append((w_end, -1, campaign.campaign_id))
        events.sort()
        by_id = {c.campaign_id: c for c in self._campaigns}
        active: set[int] = set()
        segments: list[CalendarInterval] = []
        cursor = start
        idx = 0
        while idx < len(events):
            t = events[idx][0]
            if t > cursor:
                segments.append(CalendarInterval(cursor, t, self._winner(active, by_id)))
            while idx < len(events) and events[idx][0] == t:
                _, delta, cid = events[idx]
                if delta > 0:
                    active.add(cid)
                else:
                    active.discard(cid)
                idx += 1
            cursor = t
        if cursor < end:
            segments.append(CalendarInterval(cursor, end, self._winner(active, by_id)))
        return self._coalesce(segments)

    @staticmethod
    def _winner(active: set[int], by_id: dict[int, Campaign]) -> int | None:
        best: Campaign | None = None
        for cid in active:
            c = by_id[cid]
            if best is None or (c.priority, -c.campaign_id) > (best.priority, -best.campaign_id):
                best = c
        return best.campaign_id if best else None

    @staticmethod
    def _coalesce(segments: list[CalendarInterval]) -> list[CalendarInterval]:
        merged: list[CalendarInterval] = []
        for seg in segments:
            if merged and merged[-1].winner == seg.winner and merged[-1].end == seg.start:
                merged[-1] = CalendarInterval(merged[-1].start, seg.end, seg.winner)
            else:
                merged.append(seg)
        return merged

    def winner_at(self, zone: str, moment: datetime) -> int | None:
        """查询指定分区在某个 UTC 时刻的获胜活动编号，无候选返回 None。"""
        cached = self._cache.get(zone)
        if cached is not None:
            start, end, segments, starts = cached
            if start <= moment < end:
                idx = bisect_right(starts, moment) - 1
                return segments[idx].winner
        for seg in self._segments(zone, moment, moment + timedelta(seconds=1)):
            if seg.start <= moment < seg.end:
                return seg.winner
        return None

    def generate(self, zone: str, start: datetime, end: datetime) -> list[CalendarInterval]:
        """生成指定分区在 [start, end) UTC 范围内的完整日历。

        返回区间无重叠、无遗漏地覆盖请求范围，相邻且结果相同的区间已合并。
        """
        if start >= end:
            raise ValueError("请求范围必须满足 start < end")
        segments = self._segments(zone, start, end)
        self._cache[zone] = (start, end, segments, [s.start for s in segments])
        return segments
