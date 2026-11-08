# -*- coding: utf-8 -*-
"""AQ-Agent · 智能体层：把 4 个工具交给大模型编排，支持多轮对话与过程日志

用法：
    演示模式（跑固定 5 个问题，结果写入 outputs/project_aq_run.txt）
        python aq_agent.py
    交互模式
        python aq_agent.py --chat
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aq_tools import FUNCS, TOOLS, ensure_data, ensure_knowledge  # noqa: E402

load_dotenv()

BASE = Path(__file__).resolve().parent
OUT = BASE.parent / "outputs"
LOG = BASE / "logs" / "agent.log"

MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

_api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
if not _api_key:
    raise SystemExit(
        "缺少 DEEPSEEK_API_KEY。\n"
        "请复制 .env.example 为 .env，填入你的 API Key 后再运行：\n"
        "    cp .env.example .env\n"
        "（跑单元测试不需要 Key：pytest -q）"
    )
client = OpenAI(api_key=_api_key,
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))

SYSTEM = ("你是“空气质量智能分析助手”。回答必须基于工具返回的真实数据，不得编造数值；"
          "涉及标准、限值、健康影响时先调用 search_standard 检索知识库；"
          "需要对比多个城市时分别查询后自行计算，并指明依据的日期范围；"
          "工具返回 error 时如实说明，并给出可用城市或日期范围。")

DEMO_QUESTIONS = [
    "北京 2026-10-15 的 AQI 是多少？属于什么等级？主要污染物浓度呢？",
    "上海这 30 天的平均 AQI、最高和最低分别是多少？主要污染物是什么？",
    "广州有几天 AQI 超过 100？分别是哪几天？最差的一天多少？",
    "AQI 超过 100 对健康有什么影响？我应该注意什么？",
    "北京和上海哪个空气质量更好？用平均 AQI 比较一下。",
]


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


class AQAgent:
    """最小可用的工具编排 Agent：多轮历史 + Function Calling 闭环。"""

    def __init__(self, max_turns=6):
        self.max_turns = max_turns
        self.history = [{"role": "system", "content": SYSTEM}]
        self.stats = {"model_calls": 0, "tool_calls": 0, "tokens": 0}

    def ask(self, question, verbose=True):
        self.history.append({"role": "user", "content": question})
        started = time.time()
        for turn in range(1, self.max_turns + 1):
            self.stats["model_calls"] += 1
            resp = client.chat.completions.create(
                model=MODEL, messages=self.history, tools=TOOLS,
                tool_choice="auto", temperature=0)
            if resp.usage:
                self.stats["tokens"] += resp.usage.total_tokens
            msg = resp.choices[0].message
            if not msg.tool_calls:
                self.history.append({"role": "assistant", "content": msg.content or ""})
                cost = time.time() - started
                if verbose:
                    print(f"  [turn {turn}] 直接作答（{cost:.2f}s）")
                log(f"Q={question!r} turn={turn} tool_calls={self.stats['tool_calls']}")
                return msg.content, cost

            self.history.append({"role": "assistant", "content": msg.content or "",
                                 "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                name, raw = tc.function.name, tc.function.arguments or "{}"
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    out = json.dumps({"error": "INVALID_JSON", "message": raw}, ensure_ascii=False)
                else:
                    fn = FUNCS.get(name)
                    out = fn(**args) if fn else json.dumps({"error": "TOOL_NOT_FOUND"})
                self.stats["tool_calls"] += 1
                if verbose:
                    print(f"  [turn {turn}] 工具 {name}({raw})")
                    print(f"            → {out[:150]}")
                self.history.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        return "（达到最大轮次，已强制终止）", time.time() - started


def run_demo():
    ensure_data()
    ensure_knowledge()
    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 78)
    emit("AQ-Agent 演示：空气质量智能分析助手")
    emit("=" * 78)
    agent = AQAgent()
    for i, q in enumerate(DEMO_QUESTIONS, 1):
        emit("")
        emit(f"【问题 {i}】{q}")
        answer, cost = agent.ask(q)
        emit(f"【回答】{answer}")
        emit(f"—— 本次累计：模型调用 {agent.stats['model_calls']} 次，"
             f"工具调用 {agent.stats['tool_calls']} 次，tokens {agent.stats['tokens']}，耗时 {cost:.2f}s")

    emit("")
    emit("=" * 78)
    emit("运行统计汇总")
    emit("=" * 78)
    emit(f"  问题数：{len(DEMO_QUESTIONS)}")
    emit(f"  模型调用次数：{agent.stats['model_calls']}")
    emit(f"  工具调用次数：{agent.stats['tool_calls']}")
    emit(f"  累计 tokens：{agent.stats['tokens']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "project_aq_run.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n已写入运行记录：{OUT / 'project_aq_run.txt'}")


def run_chat():
    ensure_data()
    ensure_knowledge()
    agent = AQAgent()
    print("AQ-Agent 交互模式（输入 exit 退出）")
    while True:
        try:
            q = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in ("exit", "quit", "q"):
            break
        if not q:
            continue
        answer, _ = agent.ask(q, verbose=False)
        print("答：", answer)


if __name__ == "__main__":
    run_chat() if "--chat" in sys.argv else run_demo()
