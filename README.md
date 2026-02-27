# ainewssprite

AI 新闻精灵 -- 每日 AI 领域新闻自动聚合工具。

从多个新闻源（RSS + Hacker News）自动抓取 AI 领域资讯，通过 LLM 生成中文标题、摘要和分类，存入 SQLite 数据库，输出 Markdown 格式日报。支持历史回溯、全文搜索和相似新闻自动合并。

## 功能

- **多源采集** -- RSS 订阅 + Hacker News，配置文件驱动，可自由增删
- **LLM 中文摘要** -- 自动翻译标题、生成中文摘要、智能分类、重要性评分
- **相似新闻合并** -- LLM 判断同一事件的不同报道，合并到同一条记录
- **SQLite 存储** -- 支持历史回溯、全文搜索、增量更新
- **Markdown 日报** -- 按分类组织的每日新闻摘要，路径 `YYYY/MM/YYYYMMDD.md`
- **JSON 导出** -- 按需导出结构化数据供其他工具消费
- **周度主题回顾** -- 按自定义主题筛选最近一周 Top 10 新闻，附带来源链接
- **幂等运行** -- 同一天可多次执行（cron 定时），自动去重、增量更新

## 快速开始

### 安装

```bash
# 克隆项目
git clone <repo-url> && cd ainewssprite

# 安装 (推荐 editable 模式)
pip install -e .
```

### 配置

```bash
# 复制示例配置
cp config.yaml.example config.yaml
```

编辑 `config.yaml` 中的 `llm` 段配置 API，或通过环境变量设置：

```bash
# 环境变量方式
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.openai.com/v1"
```

支持所有 OpenAI 兼容 API：

| Provider | base_url | model 示例 |
|----------|----------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

也可直接在 `config.yaml` 中配置：

```yaml
llm:
  api_key: "your-api-key"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
```

### 运行

```bash
# 完整流程: 采集 → LLM 摘要/分类 → 合并 → 输出 Markdown 日报
python -m ainewssprite

# 仅采集，不调用 LLM (保存英文原文)
python -m ainewssprite --no-llm
```

日报输出到 `data/output/YYYY/MM/YYYYMMDD.md`。

## 使用方式

```
python -m ainewssprite [选项]
```

| 选项 | 说明 |
|------|------|
| `--no-llm` | 跳过 LLM 处理，仅采集原始数据 |
| `--sources NAME [NAME ...]` | 仅运行指定的源，如 `hackernews techcrunch_ai` |
| `--export json\|md\|both` | 从数据库导出指定格式 |
| `--search QUERY` | 全文搜索历史事件 |
| `--top [THEME]` | 回顾最近一周最符合主题的 Top 10 新闻（默认主题: `软件工程师向`） |
| `--date YYYY-MM-DD` | 指定日期（默认今天） |
| `--config PATH` | 指定配置文件路径（默认 `config.yaml`） |
| `--dry-run` | 试运行，不写入文件 |
| `--verbose` | 详细日志输出 |

### 示例

```bash
# 仅采集 Hacker News
python -m ainewssprite --sources hackernews

# 搜索历史新闻
python -m ainewssprite --search "Claude"

# 导出今天的 JSON
python -m ainewssprite --export json

# 查看指定日期的日报
python -m ainewssprite --export md --date 2026-02-25

# 试运行，输出到终端
python -m ainewssprite --dry-run

# 回顾本周最相关的 10 条新闻（默认主题: 软件工程师向）
python -m ainewssprite --top

# 自定义主题回顾
python -m ainewssprite --top "大模型前沿研究"
```

## 定时运行

使用 cron 每 6 小时自动采集：

```bash
# crontab -e
0 */6 * * * cd /path/to/ainewssprite && /path/to/python -m ainewssprite >> /var/log/ainewssprite.log 2>&1
```

同一天多次运行会：
- 自动跳过已抓取的 URL（数据库去重）
- 只处理新增条目
- 覆盖更新当天的 Markdown 日报

## 新闻源

默认配置的采集源：

| 源 | 类型 | 说明 |
|----|------|------|
| TechCrunch AI | RSS | AI 频道全量 |
| The Verge AI | RSS | AI 频道全量 |
| MIT Tech Review | RSS | AI 频道全量 |
| Ars Technica | RSS | 按 AI 关键词过滤 |
| OpenAI Blog | RSS | 官方博客 |
| HuggingFace Blog | RSS | 官方博客 |
| Hacker News | API | Algolia 搜索 AI 关键词，取 points > 50 的热帖 |

### 添加新 RSS 源

编辑 `config.yaml`：

```yaml
rss_sources:
  - name: "my_new_source"
    url: "https://example.com/rss.xml"
    enabled: true
    keywords: []        # 空数组 = 全量采集；填写关键词则按匹配过滤
```

## 数据存储

### SQLite 数据库 (`data/news.db`)

两张核心表：

- **events** -- 新闻事件（合并后的主记录），含中文标题、摘要、分类、标签、重要性
- **articles** -- 原始文章条目，每条关联到一个 event，URL 唯一约束

支持 FTS5 全文搜索索引。

### 输出文件

```
data/output/
└── 2026/
    └── 02/
        └── 20260226.md      # Markdown 日报（默认输出）
```

JSON 通过 `--export json` 按需生成。

## 项目结构

```
ainewssprite/
├── config.yaml.example              # 配置模板 (复制为 config.yaml 使用)
├── pyproject.toml
├── .env.example
├── src/ainewssprite/
│   ├── cli.py                   # CLI 入口与流程编排
│   ├── config.py                # YAML 配置加载
│   ├── db.py                    # SQLite 数据库层
│   ├── models.py                # 数据模型 (frozen dataclass)
│   ├── sources/
│   │   ├── base.py              # NewsSource 抽象基类
│   │   ├── rss.py               # RSS 通用采集器
│   │   ├── hackernews.py        # Hacker News Algolia API
│   │   └── registry.py          # 配置驱动的源注册
│   ├── processing/
│   │   ├── dedup.py             # URL 精确去重
│   │   └── merger.py            # LLM 相似新闻合并
│   ├── llm/
│   │   ├── base.py              # LLMProvider 抽象基类
│   │   ├── openai.py            # OpenAI 兼容 API 实现
│   │   └── summarizer.py        # 批量摘要与分类
│   ├── output/
│   │   ├── markdown.py          # Markdown 日报生成
│   │   └── json_export.py       # JSON 导出
│   └── utils/
│       ├── http.py              # HTTP 客户端 (限速/重试)
│       └── text.py              # 文本清洗 / 哈希
└── data/
    ├── news.db                  # SQLite 数据库
    └── output/                  # 日报输出目录
```

## 数据流

```
config.yaml
    │
    ▼
源注册表 ─── RSS 采集器 ×N ──┐
    │                        ├──→ list[RawNewsItem]
    └─── HN 采集器 ──────────┘
                                    │
                                    ▼
                            URL 去重 (内存 + DB)
                                    │
                                    ▼
                         ┌── LLM 批量摘要/分类 ──┐
                         │                       │
                         │  LLM 相似事件匹配     │
                         │    ├─ 匹配 → 合并更新  │
                         │    └─ 不匹配 → 新建    │
                         └───────────────────────┘
                                    │
                                    ▼
                              写入 SQLite
                                    │
                                    ▼
                           导出 Markdown 日报
```

## 依赖

| 包 | 用途 |
|----|------|
| feedparser | RSS 解析 |
| httpx | HTTP 客户端 |
| pyyaml | YAML 配置 |
| python-dateutil | 日期解析 |
| openai | LLM API (OpenAI 兼容) |

Python >= 3.11，SQLite 为标准库。

## License

MIT
