"""门店活动获胜日历库：由上层排期预览工具调用，配置和结果仅保存在进程内存。"""
from .core import StoreCalendar
from .models import CalendarInterval, Campaign

__all__ = ["Campaign", "CalendarInterval", "StoreCalendar"]
