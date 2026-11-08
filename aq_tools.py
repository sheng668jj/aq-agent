# -*- coding: utf-8 -*-
"""AQ-Agent · 工具层：示例数据生成 + 4 个可被模型调用的工具

数据结构（示例数据，用于课程项目演示）：
    city, date, aqi, pm25, pm10, o3_8h, no2, so2, co
判定口径：AQI > 100 记为超标（对应《环境空气质量标准》二级日均限值口径，仅作演示）
"""
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "aq_sample.csv"
KNOW = BASE / "knowledge" / "aq_standard.md"

CITIES = ["北京", "上海", "广州"]
START = date(2026, 10, 1)
DAYS = 30

# 各城市的"基础污染水平"，用来让示例数据有区分度（广州偏高）
BASELINE = {"北京": 78, "上海": 62, "广州": 96}


def ensure_data():
    """生成示例数据（固定随机种子，保证结果可复现）。"""
    DATA.parent.mkdir(parents=True, exist_ok=True)
    if DATA.exists():
        return DATA
    rnd = random.Random(20261001)
    lines = ["city,date,aqi,pm25,pm10,o3_8h,no2,so2,co"]
    for city in CITIES:
        base = BASELINE[city]
        for i in range(DAYS):
            d = START + timedelta(days=i)
            # 周末略高、逐日小波动，保证既有平稳段也有超标日
            weekend = 12 if d.weekday() >= 5 else 0
            aqi = max(18, int(rnd.gauss(base + weekend, 16)))
            pm25 = max(5, int(aqi * 0.55 + rnd.gauss(0, 6)))
            pm10 = max(10, int(pm25 * 1.55 + rnd.gauss(0, 10)))
            o3 = max(10, int(rnd.gauss(90 if city != "广州" else 118, 22)))
            no2 = max(5, int(rnd.gauss(38, 10)))
            so2 = max(2, int(rnd.gauss(9, 3)))
            co = round(max(0.2, rnd.gauss(0.9, 0.2)), 2)
            lines.append(f"{city},{d.isoformat()},{aqi},{pm25},{pm10},{o3},{no2},{so2},{co}")
    DATA.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return DATA


def load_rows():
    ensure_data()
    rows = []
    for line in DATA.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        c, d, aqi, pm25, pm10, o3, no2, so2, co = line.split(",")
        rows.append({"city": c, "date": d, "aqi": int(aqi), "pm25": int(pm25),
                     "pm10": int(pm10), "o3_8h": int(o3), "no2": int(no2),
                     "so2": int(so2), "co": float(co)})
    return rows


def _err(code, msg):
    return json.dumps({"error": code, "message": msg}, ensure_ascii=False)


# ==================== 工具 1：单日查询 ====================
def query_aqi(city: str, day: str) -> str:
    """查询某城市某一天的空气质量（AQI、主要污染物浓度）。day 格式 YYYY-MM-DD。"""
    if not isinstance(city, str) or not city.strip():
        return _err("INVALID_ARGUMENTS", "city 不能为空")
    if not isinstance(day, str):
        return _err("INVALID_ARGUMENTS", "day 必须形如 2026-10-15")
    try:
        datetime.strptime(day.strip(), "%Y-%m-%d")
    except ValueError:
        return _err("INVALID_ARGUMENTS", "day 必须形如 2026-10-15（支持 2026-10-01~2026-10-30）")
    day = day.strip()
    for r in load_rows():
        if r["city"] == city.strip() and r["date"] == day:
            return json.dumps({"city": r["city"], "date": r["date"], "aqi": r["aqi"],
                               "level": aqi_level(r["aqi"]),
                               "pm25": r["pm25"], "pm10": r["pm10"],
                               "o3_8h": r["o3_8h"], "no2": r["no2"],
                               "so2": r["so2"], "co": r["co"]}, ensure_ascii=False)
    return _err("NOT_FOUND", f"没有 {city} 在 {day} 的数据（可用城市：{'、'.join(CITIES)}，日期范围 2026-10-01~2026-10-30）")


# ==================== 工具 2：区间统计 ====================
def stats_summary(city: str, start: str = "", end: str = "") -> str:
    """统计某城市一段时间内的 AQI 均值、极值、超标天数和主要污染物。
    start/end 可留空表示全部数据（格式 YYYY-MM-DD）。"""
    rows = [r for r in load_rows() if r["city"] == city.strip()]
    if not rows:
        return _err("NOT_FOUND", f"没有 {city} 的数据，可用城市：{'、'.join(CITIES)}")
    if start:
        rows = [r for r in rows if r["date"] >= start]
    if end:
        rows = [r for r in rows if r["date"] <= end]
    if not rows:
        return _err("NOT_FOUND", "该时间范围内没有数据")
    aqis = [r["aqi"] for r in rows]
    exceed = [r for r in rows if r["aqi"] > 100]
    # 主要污染物：用各污染物相对限值的超标倍数的均值判断（限值取二级日均标准）
    limits = {"pm25": 75, "pm10": 150, "o3_8h": 160, "no2": 80, "so2": 150, "co": 4}
    ratio = {k: sum(r[k] / v for r in rows) / len(rows) for k, v in limits.items()}
    main_p = max(ratio, key=ratio.get)
    return json.dumps({
        "city": city, "days": len(rows), "date_from": rows[0]["date"], "date_to": rows[-1]["date"],
        "aqi_avg": round(sum(aqis) / len(aqis), 1), "aqi_max": max(aqis), "aqi_min": min(aqis),
        "exceed_days": len(exceed), "exceed_dates": [r["date"] for r in exceed][:10],
        "main_pollutant": main_p, "main_pollutant_ratio": round(ratio[main_p], 2),
    }, ensure_ascii=False)


# ==================== 工具 3：超标预警 ====================
def detect_exceed(city: str, threshold: int = 100) -> str:
    """列出某城市 AQI 超过阈值的天数清单（默认阈值 100，即国标二级日均口径）。"""
    try:
        threshold = int(threshold)
    except (TypeError, ValueError):
        return _err("INVALID_ARGUMENTS", "threshold 必须是整数")
    rows = [r for r in load_rows() if r["city"] == city.strip()]
    if not rows:
        return _err("NOT_FOUND", f"没有 {city} 的数据")
    bad = [r for r in rows if r["aqi"] > threshold]
    if not bad:
        return json.dumps({"city": city, "threshold": threshold, "count": 0,
                           "message": "该时段内没有超标日"}, ensure_ascii=False)
    worst = max(bad, key=lambda r: r["aqi"])
    return json.dumps({
        "city": city, "threshold": threshold, "count": len(bad),
        "dates": [r["date"] for r in bad],
        "worst": {"date": worst["date"], "aqi": worst["aqi"], "level": aqi_level(worst["aqi"])},
        "advice": "连续超标时建议减少户外活动，敏感人群佩戴防护口罩" if len(bad) >= 3 else "偶发超标，注意关注当日预报",
    }, ensure_ascii=False)


# ==================== 工具 4：知识库检索（简易 RAG） ====================
def search_standard(keyword: str) -> str:
    """在空气质量标准与健康建议知识库中检索相关条目（关键词匹配）。"""
    if not KNOW.exists():
        return _err("NOT_FOUND", "知识库文件缺失")
    if not isinstance(keyword, str) or not keyword.strip():
        return _err("INVALID_ARGUMENTS", "keyword 不能为空")
    kw = keyword.strip()
    chunks = [c.strip() for c in KNOW.read_text(encoding="utf-8").split("\n\n") if c.strip()]
    hits = [c for c in chunks if kw in c]
    if not hits:
        hits = [c for c in chunks if any(x in c for x in ("AQI", "限值", "健康"))][:2]
        if not hits:
            return _err("NOT_FOUND", f"知识库中没有与「{kw}」相关的内容")
    return json.dumps({"keyword": kw, "hits": hits[:3]}, ensure_ascii=False)


# ==================== 辅助 ====================
def aqi_level(aqi: int) -> str:
    for upper, name in ((50, "优"), (100, "良"), (150, "轻度污染"),
                        (200, "中度污染"), (300, "重度污染")):
        if aqi <= upper:
            return name
    return "严重污染"


TOOLS = [
    {"type": "function", "function": {
        "name": "query_aqi",
        "description": "查询某城市某一天的空气质量，返回 AQI、等级与各污染物浓度",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string", "description": "城市名，如 北京"},
                                      "day": {"type": "string", "description": "日期，格式 YYYY-MM-DD"}},
                       "required": ["city", "day"]}}},
    {"type": "function", "function": {
        "name": "stats_summary",
        "description": "统计某城市一段时间内的 AQI 均值、最高最低、超标天数与主要污染物",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string", "description": "城市名"},
                                      "start": {"type": "string", "description": "起始日期 YYYY-MM-DD，可留空"},
                                      "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，可留空"}},
                       "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "detect_exceed",
        "description": "列出某城市 AQI 超过阈值的天数清单与最差一天，用于超标预警",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string", "description": "城市名"},
                                      "threshold": {"type": "integer", "description": "阈值，默认 100"}},
                       "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "search_standard",
        "description": "在空气质量标准与健康建议知识库中检索，回答标准限值、健康影响类问题",
        "parameters": {"type": "object",
                       "properties": {"keyword": {"type": "string", "description": "检索关键词，如 限值、健康、超标"}},
                       "required": ["keyword"]}}},
]

FUNCS = {"query_aqi": query_aqi, "stats_summary": stats_summary,
         "detect_exceed": detect_exceed, "search_standard": search_standard}


def ensure_knowledge():
    KNOW.parent.mkdir(parents=True, exist_ok=True)
    if KNOW.exists():
        return
    KNOW.write_text(
        "# 空气质量标准与健康建议（课程项目知识库）\n\n"
        "AQI 分级：0-50 优，51-100 良，101-150 轻度污染，151-200 中度污染，201-300 重度污染，300 以上严重污染。\n\n"
        "主要污染物二级日均限值：PM2.5 75 μg/m³，PM10 150 μg/m³，O₃ 8 小时滑动平均 160 μg/m³，"
        "NO₂ 80 μg/m³，SO₂ 150 μg/m³，CO 4 mg/m³。\n\n"
        "超标判定口径：本项目把 AQI 大于 100（即超过“良”）视为超标日，用于统计超标天数和预警。\n\n"
        "健康影响：AQI 在 101-150 时，儿童、老年人及心肺疾病患者应减少长时间户外活动；"
        "151-200 时一般人群也应减少户外运动；超过 200 时建议停止户外活动并佩戴防护口罩。\n\n"
        "数据说明：本项目使用按日粒度的多站点模拟数据（3 个城市 × 30 天），字段为 city/date/aqi/"
        "pm25/pm10/o3_8h/no2/so2/co，生成时固定随机种子以保证可复现。\n",
        encoding="utf-8")
