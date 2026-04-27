# hotelrate-mcp

Real-time multi-platform hotel price comparison via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol).

Ask any AI agent to compare hotel prices — it queries **Trip.com**, **Booking.com**, **Agoda**, and **Google Hotels** in parallel and returns normalized results.

Works with **Claude Code**, **Claude Desktop**, **Cursor**, and any MCP-compatible client.

## Features

- **4 OTA platforms** — Trip.com, Booking.com, Agoda, Google Hotels
- **Real-time Playwright crawling** — live prices from actual OTA websites
- **Demo mode** — synthetic data for instant testing, no browser needed
- **Batch queries** — compare multiple hotels concurrently
- **3 transports** — stdio, SSE, streamable-http
- **Interactive setup** — `hotelrate-mcp setup` configures everything in one command
- **Environment diagnostics** — `hotelrate-mcp doctor` checks health at a glance

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/seanbabalala/hotelrate-crawl.git
cd hotelrate-crawl
pip install -e .
```

### 2. Configure

**Option A — Interactive wizard** (recommended):

```bash
hotelrate-mcp setup
```

This walks you through dependency checks, `.env` creation, platform selection, browser login, and session verification. Ctrl+C is safe at any point.

**Option B — Demo mode** (no browser needed):

```bash
cp .env.example .env
# That's it — DEMO_MODE=true by default
```

### 3. Run

```bash
hotelrate-mcp
```

### 4. Verify

```bash
hotelrate-mcp doctor
```

```
  Prerequisites
    ✓ Python ≥3.12 — Python 3.13.3
    ✓ Playwright package — installed
    ✓ Chromium browser — found

  Configuration
    ✓ .env file — exists
    ! Settings — DEMO_MODE=true (set to false for live crawls)

  Platform Profiles
    ✓ Trip.com profile — .playwright/trip-profile/ (16494 files)
    ✓ Booking.com profile — .playwright/booking-profile/ (53375 files)
    ✓ Agoda profile — .playwright/agoda-profile/ (13688 files)

  8 passed  •  0 error(s)  •  1 warning(s)
```

---

## Connect to AI Agents

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hotelrate": {
      "command": "hotelrate-mcp",
      "env": {
        "DEMO_MODE": "true"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add hotelrate -- hotelrate-mcp
```

Then ask naturally:

> "Compare prices for Park Hyatt Tokyo on May 1st across all platforms"

---

## MCP Tools

### `hotel_quote`

Get real-time hotel prices from multiple OTA platforms.

```
hotel_name: "Park Hyatt Tokyo"    # required
checkin:    "2026-05-01"           # default: 7 days from now
checkout:   "2026-05-02"           # default: checkin + 1
city:       "Tokyo"                # helps URL discovery
adults:     2                      # 1-8
children:   0                      # 0-6
currency:   "USD"                  # ISO 4217
platforms:  ["trip", "booking"]    # default: all enabled
locale:     "en-US"                # BCP 47
```

### `hotel_quote_batch`

Query multiple hotels in parallel.

```
hotels: [
  {"hotel_name": "Park Hyatt Tokyo", "city": "Tokyo", "checkin": "2026-05-01", "checkout": "2026-05-02"},
  {"hotel_name": "The Peninsula Shanghai", "city": "Shanghai"}
]
concurrency: 3   # 1-10
```

### `list_platforms`

List supported OTA platforms and their status.

### `health_check`

Check Playwright, Firecrawl, and platform readiness.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `hotelrate-mcp` | Start the MCP server (default) |
| `hotelrate-mcp serve` | Start the MCP server (explicit) |
| `hotelrate-mcp setup` | Interactive first-time setup wizard |
| `hotelrate-mcp doctor` | Environment health diagnostics |

### `hotelrate-mcp setup`

Interactive 7-step wizard: dependency checks → `.env` creation → platform selection → browser login → session verification.

```bash
hotelrate-mcp setup                          # full interactive wizard
hotelrate-mcp setup --platforms trip booking  # specific platforms only
hotelrate-mcp setup --skip-login             # skip browser login (CI)
hotelrate-mcp setup --timeout 600            # adjust login wait time
```

### `hotelrate-mcp doctor`

One-command environment diagnostics.

```bash
hotelrate-mcp doctor          # quick check
hotelrate-mcp doctor --probe  # also verify live sessions via headless browser
hotelrate-mcp doctor --json   # machine-readable JSON output
```

Exit code: `0` = healthy, `1` = errors found.

### Transports

| Transport | Command | Use Case |
|-----------|---------|----------|
| stdio | `hotelrate-mcp` | Claude Code, Claude Desktop |
| SSE | `hotelrate-mcp serve --transport sse` | Web clients, remote access |
| Streamable HTTP | `hotelrate-mcp serve --transport streamable-http` | HTTP-based MCP clients |

> Backward compat: `hotelrate-mcp --transport sse` (without `serve`) still works.

---

## Live Mode Setup

Demo mode works out of the box. For **real OTA prices**, you need to log in to each platform once so browser cookies are saved.

The easiest path:

```bash
hotelrate-mcp setup
```

Or manually:

1. Edit `.env`:
   ```dotenv
   DEMO_MODE=false
   PLAYWRIGHT_BROWSER_CHANNEL=chrome
   ```

2. Install browser: `playwright install chrome`

3. Log in to each platform:
   ```bash
   python scripts/platform_login_warmup.py --platform trip
   python scripts/platform_login_warmup.py --platform booking
   ```

4. Close browser after login. Session cookies are saved to `.playwright/` profiles.

5. Verify: `hotelrate-mcp doctor --probe`

See [docs/live-mode-login.md](docs/live-mode-login.md) for details.

---

## Configuration

All via environment variables or `.env` file. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEMO_MODE` | `true` | `true` = synthetic data, `false` = live Playwright crawls |
| `HEADLESS` | `true` | Show/hide browser windows |
| `GOOGLE_SKIP` | `true` | Skip Google Hotels (slower, often blocked) |
| `FIRECRAWL_ENABLED` | `true` | Enable Firecrawl for URL discovery |
| `DEFAULT_CHECKIN_OFFSET_DAYS` | `7` | Default check-in offset from today |
| `DEFAULT_LENGTH_OF_STAY` | `1` | Default number of nights |

See [`.env.example`](.env.example) for the complete list.

---

## Scripting & API

### CLI Script

```bash
python scripts/live_meta_quote.py \
  --hotel "Park Hyatt Tokyo" --city "Tokyo" \
  --checkin 2026-05-01 --checkout 2026-05-02 \
  --currency USD --out reports/quote.json
```

### REST API (optional)

```bash
pip install -e ".[api]"
uvicorn hotelrate.apps.api.main:app --reload

curl -X POST http://127.0.0.1:8000/meta/quote \
  -H "Content-Type: application/json" \
  -d '{"hotel_name":"Park Hyatt Tokyo","city":"Tokyo","checkin":"2026-05-01","checkout":"2026-05-02"}'
```

---

## Architecture

```
src/hotelrate/
├── apps/
│   ├── mcp/               # MCP Server (main interface)
│   │   ├── server.py      # FastMCP server + CLI routing
│   │   ├── tools.py       # 4 MCP tool definitions
│   │   └── cli/           # setup & doctor subcommands
│   ├── api/               # FastAPI REST endpoints (optional)
│   └── worker/            # APScheduler periodic crawler (optional)
├── collectors/
│   ├── trip/              # Trip.com adapter
│   ├── booking/           # Booking.com adapter
│   ├── agoda/             # Agoda adapter
│   └── google_hotels/     # Google Hotels adapter
├── services/
│   └── live_quote_service.py  # Core orchestration
├── schemas/               # Pydantic models
├── core/                  # Normalizer, matcher, locale helpers
├── infra/                 # Database (SQLAlchemy, optional)
└── config.py              # Settings (pydantic-settings)
```

---

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"

pytest tests/ -v          # 112 tests
ruff check src/ tests/    # lint
hotelrate-mcp doctor      # environment check
```

## Safety Notes

- **Do not commit** `.env`, `.playwright/`, or `reports/*_debug_*` files
- Browser login state is local-only — not portable across machines
- Report security issues via [SECURITY.md](SECURITY.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
