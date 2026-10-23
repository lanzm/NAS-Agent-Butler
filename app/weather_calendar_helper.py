# -*- coding: utf-8 -*-
"""
weather_calendar_helper.py - 免 Key 实时天气 (wttr.in) 与本地农历/节假日综合服务
支持：
1. Wttr.in 免费免 Key 实时天气与温差查询 (内置中文化与异常兜底)；
2. 本地精准农历换算、干支生肖、二十四节气；
3. 国家法定节假日与调休补班判定。
"""

import os
import re
import json
import logging
import datetime
import urllib.request
import urllib.parse
from typing import Dict, Any

logger = logging.getLogger("feishu-bot.weather")

MONTH_CN = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
DAY_CN = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"
]
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
SHENGXIAO = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

SOLAR_TERMS_C = [
    (1, 6, "小寒"), (1, 20, "大寒"), (2, 4, "立春"), (2, 19, "雨水"),
    (3, 5, "惊蛰"), (3, 20, "春分"), (4, 5, "清明"), (4, 20, "谷雨"),
    (5, 5, "立夏"), (5, 21, "小满"), (6, 5, "芒种"), (6, 21, "夏至"),
    (7, 7, "小暑"), (7, 23, "大暑"), (8, 7, "立秋"), (8, 23, "处暑"),
    (9, 7, "白露"), (9, 23, "秋分"), (10, 8, "寒露"), (10, 23, "霜降"),
    (11, 7, "立冬"), (11, 22, "小雪"), (12, 7, "大雪"), (12, 22, "冬至")
]

WEATHER_ZH_MAP = {
    "sunny": "晴朗",
    "clear": "晴",
    "partly cloudy": "多云",
    "cloudy": "阴天",
    "overcast": "阴",
    "mist": "薄雾",
    "fog": "大雾",
    "patchy rain nearby": "局部阵雨/小雨",
    "patchy rain possible": "局部可能有阵雨",
    "light rain": "小雨",
    "moderate rain": "中雨",
    "heavy rain": "大雨",
    "light drizzle": "毛毛雨",
    "thundery outbreaks possible": "可能有雷雨",
    "thunderstorm": "雷阵雨",
    "smoky haze": "轻度烟霾",
    "haze": "霾",
    "smoke": "烟雾",
    "dust": "扬沙",
    "sand": "沙尘",
}


def get_holiday_countdown(dt: datetime.date = None) -> Dict[str, str]:
    """计算距离周末和下一个主要法定节假日的倒计时天数"""
    if dt is None:
        dt = datetime.date.today()

    # 1. 距离周末
    if dt.weekday() >= 5:
        weekend_msg = "正在周末休假"
    else:
        days_to_weekend = 5 - dt.weekday()
        if days_to_weekend == 1:
            weekend_msg = "明天就是周末"
        else:
            weekend_msg = f"距周末还有{days_to_weekend}天"

    # 2. 距离下一个法定大假（元旦、春节、清明、劳动节、端午、中秋、国庆）
    target_holidays = [
        (datetime.date(dt.year, 1, 1), "元旦"),
        (datetime.date(dt.year, 5, 1), "劳动节"),
        (datetime.date(dt.year, 10, 1), "国庆节"),
        (datetime.date(dt.year + 1, 1, 1), "元旦"),
    ]
    try:
        from lunardate import LunarDate
        c1 = LunarDate(dt.year, 1, 1).to_solar_date()
        c2 = LunarDate(dt.year + 1, 1, 1).to_solar_date()
        qm = datetime.date(dt.year, 4, 4)
        dw = LunarDate(dt.year, 5, 5).to_solar_date()
        zq = LunarDate(dt.year, 8, 15).to_solar_date()
        target_holidays.extend([
            (c1, "春节"), (c2, "春节"),
            (qm, "清明节"), (dw, "端午节"), (zq, "中秋节")
        ])
    except Exception:
        pass

    # 优先查 chinese_calendar 是否有近期法定安排
    cc_found = None
    try:
        import chinese_calendar as cc
        for i in range(1, 60):
            check_d = dt + datetime.timedelta(days=i)
            try:
                if cc.is_holiday(check_d):
                    detail = cc.get_holiday_detail(check_d)
                    if detail and detail[1]:
                        cc_found = (check_d, detail[1])
                        break
            except Exception:
                break
    except Exception:
        pass

    if cc_found:
        diff = (cc_found[0] - dt).days
        holiday_countdown = f"距{cc_found[1]}还有{diff}天"
    else:
        future_holidays = [(d, name) for d, name in target_holidays if d > dt]
        future_holidays.sort(key=lambda x: x[0])
        if future_holidays:
            next_d, next_name = future_holidays[0]
            diff = (next_d - dt).days
            holiday_countdown = f"距{next_name}还有{diff}天"
        else:
            holiday_countdown = ""

    countdown_text = f"{weekend_msg}，{holiday_countdown}" if holiday_countdown else weekend_msg
    return {
        "weekend_countdown": weekend_msg,
        "holiday_countdown": holiday_countdown,
        "countdown_summary": countdown_text
    }


def get_calendar_info(dt: datetime.date = None) -> Dict[str, Any]:
    """计算农历、干支生肖、二十四节气与工作日调休及放假倒计时"""
    if dt is None:
        dt = datetime.date.today()

    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][dt.weekday()]
    is_weekend = dt.weekday() >= 5

    # 1. 农历换算
    lunar_str = "农历未知"
    try:
        from lunardate import LunarDate
        ld = LunarDate.from_solar_date(dt.year, dt.month, dt.day)
        sx = SHENGXIAO[(ld.year - 4) % 12]
        gz_year = f"{GAN[(ld.year - 4) % 10]}{ZHI[(ld.year - 4) % 12]}"
        m_name = f"闰{MONTH_CN[ld.month-1]}" if ld.isLeapMonth else MONTH_CN[ld.month-1]
        d_name = DAY_CN[ld.day - 1] if 1 <= ld.day <= len(DAY_CN) else f"{ld.day}日"
        lunar_str = f"{gz_year}({sx})年 {m_name}月{d_name}"
    except Exception as e:
        logger.debug(f"农历转换降级: {e}")

    # 2. 节气判定
    term_str = ""
    for tm, td, tname in SOLAR_TERMS_C:
        if dt.month == tm and abs(dt.day - td) <= 1:
            term_str = tname
            break
        elif dt.month == tm and dt.day < td and (td - dt.day) <= 3:
            term_str = f"距{tname}还有{td - dt.day}天"
            break

    # 3. 法定节假日与调休判定
    holiday_desc = "普通工作日"
    is_workday = not is_weekend
    try:
        import chinese_calendar as cc
        is_workday = cc.is_workday(dt)
        is_holiday = cc.is_holiday(dt)
        detail = cc.get_holiday_detail(dt)
        if detail and detail[1]:
            holiday_desc = f"{detail[1]}假期" if is_holiday else f"{detail[1]}调休工作日"
        else:
            holiday_desc = "工作日" if is_workday else "周末休息"
    except Exception:
        holiday_desc = "周末休息" if is_weekend else "工作日"

    # 4. 放假倒计时
    countdown = get_holiday_countdown(dt)

    return {
        "solar_date": dt.strftime(f"%Y年%m月%d日 {weekday_cn}"),
        "lunar_date": lunar_str,
        "solar_term": term_str,
        "is_workday": is_workday,
        "holiday_status": holiday_desc,
        "holiday_countdown": countdown["holiday_countdown"],
        "weekend_countdown": countdown["weekend_countdown"],
        "countdown_summary": countdown["countdown_summary"],
        "formatted_calendar": (
            f"{dt.strftime('%Y年%m月%d日')} {weekday_cn} · {lunar_str}"
            + (f" · {term_str}" if term_str else "")
            + f" | {holiday_desc}（{countdown['countdown_summary']}）"
        )
    }


def get_wttr_weather(city: str = None) -> Dict[str, Any]:
    """调用 wttr.in 免 Key API 获取实时天气与今日预报"""
    default_city = os.getenv("DEFAULT_CITY", "北京").strip() or "北京"
    raw_city = (city or default_city).strip()
    
    # 防注入与 SSRF：严格净化城市参数，仅允许汉字、英文字母、数字和横杠空格，最长 30 字符
    query_city = re.sub(r'[^\w\u4e00-\u9fa5\s-]', '', raw_city)[:30].strip() or "北京"
    
    # 常用城市拼音映射或直接使用传入名称
    city_map = {
        "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou",
        "深圳": "Shenzhen", "杭州": "Hangzhou", "成都": "Chengdu", "武汉": "Wuhan"
    }
    city_ascii = city_map.get(query_city, query_city)
    url = f"https://wttr.in/{urllib.parse.quote(city_ascii)}?format=j1&lang=zh"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            curr = data.get("current_condition", [{}])[0]
            today = data.get("weather", [{}])[0]

            temp_c = curr.get("temp_C", "--")
            feels_like = curr.get("FeelsLikeC", temp_c)
            humidity = curr.get("humidity", "--")

            # 天气描述与中文化
            raw_desc = curr.get("lang_zh", [{}])[0].get("value") or curr.get("weatherDesc", [{}])[0].get("value", "")
            condition_zh = WEATHER_ZH_MAP.get(raw_desc.lower().strip(), raw_desc)

            maxtemp = today.get("maxtempC", "--")
            mintemp = today.get("mintempC", "--")

            # 提取全天所有时段最高下雨概率，避免仅取半夜 00:00 数据失真
            hourly = today.get("hourly", [])
            rain_values = [int(h.get("chanceofrain", 0)) for h in hourly if str(h.get("chanceofrain", "")).isdigit()]
            rain_chance = str(max(rain_values)) if rain_values else "0"

            advice_list = []
            try:
                if int(rain_chance) >= 30:
                    advice_list.append("今日有降雨概率，出门建议携带雨具")
                if int(maxtemp) - int(mintemp) >= 8:
                    advice_list.append("早晚温差较大，适时增减衣物")
            except Exception:
                pass

            advice = "；".join(advice_list) if advice_list else "体感舒适，适宜出行"

            return {
                "city": query_city,
                "status": "success",
                "condition": condition_zh,
                "current_temp": f"{temp_c}°C",
                "temp_range": f"{mintemp}°C ~ {maxtemp}°C",
                "feels_like": f"{feels_like}°C",
                "humidity": f"{humidity}%",
                "rain_chance": f"{rain_chance}%",
                "advice": advice,
                "formatted_weather": f"{query_city}今日{condition_zh}，气温 {mintemp}°C ~ {maxtemp}°C (当前 {temp_c}°C)，湿度 {humidity}%，降水概率 {rain_chance}%。{advice}。"
            }
    except Exception as e:
        logger.warning(f"获取 wttr.in 天气失败 ({query_city}): {e}")
        return {
            "city": query_city,
            "status": "fallback",
            "condition": "多云",
            "temp_range": "20°C ~ 27°C",
            "advice": "天气舒适，祝您今日心情愉悦！",
            "formatted_weather": f"{query_city}今日天气舒适，祝您今天工作顺利！"
        }


def get_weather_calendar_summary(city: str = None) -> Dict[str, Any]:
    """生成天气 + 农历日历完整生活汇总"""
    cal = get_calendar_info()
    weather = get_wttr_weather(city)

    return {
        "city": weather.get("city", "北京"),
        "calendar": cal,
        "weather": weather,
        "morning_brief": (
            f"📅 {cal['formatted_calendar']}\n"
            f"🌤️ {weather['formatted_weather']}"
        )
    }
