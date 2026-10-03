"""数据模型：活动配置与日历结果。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import FrozenSet, Optional


def _as_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} 必须是 datetime，得到 {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} 必须带时区信息（UTC 时刻）")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Activity:
    """一个门店活动配置。

    - activity_id: 唯一整数编号
    - partitions: 目标分区集合
    - priority: 1 至 10，数值越大优先级越高
    - effective_start/effective_end: UTC 生效区间，左闭右开
    - weekdays: 星期集合，0=周一 ... 6=周日（按窗口开始的本地日期判断）
    - window_start/window_end: 本地日内窗口，左闭右开，起止必须不同；
      window_end <= window_start 表示跨午夜，午夜后部分仍归窗口开始日
    """

    activity_id: int
    partitions: FrozenSet[str]
    priority: int
    effective_start: datetime
    effective_end: datetime
    weekdays: FrozenSet[int]
    window_start: time
    window_end: time

    def __post_init__(self) -> None:
        if not isinstance(self.activity_id, int) or isinstance(self.activity_id, bool):
            raise TypeError("activity_id 必须是整数")
        if not 1 <= self.priority <= 10:
            raise ValueError("priority 必须在 1 至 10 之间")
        object.__setattr__(self, "partitions", frozenset(self.partitions))
        object.__setattr__(self, "weekdays", frozenset(self.weekdays))
        if not self.partitions:
            raise ValueError("partitions 不能为空")
        if not self.weekdays or not all(0 <= d <= 6 for d in self.weekdays):
            raise ValueError("weekdays 必须是 0..6 的非空子集")
        object.__setattr__(
            self, "effective_start", _as_utc(self.effective_start, "effective_start")
        )
        object.__setattr__(
            self, "effective_end", _as_utc(self.effective_end, "effective_end")
        )
        if not self.effective_start < self.effective_end:
            raise ValueError("effective_start 必须早于 effective_end")
        for name, t in (("window_start", self.window_start), ("window_end", self.window_end)):
            if not isinstance(t, time):
                raise TypeError(f"{name} 必须是 datetime.time")
            if t.tzinfo is not None:
                raise ValueError(f"{name} 是本地钟表时间，不应带时区")
            if t.microsecond:
                raise ValueError(f"{name} 精度为 1 秒，不允许微秒")
        if self.window_start == self.window_end:
            raise ValueError("日内窗口起止时刻必须不同")


@dataclass(frozen=True)
class CalendarEntry:
    """日历片段：[start, end) 内获胜活动为 activity_id（None 表示无候选）。"""

    start: datetime
    end: datetime
    activity_id: Optional[int]
