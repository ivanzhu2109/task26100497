# store-calendar — 门店活动获胜日历库

由上层排期预览工具调用的纯 Python 库：给定单门店的活动配置，计算每个分区在
真实时间轴（UTC 秒级精度）上的获胜活动日历。配置与结果仅保存在进程内存，
不依赖任何外部服务、数据库或文件。

## 环境要求

- Python 3.9+（标准库 `zoneinfo`；Windows 或精简系统需安装 `tzdata` 包）
- 测试：`pytest`

## 业务规则要点

- 每个门店一个 IANA 时区；所有区间左闭右开，精度 1 秒。
- 活动：唯一整数编号、目标分区集合、优先级 1–10、UTC 生效区间、星期集合
  （0=周一…6=周日）、本地日内窗口（起止必须不同）。
- 日内窗口可跨午夜；星期筛选按**窗口开始的本地日期**判断，午夜后的部分仍归前一天。
- 夏令时跳过的本地时刻没有展示机会（不顺延）；重复出现的本地时刻两段都参与竞争；
  偏移变化不保证恰好 1 小时（如 Australia/Lord_Howe 为 30 分钟）。
- 有资格活动中优先级最大者获胜，同优先级取编号最小者；无候选时结果为空。

## 快速开始

```python
from datetime import datetime, time, timezone
from store_calendar import Activity, StoreCalendar

activities = [
    Activity(
        activity_id=10,
        partitions={"entrance", "aisle-3"},
        priority=5,
        effective_start=datetime(2025, 3, 1, tzinfo=timezone.utc),
        effective_end=datetime(2025, 4, 1, tzinfo=timezone.utc),
        weekdays={0, 1, 2, 3, 4, 5, 6},
        window_start=time(2, 10),   # 本地 02:10
        window_end=time(3, 10),     # 本地 03:10；<= 起始时刻表示跨午夜
    ),
]

store = StoreCalendar("America/New_York", activities)

# 1) 单时刻查询：某分区在某个 UTC 时刻的获胜活动编号（无候选返回 None）
winner = store.winner_at("entrance", datetime(2025, 3, 9, 7, 5, tzinfo=timezone.utc))

# 2) 生成完整日历：[start, end) 内无重叠、无遗漏、相邻同结果已合并
cal = store.calendar(
    "entrance",
    datetime(2025, 3, 9, tzinfo=timezone.utc),
    datetime(2025, 3, 10, tzinfo=timezone.utc),
)
for entry in cal:                      # CalendarEntry(start, end, activity_id)
    print(entry.start, "->", entry.end, entry.activity_id)

# 3) 日历范围内的秒级快速查询（二分查找，适合批量预览）
cal.winner_at(datetime(2025, 3, 9, 7, 5, tzinfo=timezone.utc))
```

## API

- `Activity(...)`：活动配置，构造时校验（优先级 1–10、窗口起止不同、
  生效区间非空、UTC 时刻必须带时区等）。
- `StoreCalendar(timezone_name, activities)`：单门店日历；编号重复会报错；
  配置在构造后视为不变。
- `store.winner_at(partition, instant) -> int | None`：单时刻获胜查询。
- `store.calendar(partition, start, end) -> CalendarResult`：完整日历。
- `CalendarResult`：只读序列，元素为 `CalendarEntry(start, end, activity_id)`；
  `activity_id is None` 表示该区间无候选；`cal.winner_at(instant)` 提供
  范围内 O(log n) 查询，越界抛 `ValueError`。

## 测试

```bash
python3 -m pytest tests/ -q
```

- `tests/test_dst.py`：夏令时验收场景（纽约春跳/秋回拨、Lord Howe 30 分钟回拨）。
- `tests/test_overlap.py`：跨午夜窗口与更高/相同优先级、完全遮蔽、生效区间
  落在窗口内部等叠加场景，逐秒对照独立模型，并验证覆盖完整性与最大化合并。
- `tests/test_scale.py`：规模与性能验收（50 活动 × 20 分区 × 10 年）。

## 性能记录（本机 Python 3.14，America/New_York，zone-03 分区）

| 指标 | 要求 | 实测 |
| --- | --- | --- |
| 单分区 10 年日历生成 | < 10 s | ≈ 0.77 s（25048 个片段） |
| 生成峰值内存（tracemalloc） | < 256 MiB | ≈ 9.4 MiB |
| 日历生成后 100000 次时刻查询 | < 3 s | ≈ 0.05 s |

## 实现说明

- `store_calendar/tzutil.py`：以 6 小时步长扫描 + 二分查找定位 UTC 偏移
  转换点（精确到秒），按范围缓存。
- `store_calendar/engine.py`：在相邻转换点之间 `local = utc + offset` 为线性
  映射，据此把每个本地日期的窗口映射为 UTC 区间集合——跳过的本地时刻自然
  留空、重复的本地时刻自然成对；随后扫描线 + 懒删除堆按
  “优先级大者胜、同优先级编号小者胜”裁决并合并相邻同结果片段。
