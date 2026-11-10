# AQ-Agent：用自然语言查空气质量数据

一个最小的**工具编排 Agent**：把 4 个数据工具交给大模型调度，让"北京今天 AQI 多少、超标了几天、这对健康有什么影响"这类问题能一句话问完。

不用 LangChain，不用框架，就是一个 `while` 循环 + Function Calling，代码全部可读。

```
          ┌─────────────────────────────────────────┐
  提问 ──▶│  LLM（tool_choice=auto）                 │
          │    ↓ tool_calls                          │
          │  ┌──────────────────────────────────┐    │
          │  │ query_aqi        单日查询         │    │
          │  │ stats_summary    区间统计         │    │
          │  │ detect_exceed    超标预警         │    │
          │  │ search_standard  知识库检索       │    │
          │  └──────────────────────────────────┘    │
          │    ↓ JSON 结果回灌                        │
          │  继续判断 / 直接作答                       │
          └─────────────────────────────────────────┘
```

## 效果

真实运行记录见 [`docs/demo_run.txt`](docs/demo_run.txt)。摘一段：

> **问**：上海这 30 天的平均 AQI、最高和最低分别是多少？主要污染物是什么？
>
> **答**：平均 AQI **70.4**，最高 **105**（2026-10-12），最低 **34**，超标 1 天；主要污染物是 **O₃ 八小时滑动平均**，占 57% 的天数。
>
> 并主动说明了统计口径（`data_from=2026-10-01`、`date_to=2026-10-30`）、超标判据（AQI>100）、
> 以及"主要污染物"是按首要污染物出现频次统计的——而不是模型自己算的。

5 个演示问题的完整跑批：模型调用 10 次、工具调用 8 次。详见运行记录末尾的统计汇总。

## 关键设计

**1. 工具返回值有统一契约。** 所有工具都返回同一形状的 JSON，出错也返回 JSON：

```json
{ "error": "NOT_FOUND", "message": "没有该城市的数据，可用城市：北京 / 上海 / 广州" }
```

错误码只用三类：`INVALID_ARGUMENTS`（参数不合法）、`NOT_FOUND`（查不到）、`TOOL_NOT_FOUND`（模型调了不存在的工具）。
模型不需要猜异常，看到 `error` 就知道该怎么补救——所以它能自己换个城市重试，而不是把异常堆栈吐给用户。

**2. 数据可复现。** 示例数据用固定随机种子生成（`random.Random(20261001)`），
3 城市 × 30 天，每次跑出来的数字完全一样。任何人 clone 下来跑，结果对得上。

**3. 工具层有测试。** 13 个 pytest 用例覆盖正常查询、日期格式错误、城市不存在、空参数、
统计口径、阈值非法、Schema 与实现一致性。

```
$ pytest -q
.............                    [100%]
13 passed in 0.04s
```

**4. 防编造。** System prompt 明确要求"回答必须基于工具返回的真实数据，不得编造数值"，
涉及标准限值时先检索知识库。演示里模型确实会说明"我没有该字段，因此不做结论性判断"。

## 快速开始

```bash
git clone https://github.com/sheng668jj/aq-agent.git
cd aq-agent
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env      # 填入你的 API Key
```

跑演示（5 个固定问题，结果写入 `outputs/`）：

```bash
python aq_agent.py
```

交互模式：

```bash
python aq_agent.py --chat
```

跑测试（不需要 API Key）：

```bash
pytest -q
```

## 配置

`.env` 里三个变量：

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 必填。任何兼容 OpenAI 接口的服务都行 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 需要支持 Function Calling 的模型 |

> 换其他厂商只要改 `BASE_URL` 和 `MODEL`，代码不用动——用的是 OpenAI SDK 的兼容接口。

## 目录

```
aq-agent/
├── aq_agent.py         # 编排层：Function Calling 循环 + 多轮历史
├── aq_tools.py         # 工具层：示例数据生成 + 4 个工具 + AQI 分级
├── test_aq_tools.py    # 13 个 pytest 用例
├── data/aq_sample.csv  # 示例数据（固定种子生成，3 城市 × 30 天）
├── knowledge/          # 知识库（AQI 分级、限值、健康影响）
└── docs/               # 真实运行记录与测试输出
```

## 局限

- 示例数据是**合成数据**（固定种子 + 高斯扰动），只用于演示流程，不能当真实空气质量结论用。
- 知识库是手写的 AQI 分级与限值摘要，不是完整标准原文。
- 没有做并发、没有做限流、没有做缓存——这是教学/演示项目，不是生产系统。
- 多轮历史是无限增长的，长对话会撞上下文上限，没有做裁剪。

## 数据口径说明

AQI > 100 记为"超标"，对应《环境空气质量标准》二级日均限值口径，仅作演示用途。
O₃ 采用 8 小时滑动平均（`o3_8h`），与常见发布口径一致。
