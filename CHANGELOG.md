# WEEX Sentinel — Changelog

## v4.3.0 — 2026-04-27

### 拓宽国内热点资讯（48h 火爆消息）
- **新增 18 个国内科技/财经媒体域名** 到 `GLOBAL_NEWS_DOMAINS`：
  - 国内科技：虎嗅、钛媒体、雷锋网、量子位、机器之心、IT之家、极客公园、品玩、爱范儿、cnBeta、DoNews、engadget、venturebeat
  - 国内财经：证券时报、中证报、上交所、东方财富、同花顺、搜狐、新浪、腾讯新闻、网易、澎湃、观察者网
  - 创投：IT桔子、创业邦
- **新增 15 条中文火爆查询** 到 `GLOBAL_NEWS_QUERIES`：
  - 国内大厂动态（阿里/腾讯/字节/美团/京东/拼多多）
  - 新能源车（比亚迪/蔚来/小鹏/理想/小米汽车）
  - 国产芯片/半导体突破
  - 国内独角兽/融资/IPO
  - 36氪/钛媒体/虎嗅头条
  - 雷峰网/量子位/机器之心 AI 资讯
  - 北向资金/产业突发
- **新增板块分类 "国内科技"**（`classify_global_news_sector`）：
  - 优先识别国内大厂、新能源车、国产芯片、国内科技媒体关键词
  - 出现在 SKILL.md 第 2 章板块表格
- **集合 limit 提升**：`collect_global_news` 40 → **80**
- **freshness 保持 24h**（每条 query 只搜最近 24h），全局 48h 截断由 `collect_data.py` 统一管理

### SKILL.md 文档同步
- 第 2 章板块表新增"国内科技"行
- 元数据 v4.3.0

---

## v4.2.0 — 2026-04-25

### 时效窗口统一为 48 小时
- `scripts/collect_data.py`: 全局硬截断 72h → **48h**
- `SKILL.md`: 第5.3 币圈八卦从 72h → **48h**（与其他章节统一）
- 数据准确性章节："采集管道丢弃 >72h" → "**>48h**"
- 时效窗口表格：所有板块统一 **48h**

### 时区统一为北京时间（CST = UTC+8）
- 新增 `CST = timezone(timedelta(hours=8))` + `now_cst()` 辅助函数
- `fmt_dt()` 重写：所有 datetime 序列化前先转换到 CST，输出 ISO8601 + `+0800`
- 文件命名时间 (`<HHMMSS>_raw.json`) 使用 CST
- `coverage_period` 字段：`"YYYY-MM-DD HH:MM — YYYY-MM-DD HH:MM CST (UTC+8)"`
- `summary.generated_at` / `generated_at_cst` 使用 CST
- 新增 `summary.timezone = "Asia/Shanghai (UTC+8)"` 字段
- 新增 `summary.freshness_window_hours = 48` 字段
- 财报采集 `today` 字段使用 CST 日期
- 启动日志输出当前北京时间

### SKILL.md 文档同步
- 数据准确性章节新增："**所有时间一律以北京时间（CST = UTC+8）为准**：报告时间、信源时间、行情时间、文件名时间、coverage_period 字段均使用 UTC+8"

### 文件变更
- `scripts/collect_data.py`: now_cst()、CST 常量、fmt_dt 重写、48h 截断、CST 文件名、summary 字段
- `SKILL.md`: 元数据 v4.2.0、5.3 章 48h、时效表格 48h、时区硬规则

---

## v4.1.0 — 2026-04-25

### 改造点 1：跨板块去重（强约束）
- 新增 `src/collectors/dedup.py`，包含三个去重策略：
  - `source_id` 精确匹配
  - URL canonicalization（去除 `utm_*` / `fbclid` / `gclid` / `mc_*` / `ref` / `s` / `t` 等追踪参数）
  - 内容 SimHash 64-bit 指纹，相似度阈值 **0.75**（更松，按需求）
- `collect_data.py` 在采集后、生成 summary 前执行全局去重
- 去重统计写入 `summary["dedup_stats"]`

### 改造点 2：新增 KOL 监控账号
- `src/collectors/x_twitter.py` `KOL_ACCOUNTS` 列表新增：
  - `from:EmberCN` — 余烬，链上巨鲸/加密资讯
  - `from:ai_9684xtpa` — 加密分析师

### 改造点 3：美股财报跟踪
- 新增 `src/collectors/earnings.py`：
  - `STOCK_WATCHLIST` 包含 31 只 WEEX 已上线美股（按发行日排序）
  - 已发布的 BMNR / WFC **完全剔除**，不进入预告/实际任何流程
  - 数据来源：**Exa MCP**（路透/彭博/Yahoo Finance/SeekingAlpha/华尔街见闻 等）
  - 触发逻辑：T-1 日预告（`freshness=week`），T 日实际（`freshness=24h`）
  - 股价涨跌幅口径：**T 日开盘价 → T 日收盘价**百分比变动
- `collect_data.py` 集成财报采集，结果写入 `summary["earnings_section"]`
- SKILL.md 新增"第 6.5 章：美股财报跟踪"输出规范

### 改造点 4：WEEX 引用约束
- `src/collectors/dedup.py` `filter_weex_sources()` 在 collect 阶段硬性过滤所有 weex.com 域名（保留 `platform=weex_official` 用于 Ch6 运营日历）
- `src/collectors/earnings.py` 增加 WEEX 黑名单 URL 检查，财报采集器永不接受 WEEX 自有渠道
- SKILL.md 第 6 章/6.5 章新增 WEEX 信源约束硬规则

### 发布渠道
- **延续原 skill 渠道**，不新增

### 文件变更
- `src/collectors/dedup.py` (新增)
- `src/collectors/earnings.py` (新增)
- `src/collectors/x_twitter.py` (KOL 列表 +2)
- `scripts/collect_data.py` (集成财报采集 + 去重 + WEEX 过滤)
- `SKILL.md` (新增 6.5 章 + WEEX 约束 + 元数据 v4.1.0)
