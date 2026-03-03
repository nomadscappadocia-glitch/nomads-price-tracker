# hotelrate

Trip / Booking / Google Hotels / Agoda 多源酒店价格抓取学习项目（MVP）。

## 1) 项目内容

- 后端 API：查询最新价、最低价、历史价。
- Worker：定时拉取多个平台的报价并落库。
- 统一模型：不同平台字段标准化到 `rate_snapshot`。
- 四个平台 Adapter 模板：支持 Demo 模式和 Live 模式扩展点。

## 2) 目录结构

- `src/hotelrate/apps/api/main.py` FastAPI 入口
- `src/hotelrate/apps/worker/main.py` 定时抓取入口
- `src/hotelrate/apps/worker/service.py` 抓取编排逻辑
- `src/hotelrate/collectors/*/collector.py` 各平台 adapter 模板
- `src/hotelrate/core/normalizer.py` 统一字段规范
- `src/hotelrate/infra/models.py` SQLAlchemy 模型
- `src/hotelrate/infra/repository.py` 数据读写
- `sql/schema.sql` 原生 PostgreSQL 建表 SQL
- `scripts/init_db.py` 初始化 + 示例数据

## 3) 快速开始

### 3.1 启动 PostgreSQL

```bash
docker compose up -d
```

### 3.2 安装依赖

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

### 3.3 环境变量

```bash
cp .env.example .env
```

默认 `DEMO_MODE=true`，可直接产出样例价格数据。

### 3.4 初始化数据库

```bash
python scripts/init_db.py
```

### 3.5 启动 worker（定时抓取）

```bash
python -m hotelrate.apps.worker.main
```

### 3.6 启动 API

```bash
uvicorn hotelrate.apps.api.main:app --reload
```

## 4) API 示例

```bash
curl "http://127.0.0.1:8000/rates/search?city=Shanghai&checkin=2026-03-10&checkout=2026-03-11&adults=2&children=0"

curl "http://127.0.0.1:8000/rates/best?city=Shanghai&checkin=2026-03-10&checkout=2026-03-11&adults=2&children=0"

curl "http://127.0.0.1:8000/rates/history/<hotel_id>?checkin=2026-03-10&checkout=2026-03-11&adults=2&children=0"
```

实时多平台报价（新增）：

```bash
curl -X POST "http://127.0.0.1:8000/meta/quote" \
  -H "Content-Type: application/json" \
  -d '{
    "hotel_name":"Atour Hotel Shanghai HuangPu Xintiandi Metro Station",
    "city":"Shanghai",
    "checkin":"2026-03-09",
    "checkout":"2026-03-10",
    "adults":2,
    "children":0,
    "currency":"USD",
    "platforms":["trip","booking","google_hotels","agoda"]
  }'
```

## 5) Live 模式扩展

把 `.env` 中 `DEMO_MODE=false`，然后按目标站点持续微调解析规则（字段经常变化）：

1. 扩大/收敛 `RESPONSE_PATTERNS`
2. 调整 `room_keys/price_keys/tax_keys/currency_keys`
3. 对特殊房型结构增加平台专用解析逻辑
4. 增加错误重试、截图与告警

当前版本已经内置了第一版 Live 骨架：

- 自动抓取 XHR/FETCH JSON 响应（按平台关键词过滤）
- 基于通用字段映射解析 `room + price + tax + currency`
- Trip 已支持 `getHotelRoomListOversea` 结构化解析（`mode=trip_room_list_oversea`）
- 当 XHR 解析不到时，自动尝试 `application/ld+json` 兜底

## 6) 调试 Live Payload（强烈建议先跑）

```bash
python scripts/inspect_live_payloads.py \
  --platform trip \
  --platform-hotel-id 123456 \
  --platform-url \"https://www.trip.com/hotels/detail/?hotelId=123456\" \
  --checkin 2026-03-20 \
  --nights 1
```

可选平台：`trip` / `booking` / `google_hotels` / `agoda`。

如果 `parsed_offers=0`，优先看输出的 payload url 与 keys，再回到对应 collector 的：

- `RESPONSE_PATTERNS`（扩大响应匹配范围）
- `parse_payloads_to_offers(...)` 的 `room_keys/price_keys/tax_keys`（按真实字段微调）

也可以直接跑内置四站点样例：

```bash
python scripts/run_sample_live_urls.py
```

输出里重点看 3 个字段：

- `date_window`：本次实际抓取的入住窗口（脚本会对 Agoda/Booking 自动探测未来可用日期窗口）。
- `structured_offers`：结构化解析成功的报价数量。
- `mode=text_fallback`：该条价格来自页面文本兜底，不是结构化 API 解析结果。

## 7) 一键实时抓取（酒店名 + 日期）

```bash
python scripts/live_meta_quote.py \
  --hotel "Atour Hotel Shanghai HuangPu Xintiandi Metro Station" \
  --city "Shanghai" \
  --checkin 2026-03-09 \
  --checkout 2026-03-10 \
  --currency USD \
  --out reports/live_quote_sample.json
```

可选传入已知 URL（提升命中）：

- `--trip-url`
- `--booking-url`
- `--google-url`
- `--agoda-url`

> 注意：上面这些参数必须传**真实 URL**。像 `<Trip详情页URL>` 这样的占位符字符串会被自动忽略。

## 8) 自动发现详情页 URL（不手填）

先跑候选发现：

```bash
python scripts/discover_platform_urls.py \
  --hotel "Atour Hotel Shanghai HuangPu Xintiandi Metro Station" \
  --city "Shanghai" \
  --checkin 2026-03-16 \
  --checkout 2026-03-17
```

该脚本会输出每个平台 top 候选，并标记 `(detail)` 或 `(search/list)`。

系统本身也会自动做：
- 平台规则 URL 构建
- Yahoo + Brave + DuckDuckGo 多搜索引擎检索
- Firecrawl `map + crawl`
- 搜索页 HTML 反向抽取详情页链接
- Playwright 页面级链接抽取（处理动态 DOM）

并优先选择 detail URL。

## 9) URL 映射缓存（自动记忆）

当某平台本次抓取成功，会把 URL 记到本地缓存，后续同酒店可自动复用：

- `reports/url_mapping_cache.json`

可在 `.env` 修改路径：

```bash
URL_MAPPING_CACHE_PATH=reports/url_mapping_cache.json
```

## 10) Trip 持久会话（解决登录墙/反爬）

1) 先把 `.env` 设为：

```bash
DEMO_MODE=false
PLAYWRIGHT_USER_DATA_DIR_TRIP=/Users/<you>/Desktop/hotelrate/.playwright/trip-profile
PLAYWRIGHT_USER_DATA_DIR_BOOKING=/Users/<you>/Desktop/hotelrate/.playwright/booking-profile
HEADLESS=true
```

2) 首次手动登录（只需一次，后续复用 profile）：

```bash
python scripts/trip_login_warmup.py --wait-seconds 240
```

3) 登录后探测 Trip session 是否可用：

```bash
python scripts/trip_session_probe.py
```

> 如果 Trip 仍跳转到 `/account/signin`，再次执行 warmup，并在浏览器里保持已登录状态后再 probe。
> 新版本在复用持久化 profile 时会自动避免注入额外请求头，减少 Trip 详情页空白/无 payload 的概率。

也可以用通用暖机脚本（支持 booking/agoda/google）：

```bash
python scripts/platform_login_warmup.py --platform trip --wait-seconds 300
python scripts/platform_login_warmup.py --platform booking --wait-seconds 300
python scripts/platform_login_warmup.py --platform agoda --wait-seconds 300
```

> 实测在部分网络环境下，Booking 会长期停在 `pipl_consent` 页。建议先运行 booking warmup 手动同意一次，并复用 `PLAYWRIGHT_USER_DATA_DIR_BOOKING`。
> 新版本会自动识别本地目录：`.playwright/trip-profile`、`.playwright/booking-profile`，即使你没显式配置 `.env` 也会自动复用会话。

## 11) 夜间批量任务

```bash
python scripts/nightly_quote_job.py
python scripts/report_nightly_summary.py
```

输出文件：

- `reports/nightly_quote_report.json`

## 12) URL 规范（已按你给的样例修正）

- `trip.com`：使用 `https://www.trip.com/hotels/detail/`，并更新 `hotelId/checkIn/checkOut/adult/children/curr/barcurr`。
- `agoda.com`：支持完整详情路径（如 `zh-hk/.../hotel/...html`），并更新 `checkIn/los/adults/children/rooms/currencyCode`。
- `booking.com`：支持 `hotel/<country>/<slug>.<locale>.html` 详情页，并更新 `checkin/checkout/group_adults/group_children/no_rooms/selected_currency`。
- `google hotel meta`：改用 `https://www.google.com/travel/search`，并更新 `q/checkin/checkout/adults/children`（保留其它追踪参数）。

如果你在 `hotel_mapping.platform_url` 里直接保存整条详情页 URL（带一堆 query），系统会在每次抓取时只覆盖入住日期和人数等关键参数，其他参数保持不变。

## 13) Firecrawl 集成说明（本地 3002）

已接入 `FIRECRAWL_BASE_URL=http://localhost:3002`：

- `map`：候选 URL 扩展
- `crawl`：候选 URL 深挖与补充

如本地 Firecrawl 暂不可用，系统会自动降级为 DuckDuckGo + 平台规则 URL 生成，不影响主流程执行。

## 14) 运行速度优化（已内置）

- `live_meta_quote` 现在会并行跑多平台，不再串行等待。
- 每个平台会自动截断候选 URL 数量，优先 detail URL。
- `booking/agoda` 的日期探测默认只探测 1 个偏移窗口（`0` 和 `probe-step`），减少卡住概率。
