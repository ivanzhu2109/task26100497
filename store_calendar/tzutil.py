"""时区工具：UTC 偏移变化（夏令时）转换点探测。"""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import List, Tuple

_ONE_SECOND = timedelta(seconds=1)
_SCAN_STEP = timedelta(hours=6)


def _offset_at(tz: tzinfo, utc_instant: datetime) -> timedelta:
    return utc_instant.astimezone(tz).utcoffset()


def find_offset_transitions(
    tz: tzinfo, start: datetime, end: datetime
) -> List[Tuple[datetime, timedelta]]:
    """返回 (start, end) 内每次 utcoffset 变化的 (UTC 时刻, 变化后偏移)，按时间升序。

    转换点精确到 1 秒。先以 6 小时步长扫描定位变化区间，再二分查找
    偏移发生变化的第一个 UTC 秒。
    """
    transitions: List[Tuple[datetime, timedelta]] = []
    prev_t = start
    prev_off = _offset_at(tz, start)
    t = start + _SCAN_STEP
    while t < end:
        off = _offset_at(tz, t)
        if off != prev_off:
            transitions.append((_bisect_transition(tz, prev_t, t), off))
            prev_off = off
        prev_t = t
        t += _SCAN_STEP
    off = _offset_at(tz, end)
    if off != prev_off:
        transitions.append((_bisect_transition(tz, prev_t, end), off))
    return transitions


def _bisect_transition(tz: tzinfo, lo: datetime, hi: datetime) -> datetime:
    """在 (lo, hi] 内找到 utcoffset 与 lo 处不同的第一个 UTC 秒。"""
    lo_off = _offset_at(tz, lo)
    while hi - lo > _ONE_SECOND:
        mid = lo + (hi - lo) / 2
        mid = mid.replace(microsecond=0)
        if mid <= lo:
            mid = lo + _ONE_SECOND
        if _offset_at(tz, mid) != lo_off:
            hi = mid
        else:
            lo = mid
    return hi.replace(microsecond=0)
