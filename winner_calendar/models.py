"""数据模型：活动配置与日历区间。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone


@dataclass(frozen=True)
class Campaign:
    """一个门店活动。

    - campaign_id: 唯一整数编号
    - zones: 目标分区集合
    - priority: 1 至 10，数值越大优先级越高
    - effective_from / effective_to: UTC 生效区间，左闭右开
    - weekdays: 星期集合，0=周一 ... 6=周日，按窗口开始的本地日期判断
    - window_start / window_end: 本地日内窗口，左闭右开；end < start 表示跨午夜
    """

    campaign_id: int
    zones: frozenset[str]
    priority: int
    effective_from: datetime
    effective_to: datetime
    weekdays: frozenset[int]
    window_start: time
    window_end: time

    def __post_init__(self) -> None:
        if not 1 <= self.priority <= 10:
            raise ValueError("priority 必须在 1 至 10 之间")
        if not self.zones:
            raise ValueError("zones 不能为空")
        if not self.weekdays or not all(0 <= d <= 6 for d in self.weekdays):
            raise ValueError("weekdays 必须是 0..6 的非空集合")
        if self.window_start == self.window_end:
            raise ValueError("日内窗口起止时刻必须不同")
        for name, value in (("effective_from", self.effective_from), ("effective_to", self.effective_to)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} 必须是带时区的 UTC 时间")
            if value.microsecond:
                raise ValueError(f"{name} 精度为 1 秒，不允许微秒")
        if not self.effective_from < self.effective_to:
            raise ValueError("生效区间必须满足 effective_from < effective_to")
        if self.window_start.microsecond or self.window_end.microsecond:
            raise ValueError("日内窗口精度为 1 秒，不允许微秒")


@dataclass(frozen=True)
class CalendarInterval:
    """日历区间：[start, end) UTC 内的获胜活动编号，无候选时 winner 为 None。"""

    start: datetime
    end: datetime
    winner: int | None
