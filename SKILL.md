---
name: x-sentiment-monitor
description: "WEEX Sentinel — 加密货币舆情采集与AI情报报告生成。触发词: crypto sentiment, 舆情, 日报, market intelligence, 情感分析, WEEX推文, 加密货币情报, daily report, sentiment analysis, 市场分析, X sentiment"
metadata:
  version: "3.0.0"
  author: HorizonGazer
  homepage: https://github.com/HorizonGazer/x-sentiment-monitor
---

# WEEX Sentinel — Claude Code Skill

## 一句话安装

对 Claude Code 说：

> 帮我安装 x-sentiment-monitor skill，仓库地址 https://github.com/HorizonGazer/x-sentiment-monitor ，克隆到 ~/.claude/skills/x-sentiment-monitor，然后安装 Python 依赖（pip install -e .）、Playwright Firefox（playwright install firefox）、mcporter（npm i -g mcporter）并配置 Exa（mcporter config add exa https://mcp.exa.ai/mcp）。

安装后重启 Claude Code 即可自动识别。

### 前置条件

| 依赖 | 用途 | 版本 |
|------|------|------|
| Python 3.12+ | 运行采集脚本 | `python --version` |
| Node.js | 运行 mcporter | `node --version` |
| Firefox | 提供 X/Twitter 登录 Cookie | 系统安装 |

### 安装后配置（必做）

**X/Twitter Cookie**：在 Firefox 中登录 X/Twitter，保持"记住我"勾选。系统自动读取 Firefox 本地 Cookie（`auth_token` + `ct0`）。

**依赖的 Skill**：需要 [weex-trader](https://github.com/HorizonGazer/weex-trader-skill) 获取实时行情。

## 你是什么

你是加密货币市场情报分析师。你的工作是：
1. 运行 Python 脚本采集 X/Twitter + 权威媒体数据
2. 获取最新行情（通过 weex-trader skill）
3. 阅读采集到的原始数据
4. 撰写商业级情报报告

## 工作流程

**SKILL_DIR** = 本 skill 的安装目录（`~/.claude/skills/x-sentiment-monitor`）

### Step 1: 采集数据

```bash
cd ~/.claude/skills/x-sentiment-monitor
python scripts/collect_data.py
```

脚本会自动：
- 用 Playwright 从 X/Twitter 采集 ~30 条推文（需要 Firefox 已登录 X）
- 用 mcporter MCP 从 Exa 采集 ~60 条权威媒体文章
- 用 VADER 加密词典对全部内容做情感评分
- 输出到 `D:/download/x/x_sentiment_logs/<date>/<time>_raw.json` 和 `_summary.json`

### Step 2: 获取实时行情

使用 weex-trader skill 获取最新数据：

```bash
S=$HOME/.claude/skills/weex-trader/scripts

# 主要币种价格
python $S/weex_spot_api.py ticker --symbol BTCUSDT --pretty
python $S/weex_spot_api.py ticker --symbol ETHUSDT --pretty
python $S/weex_spot_api.py ticker --symbol SOLUSDT --pretty
python $S/weex_spot_api.py ticker --symbol XRPUSDT --pretty
python $S/weex_spot_api.py ticker --symbol BNBUSDT --pretty

# 恐惧贪婪指数
bash $S/crypto.sh fear
```

### Step 3: 读取数据并撰写报告

1. 读取最新的 `_raw.json` 文件（包含全部采集数据）
2. 读取 `_summary.json`（聚合统计）
3. 分析全部信源，识别 8-12 个重大事件
4. 撰写报告并保存到 `D:/download/x/x_sentiment_logs/<date>/ai_report.md`

## 报告撰写规范

### 必须包含的章节

1. **报告头部** — 日期、实时行情（WEEX Spot 价格）、恐惧贪婪指数、信源统计、工具声明
2. **核心结论** — 3-5 句话概括市场格局，给出明确判断
3. **X/Twitter 舆论分析** — 情感量化表格、KOL 声音（带链接）、主题聚类
4. **重大事件深度分析**（8-12 个）— 每个事件包含：时间线、信源引用、数据表格、传导链分析、前景判断
5. **市场总结与展望** — 多空对比表、核心判断（短期/中期/结构性）、关键时间节点
6. **推文草稿**（6 组）— 中文快讯、繁中互动、英文、专题、TG 推送、数据 Thread
7. **运营策略** — 渠道-动作-优先级-时效表
8. **信源索引** — 完整附录

### 信源引用格式

- X/Twitter：正文中用 `[@author](https://x.com/author/status/xxx)` 内联
- Exa 媒体：正文中用 `[媒体名](url)` 内联
- **不要只放在附录末尾，正文中必须有内联链接**

### 推文风格

- 参考 `references/copywriting_materials.txt` 中的 WEEX/Bitget/Binance 风格
- 禁止 AI 味语言（"值得注意的是"、"需要指出"、"众所周知"等）
- 数据驱动，具体数字，不说空话

### 工具声明

报告开头必须声明使用的工具（Playwright、Exa mcporter、VADER、WEEX Trader Skill、Alternative.me），让读者了解数据来源。

## 项目文件

```
x-sentiment-monitor/
├── scripts/collect_data.py       # 运行这个采集数据
├── src/collectors/x_twitter.py   # X/Twitter 采集器（Playwright + Firefox Cookie）
├── src/collectors/exa_search.py  # Exa 搜索（mcporter MCP，免费无 API Key）
├── src/collectors/base.py        # RawMention 统一数据格式
├── src/collectors/symbol_extractor.py  # 符号识别（34 crypto + 7 stock）
├── src/sentiment/vader_crypto.py # VADER 加密定制词典（EN 143 + ZH 80 + Emoji 40）
└── references/copywriting_materials.txt  # 推文风格参考素材
```

## 数据输出位置

```
D:/download/x/x_sentiment_logs/<date>/
├── <time>_raw.json      # 全部原始数据（每条含情感分、事件分类）
├── <time>_summary.json  # 聚合统计
└── ai_report.md         # 你撰写的报告
```

## 注意事项

- 采集前确保 Firefox 已登录 X/Twitter（Cookie 有效）
- mcporter 已配置 Exa（`mcporter config add exa https://mcp.exa.ai/mcp`）
- 报告是你（Claude）直接分析信源写的，不是 Python 模板生成的
- 每次报告都应包含最新实时行情数据
