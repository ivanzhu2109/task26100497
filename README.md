# 门店活动获胜日历库

由上层排期预览工具调用的纯 Python 库：计算每个分区在真实时间轴上由哪个活动
占据展示机会。配置和结果仅保存在进程内存，不依赖任何外部服务、数据库或文件。

## 安装与依赖

- Python 3.9+，仅使用标准库（`zoneinfo`，需系统时区数据库；macOS/Linux 自带）。
- 运行测试需要 `pytest`。

## 快速开始

```python
from datetime import datetime, time, timezone
from winner_calendar import Campaign, StoreCalendar

utc = timezone.utc

campaigns = [
    Campaign(
        campaign_id=1,                            # 唯一整数编号
        zones=frozenset({"zone-a", "zone-b"}),    # 目标分区集合
        priority=5,                               # 1 至 10，越大越优先
        effective_from=datetime(2025, 1, 1, tzinfo=utc),  # UTC 生效区间，左闭右开
        effective_to=datetime(2026, 1, 1, tzinfo=utc),
        weekdays=frozenset({0, 1, 2, 3, 4, 5, 6}),        # 0=周一 ... 6=周日
        window_start=time(22, 0),                 # 本地日内窗口，左闭右开
        window_end=time(2, 0),                    # end <= start 表示跨午夜
    ),
]

cal = StoreCalendar("America/New_York", campaigns)

# 生成指定分区在 UTC 范围内的完整日历
segments = cal.generate("zone-a",
                        datetime(2025, 3, 9, tzinfo=utc),
                        datetime(2025, 3, 10, tzinfo=utc))
for seg in segments:
    print(seg.start, "->", seg.end, "winner:", seg.winner)

# 单时刻查询（生成范围内的查询走缓存，O(log n)）
winner = cal.winner_at("zone-a", datetime(2025, 3, 9, 7, 5, tzinfo=utc))
```

## 语义规则

- 所有时间精度为 1 秒，所有区间左闭右开；UTC 时间必须带时区。
- 日内窗口允许跨午夜；星期筛选按窗口**开始**的本地日期判断，午夜后的部分
  仍归前一天。
- 资格由每个 UTC 时刻对应的本地日期与钟表时间决定：夏令时跳过的本地时刻
  没有展示机会（不顺延）；重复出现的本地时刻两段都参与竞争；偏移变化不
  保证恰好 1 小时（如 Australia/Lord_Howe 为 30 分钟）。
- 有资格者中优先级数值最大者获胜；同优先级取编号最小者；无候选时结果为
  空（`winner is None`）。
- `generate` 返回的区间无重叠、无遗漏地覆盖请求范围，相邻且结果相同的
  区间已合并；午夜、时区偏移变化或落败活动的边界不会造成多余分段。

## 性能

在 50 个活动、20 个分区的规模下（实测见 `tests/test_perf.py`）：

- 单分区连续 10 年日历生成约 0.4 秒（要求 10 秒内），峰值内存约 10 MiB
  （要求 256 MiB 内）。
- 生成后 100000 次单时刻查询约 0.04 秒（要求 3 秒内）。

## 测试

```bash
python3 -m pytest tests/ -q
```

- `tests/test_dst.py`：夏令时验收场景（纽约春跳/秋回拨、Lord Howe 30 分钟回拨）。
- `tests/test_competition.py`：跨午夜窗口与多活动竞争，逐秒校验单时刻查询与日历一致。
- `tests/test_edges.py`：落败活动不多余分段、未命中分区、参数校验。
- `tests/test_perf.py`：规模与性能验收（含耗时与峰值内存记录）。
