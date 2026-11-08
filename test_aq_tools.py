# -*- coding: utf-8 -*-
"""AQ-Agent · 工具层单元测试（pytest）

覆盖：正常查询、边界输入、异常输入、统计口径、知识库检索。
运行：.venv\\Scripts\\python.exe -m pytest test_aq_tools.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aq_tools import (FUNCS, TOOLS, aqi_level, detect_exceed, ensure_data,  # noqa: E402
                      ensure_knowledge, query_aqi, search_standard, stats_summary)


def test_data_generated():
    p = ensure_data()
    assert p.exists()
    rows = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(rows) == 1 + 3 * 30, "应为 3 城市 × 30 天 = 90 行数据"


def test_query_normal():
    d = json.loads(query_aqi("北京", "2026-10-15"))
    assert d["city"] == "北京" and d["date"] == "2026-10-15"
    assert isinstance(d["aqi"], int) and d["level"] == aqi_level(d["aqi"])


def test_query_bad_date_format():
    assert json.loads(query_aqi("北京", "2026/10/15"))["error"] == "INVALID_ARGUMENTS"


def test_query_unknown_city():
    d = json.loads(query_aqi("火星", "2026-10-15"))
    assert d["error"] == "NOT_FOUND"


def test_query_empty_city():
    assert json.loads(query_aqi("  ", "2026-10-15"))["error"] == "INVALID_ARGUMENTS"


def test_stats_summary():
    d = json.loads(stats_summary("广州"))
    assert d["days"] == 30
    assert d["aqi_min"] <= d["aqi_avg"] <= d["aqi_max"]
    assert d["exceed_days"] == len(d["exceed_dates"]) or d["exceed_days"] > 10
    assert d["main_pollutant"] in ("pm25", "pm10", "o3_8h", "no2", "so2", "co")


def test_stats_range_filter():
    d = json.loads(stats_summary("上海", "2026-10-01", "2026-10-07"))
    assert d["days"] == 7


def test_detect_exceed_default():
    d = json.loads(detect_exceed("广州"))
    assert d["threshold"] == 100
    assert d["count"] >= 0
    if d["count"]:
        assert d["worst"]["aqi"] > 100


def test_detect_exceed_bad_threshold():
    assert json.loads(detect_exceed("北京", "高"))["error"] == "INVALID_ARGUMENTS"


def test_search_standard_hit():
    ensure_knowledge()
    d = json.loads(search_standard("健康"))
    assert d["hits"] and all("健康" in h or "AQI" in h for h in d["hits"])


def test_search_standard_empty():
    assert json.loads(search_standard(""))["error"] == "INVALID_ARGUMENTS"


def test_tools_schema_consistency():
    """JSON Schema 声明的工具必须与实现一一对应，且都有 description。"""
    declared = {t["function"]["name"] for t in TOOLS}
    assert declared == set(FUNCS)
    for t in TOOLS:
        assert t["function"]["description"]
        assert t["function"]["parameters"]["required"] is not None


def test_aqi_level_boundaries():
    assert aqi_level(50) == "优"
    assert aqi_level(51) == "良"
    assert aqi_level(100) == "良"
    assert aqi_level(101) == "轻度污染"
    assert aqi_level(301) == "严重污染"
