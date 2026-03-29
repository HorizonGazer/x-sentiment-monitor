# WEEX Sentinel

加密货币多源舆情采集与 AI 情报分析系统。

从 X/Twitter 和权威财经媒体自动采集数据，经 VADER 情感分析后，由 Claude AI 生成商业级市场情报日报。

## 一句话安装（Claude Code Skill）

对 Claude Code 说：

> 帮我安装 x-sentiment-monitor skill，仓库地址 https://github.com/HorizonGazer/x-sentiment-monitor ，克隆到 ~/.claude/skills/x-sentiment-monitor，然后安装 Python 依赖（pip install -e .）、Playwright Firefox（playwright install firefox）、mcporter（npm i -g mcporter）并配置 Exa（mcporter config add exa https://mcp.exa.ai/mcp）。

安装后重启 Claude Code，Skill 自动识别。触发词：`舆情`、`日报`、`crypto sentiment`、`market intelligence`。

> 也可以安装到任意目录作为独立项目使用，不限于 Claude Code Skill。

## 架构

```
┌─────────────────────────────────────────────────────┐
│  Step 1: python scripts/collect_data.py             │
│                                                     │
│  X/Twitter (Playwright)  +  Exa (mcporter MCP)      │
│        ~30 条                   ~60 条               │
│             ↓                     ↓                  │
│           VADER 情感分析 (120+ 加密术语)              │
│                     ↓                                │
│         raw.json  +  summary.json                    │
├─────────────────────────────────────────────────────┤
│  Step 2: Claude AI 分析                              │
│                                                     │
│  读取 raw.json → 事件识别 → 商业分析 → ai_report.md  │
└─────────────────────────────────────────────────────┘
```

报告由 Claude 直接分析信源写成，不使用 Python 模板/正则提取。

## 前置条件

| 依赖 | 说明 | 版本要求 |
|------|------|----------|
| Python | 运行采集脚本 | 3.12+ |
| Firefox | 提供 X/Twitter 登录 Cookie | 任意版本 |
| Node.js | 运行 mcporter MCP 客户端 | 18+ |

## 分步安装（如不用一句话命令）

```bash
git clone https://github.com/HorizonGazer/x-sentiment-monitor.git
cd x-sentiment-monitor

pip install -e .              # 3 个依赖：playwright, httpx, vaderSentiment
playwright install firefox    # Playwright Firefox 引擎
npm i -g mcporter             # Exa MCP 命令行客户端
mcporter config add exa https://mcp.exa.ai/mcp   # 配置 Exa 搜索源
```

## 配置

### 1. X/Twitter Cookie（必须）

系统通过读取 Firefox 本地 Cookie 实现 X/Twitter 免 API 采集。

**步骤：**

1. 在 Firefox 浏览器中登录 X/Twitter 账号
2. 登录后随便浏览几个页面（确保 Cookie 写入）
3. **不要关闭 Firefox 的"记住我"选项**

**Cookie 存储位置（自动检测）：**

| 系统    | 路径                                                                         |
| ------- | ---------------------------------------------------------------------------- |
| Windows | `%APPDATA%\Mozilla\Firefox\Profiles\*.default*\cookies.sqlite`             |
| macOS   | `~/Library/Application Support/Firefox/Profiles/*.default*/cookies.sqlite` |
| Linux   | `~/.mozilla/firefox/*.default*/cookies.sqlite`                             |

**必须存在的 Cookie：**

- `auth_token` — X 的身份验证令牌
- `ct0` — CSRF 防护令牌

如果自动检测失败，可在代码中手动指定 Firefox profile 路径：

```python
collector = XTwitterCollector(firefox_profile="/path/to/profile")
```

**验证 Cookie 是否有效：**

```python
from src.collectors.x_twitter import XTwitterCollector
c = XTwitterCollector()
print(c.health_check())
# {'platform': 'x_twitter', 'profile_found': True, 'cookies_valid': True}
```

### 2. Exa 搜索配置（必须）

通过 mcporter 接入 Exa 语义搜索，免费无需 API Key。

```bash
# 验证 mcporter 安装
mcporter config list
# 输出应包含: exa → https://mcp.exa.ai/mcp

# 手动测试搜索
mcporter call 'exa.web_search_exa(query: "bitcoin", numResults: 3)'
```

### 3. 数据输出目录

采集结果默认保存到 `D:/download/x/x_sentiment_logs/<date>/`。如需修改，编辑 `scripts/collect_data.py` 中的 `LOG_ROOT` 变量。

## 使用

### 完整流程

```bash
# Step 1: 采集数据（约 2 分钟）
python scripts/collect_data.py

# Step 2: 在 Claude Code 中让 AI 分析并生成报告
# Claude 会读取最新的 raw.json，分析后生成 ai_report.md
```

### 输出文件

| 文件                    | 内容                                               |
| ----------------------- | -------------------------------------------------- |
| `<time>_raw.json`     | 全部采集数据（每条含情感评分、事件分类、互动数据） |
| `<time>_summary.json` | 聚合统计（symbol 分布、事件聚类、情感概况）        |
| `ai_report.md`        | Claude AI 生成的商业级情报报告                     |

### 配合 Claude Code Skill 使用

本项目设计为 Claude Code Skill，配合以下 Skill 协同工作：

- **weex-trader** — 获取实时行情（BTC/ETH 等价格、恐惧贪婪指数）
- **x-sentiment-monitor**（本项目）— 数据采集与情感分析

## 项目结构

```
x-sentiment-monitor/
├── README.md                 # 本文件
├── SKILL.md                  # Claude Code Skill 定义
├── pyproject.toml            # Python 项目配置（3 个依赖）
├── .gitignore
│
├── scripts/
│   ├── collect_data.py       # 数据采集主脚本
│   └── generate_final_report.py  # 备用报告生成器（legacy）
│
├── src/
│   ├── __init__.py
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py           # RawMention 数据类 + Collector 协议
│   │   ├── x_twitter.py      # Playwright + Firefox Cookie 采集
│   │   ├── exa_search.py     # Exa 语义搜索 (mcporter MCP)
│   │   └── symbol_extractor.py  # 符号识别（34 crypto + 7 stock）
│   └── sentiment/
│       ├── __init__.py
│       └── vader_crypto.py   # VADER + 加密定制词典
│
└── references/
    ├── architecture.md       # 技术架构文档
    ├── customization.md      # 自定义配置指南
    └── copywriting_materials.txt  # WEEX 推文风格素材
```

## 数据源

| 来源           | 方法                                      | 覆盖范围                                                                  | 数量/次 |
| -------------- | ----------------------------------------- | ------------------------------------------------------------------------- | ------- |
| X/Twitter      | Playwright + Firefox Cookie               | crypto/bitcoin/ethereum 等关键词                                          | ~30 条  |
| Exa 权威媒体   | mcporter MCP（免费）                      | CoinDesk · CoinTelegraph · Bloomberg · CNBC · Yahoo Finance 等 20+ 家 | ~60 条  |
| VADER 情感分析 | 加密定制词典（EN 143 + ZH 80 + Emoji 40） | 全部采集内容                                                              | 全量    |

## 常见问题

### X/Twitter 采集返回 0 条

1. **Cookie 过期** — 重新在 Firefox 中登录 X
2. **Firefox profile 未找到** — 确认 Firefox 有 default profile 且包含 `cookies.sqlite`
3. **X 限流** — 等 15-30 分钟重试

### mcporter 搜索失败

```bash
# 检查安装
which mcporter

# 重新配置
mcporter config add exa https://mcp.exa.ai/mcp

# 测试
mcporter call 'exa.web_search_exa(query: "test", numResults: 1)'
```

### 修改搜索关键词

- X/Twitter 搜索词：`src/collectors/x_twitter.py` → `CRYPTO_QUERIES`
- Exa 搜索词：`src/collectors/exa_search.py` → `CRYPTO_QUERIES`
- 权威域名白名单：`src/collectors/exa_search.py` → `AUTHORITY_DOMAINS`
- 垃圾过滤规则：`src/collectors/x_twitter.py` → `SPAM_PATTERNS`

## License

MIT
