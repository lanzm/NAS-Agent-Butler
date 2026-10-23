# -*- coding: utf-8 -*-
"""
calendar_helper.py - 纯 Python 轻量级农历、节气与节假日计算器 (零第三方库依赖)
支持 1900-2100 年公历转农历、生肖干支、二十四节气与工作日/法定节假日判定。
"""

import datetime
from typing import Dict, Any, Tuple, Optional

# 1900-2100 农历核心数据（16进制编码月相与闰月）
LUNAR_INFO = [
    0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,
    0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,
    0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,
    0x06566, 0x0d4a0, 0x0ea50, 0x06e95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,
    0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,
    0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,
    0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,
    0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6,
    0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,
    0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x055c0, 0x0ab60, 0x096d5, 0x092e0,
    0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,
    0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,
    0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,
    0x05aa0, 0x076a3, 0x096d0, 0x04bd7, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,
    0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,
    0x14b63
]

GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
SHENGXIAO = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
MONTH_NAMES = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
MONTH_CN = MONTH_NAMES
DAY_NAMES = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"
]
DAY_CN = DAY_NAMES

# 常见节气简易计算参数 (月份基准天)
SOLAR_TERMS_C = [
    (1, 6, "小寒"), (1, 20, "大寒"), (2, 4, "立春"), (2, 19, "雨水"),
    (3, 5, "惊蛰"), (3, 20, "春分"), (4, 5, "清明"), (4, 20, "谷雨"),
    (5, 5, "立夏"), (5, 21, "小满"), (6, 5, "芒种"), (6, 21, "夏至"),
    (7, 7, "小暑"), (7, 23, "大暑"), (8, 7, "立秋"), (8, 23, "处暑"),
    (9, 7, "白露"), (9, 23, "秋分"), (10, 8, "寒露"), (10, 23, "霜降"),
    (11, 7, "立冬"), (11, 22, "小雪"), (12, 7, "大雪"), (12, 22, "冬至")
]


def _get_lunar_year_days(year: int) -> int:
    """计算农历年总天数 (12个月基准天数348天，按大月+1天及闰月天数累加)"""
    total = 348
    code = LUNAR_INFO[year - 1900]
    mask = 0x8000
    for _ in range(12):
        if code & mask:
            total += 1
        mask >>= 1
    # 加上闰月天数
    leap_month = code & 0xf
    if leap_month:
        total += 30 if (code & 0x10000) else 29
    return total


def get_lunar_date(dt: datetime.date) -> Dict[str, Any]:
    """将公历日期转换为农历信息"""
    base_date = datetime.date(1900, 1, 31)
    offset = (dt - base_date).days

    year = 1900
    while year < 2100 and offset > 0:
        year_days = _get_lunar_year_days(year)
        if offset < year_days:
            break
        offset -= year_days
        year += 1

    code = LUNAR_INFO[year - 1900]
    leap_month = code & 0xf
    is_leap = False

    month = 1
    while month <= 12 and offset > 0:
        # 判断本月是否闰月
        if leap_month > 0 and month == (leap_month + 1) and not is_leap:
            is_leap = True
            month -= 1
            month_days = 30 if (code & 0x10000) else 29
        else:
            # 正常月份
            bit_mask = 0x8000 >> (month - 1)
            month_days = 30 if (code & bit_mask) else 29

        if offset < month_days:
            break
        offset -= month_days
        if is_leap and month == leap_month:
            is_leap = False
        month += 1

    day = offset + 1

    # 干支与生肖
    gan_year = GAN[(year - 4) % 10]
    zhi_year = ZHI[(year - 4) % 12]
    sx_year = SHENGXIAO[(year - 4) % 12]

    month_str = f"闰{MONTH_NAMES[month-1]}" if is_leap else f"{MONTH_NAMES[month-1]}"
    day_str = DAY_NAMES[day - 1] if 1 <= day <= len(DAY_NAMES) else f"{day}日"

    return {
        "lunar_year": year,
        "lunar_month": month,
        "lunar_day": day,
        "is_leap": is_leap,
        "text": f"{gan_year}{zhi_year}({sx_year})年 {month_str}月{day_str}"
    }


def get_solar_term(dt: datetime.date) -> str:
    """获取当日或最近的二十四节气"""
    m, d = dt.month, dt.day
    for term_m, term_d, name in SOLAR_TERMS_C:
        if m == term_m and abs(d - term_d) <= 1:
            return name
        elif m == term_m and d < term_d:
            days_left = term_d - d
            if days_left <= 3:
                return f"距{name}还有{days_left}天"
    return ""


def get_holiday_status(dt: datetime.date) -> Dict[str, Any]:
    """判定是否是工作日/周末/法定节假日"""
    weekday = dt.weekday()  # 0~6
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][weekday]
    is_weekend = weekday >= 5

    # 尝试优先导入 chinesecalendar 精准判定国家法定调休
    try:
        import chinese_calendar
        is_workday = chinese_calendar.is_workday(dt)
        is_holiday = chinese_calendar.is_holiday(dt)
        holiday_detail = chinese_calendar.get_holiday_detail(dt)
        desc = holiday_detail[1] if holiday_detail and holiday_detail[1] else ("工作日" if is_workday else "休息日")
        return {
            "weekday": weekday_cn,
            "is_workday": is_workday,
            "day_type": "工作日" if is_workday else "节假日/休息日",
            "detail": desc
        }
    except Exception:
        pass

    # 兜底规则（公历固定法定假 + 常规周末）
    m_d = (dt.month, dt.day)
    holidays_map = {
        (1, 1): "元旦", (5, 1): "劳动节", (5, 2): "劳动节假期", (5, 3): "劳动节假期",
        (10, 1): "国庆节", (10, 2): "国庆节假期", (10, 3): "国庆节假期",
        (10, 4): "国庆节假期", (10, 5): "国庆节假期", (10, 6): "国庆节假期", (10, 7): "国庆节假期"
    }

    if m_d in holidays_map:
        return {
            "weekday": weekday_cn,
            "is_workday": False,
            "day_type": "法定节假日",
            "detail": holidays_map[m_d]
        }

    return {
        "weekday": weekday_cn,
        "is_workday": not is_weekend,
        "day_type": "休息日 (周末)" if is_weekend else "普通工作日",
        "detail": "周末休息" if is_weekend else "工作日"
    }


def get_full_calendar_summary(dt: datetime.date = None) -> Dict[str, Any]:
    """生成当日完整的日历、农历与节假日综合快照"""
    if dt is None:
        dt = datetime.date.today()

    lunar = get_lunar_date(dt)
    term = get_solar_term(dt)
    holiday = get_holiday_status(dt)

    solar_str = dt.strftime(f"%Y年%m月%d日 {holiday['weekday']}")
    summary_parts = [solar_str, f"农历: {lunar['text']}"]
    if term:
        summary_parts.append(f"节气: {term}")
    summary_parts.append(f"状态: {holiday['detail']}")

    return {
        "solar_date": solar_str,
        "lunar_text": lunar["text"],
        "solar_term": term,
        "holiday": holiday,
        "calendar_summary": " · ".join(summary_parts)
    }


def format_datetime_chinese(dt: Optional[datetime.datetime] = None) -> str:
    """统一输出中文日期时间与星期 (如: '2026年10月23日 15:30 星期五')"""
    if dt is None:
        dt = datetime.datetime.now()
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][dt.weekday()]
    return dt.strftime(f"%Y年%m月%d日 %H:%M {weekday_cn}")

