# hotelrate-mcp

Real-time multi-platform hotel price comparison via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol).

Compare hotel rates across **Trip.com**, **Booking.com**, **Agoda**, and **Google Hotels** — from any AI agent (Claude Code, Claude Desktop, Cursor, etc.) or as a standalone CLI.

## Quick Start — MCP Server

```bash
# Install
pip install -e .
playwright install chromium

# Copy config (demo mode is on by default — no browser needed)
cp .env.example .env

# Run the MCP server (stdio transport)
hotelrate-mcp
```

## Claude Desktop Setup

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

## Claude Code Setup

```bash
claude mcp add hotelrate -- hotelrate-mcp
```

Then in Claude Code:

> "Compare prices for Park Hyatt Tokyo on May 1st across all platforms"

## Available MCP Tools

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

List supported OTA platforms and their status. No parameters.

### `health_check`

Check Playwright, Firecrawl, and platform readiness. No parameters.

## CLI Usage

The project also provides a CLI for direct use:

```bash
# Single hotel quote
python scripts/live_meta_quote.py \
  --hotel "Park Hyatt Tokyo" \
  --city "Tokyo" \
  --checkin 2026-05-01 \
  --checkout 2026-05-02 \
  --currency USD \
  --out reports/live_quote_latest.json

# Batch smoke test (4 hotels across all platforms)
python scripts/live_meta_quote.py \
  --batch-config scripts/live_all_sites_smoke.json \
  --batch-concurrency 2 \
  --enable-google \
  --out reports/smoke.json
```

## API Usage

The FastAPI server is available for HTTP-based access:

```bash
# Install API dependencies
pip install -e ".[api]"

# Start the API
uvicorn hotelrate.apps.api.main:app --reload

# Query
curl -X POST http://127.0.0.1:8000/meta/quote \
  -H "Content-Type: application/json" \
  -d '{"hotel_name":"Park Hyatt Tokyo","city":"Tokyo","checkin":"2026-05-01","checkout":"2026-05-02"}'
```

## Configuration

All configuration is via environment variables (or `.env` file). Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEMO_MODE` | `true` | `true` = synthetic data, no browser. `false` = live Playwright crawls |
| `HEADLESS` | `true` | Show/hide browser windows |
| `GOOGLE_SKIP` | `true` | Skip Google Hotels (slower, fragile) |
| `FIRECRAWL_ENABLED` | `true` | Enable Firecrawl for URL discovery |
| `DEFAULT_CHECKIN_OFFSET_DAYS` | `7` | Default check-in offset from today |
| `DEFAULT_LENGTH_OF_STAY` | `1` | Default number of nights |

See [`.env.example`](.env.example) for the complete list.

### Live Mode Setup

For real hotel prices (not demo data):

1. Set `DEMO_MODE=false` in `.env`
2. Install Playwright: `playwright install chromium`
3. Warm up browser profiles for OTA login walls:

```bash
python scripts/platform_login_warmup.py --platform trip --wait-seconds 300
python scripts/platform_login_warmup.py --platform booking --wait-seconds 300
```

## Architecture

```
src/hotelrate/
├── apps/
│   ├── mcp/        # MCP Server (this project's main interface)
│   │   ├── server.py   # FastMCP server + CLI entry point
│   │   └── tools.py    # 4 MCP tool definitions
│   ├── api/        # FastAPI REST endpoints
│   └── worker/     # APScheduler periodic crawler
├── services/
│   └── live_quote_service.py   # Core orchestration
├── collectors/
│   ├── trip/       # Trip.com adapter
│   ├── booking/    # Booking.com adapter
│   ├── agoda/      # Agoda adapter
│   └── google_hotels/  # Google Hotels adapter
├── schemas/        # Pydantic models
├── core/           # Normalizer, matcher, locale helpers
├── infra/          # Database (SQLAlchemy, optional)
└── config.py       # Settings (pydantic-settings)
```

The MCP server is a thin wrapper (~250 lines) around the existing `LiveQuoteService`. All collectors, schemas, and business logic remain unchanged.

## Development

```bash
# Setup
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
playwright install chromium

# Run tests
pytest tests/ -v

# Lint
ruff check src/

# Run MCP server locally
hotelrate-mcp

# Run with SSE transport
hotelrate-mcp --transport sse --port 8080
```

## Supported Transports

| Transport | Command | Use Case |
|-----------|---------|----------|
| stdio | `hotelrate-mcp` | Claude Code, Claude Desktop |
| SSE | `hotelrate-mcp --transport sse` | Web clients, remote access |
| Streamable HTTP | `hotelrate-mcp --transport streamable-http` | HTTP-based MCP clients |

## License

[MIT](LICENSE)
