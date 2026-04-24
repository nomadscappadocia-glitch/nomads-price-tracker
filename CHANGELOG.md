# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2025-04-24

### Added

- **MCP Server** — New `hotelrate-mcp` CLI that exposes hotel price comparison as an MCP server, compatible with Claude Code, Claude Desktop, Cursor, and any MCP-compatible AI agent.
  - `hotel_quote` tool — single-hotel real-time multi-platform price lookup
  - `hotel_quote_batch` tool — batch multi-hotel price comparison
  - `list_platforms` tool — list supported OTA platforms and status
  - `health_check` tool — system health and configuration check
- Three transport modes: stdio (default), SSE, streamable-http
- Progress notification bridging from `LiveQuoteService.on_progress` to MCP context
- Claude Code agent metadata (`skills/hotel-meta-live-quote/agents/claude.yaml`)
- MCP server test suite (`tests/test_mcp_server.py`) using in-memory MCP client
- MIT License
- `CONTRIBUTING.md` with development guide and new-platform walkthrough
- This `CHANGELOG.md`

### Changed

- Package renamed from `hotelrate` to `hotelrate-mcp` for PyPI
- Version bumped from 0.1.0 to 0.2.0
- `pyproject.toml` restructured:
  - `mcp[cli]` added to core dependencies
  - `fastapi`/`uvicorn` moved to `[project.optional-dependencies.api]`
  - `sqlalchemy`/`asyncpg`/`apscheduler` moved to `[project.optional-dependencies.worker]`
  - Added `[project.scripts]` entry point for `hotelrate-mcp`
- `SKILL.md` rewritten with MCP tool documentation, parameter tables, output format examples
- `README.md` rewritten as MCP-first open-source documentation
- `.env.example` reorganized with section headers and MCP-focused comments
- `.gitignore` updated with build artifacts (`dist/`, `build/`, `*.egg-info/`)
- `agents/openai.yaml` updated with enhanced MCP-aware prompt

### Unchanged

- All existing collectors (Trip.com, Booking.com, Agoda, Google Hotels)
- `LiveQuoteService` and all business logic
- Pydantic schemas
- FastAPI endpoints
- CLI scripts
- All existing tests (52 tests continue to pass)

## [0.1.0] - 2025-03-01

### Added

- Initial release with 4 OTA platform collectors
- `LiveQuoteService` for multi-platform orchestration
- FastAPI REST API with rate search, best rates, and history endpoints
- APScheduler-based worker for periodic crawling
- CLI tool (`scripts/live_meta_quote.py`) with Rich TUI dashboard
- URL discovery service (search engines + Firecrawl + Playwright)
- URL mapping cache for session persistence
- Demo mode for synthetic data without browser
- Pydantic v2 data models for all domain types
- PostgreSQL storage with SQLAlchemy async
