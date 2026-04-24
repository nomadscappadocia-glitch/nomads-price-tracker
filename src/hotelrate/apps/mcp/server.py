"""FastMCP server for hotelrate — exposes hotel price comparison as MCP tools.

Supports three transports: stdio (default), SSE, and streamable-http.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from hotelrate.apps.mcp.preflight import check_environment
from hotelrate.config import get_settings
from hotelrate.services import LiveQuoteService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Initialize a shared LiveQuoteService instance for the server lifetime."""
    settings = get_settings()
    issues = check_environment(settings)

    # Log error-level issues to stderr so operators see them immediately.
    for issue in issues:
        if issue["level"] == "error":
            logger.warning(
                "Preflight: %s — fix: %s",
                issue["message"],
                issue["fix_command"],
            )

    service = LiveQuoteService(settings)
    yield {"service": service, "settings": settings, "preflight_issues": issues}


mcp = FastMCP(
    "hotelrate",
    instructions=(
        "Real-time multi-platform hotel price comparison. "
        "Query hotel rates across Trip.com, Booking.com, Agoda, and Google Hotels. "
        "Use hotel_quote for single-hotel lookups, hotel_quote_batch for bulk queries, "
        "list_platforms to see supported OTAs, and health_check to verify the system."
    ),
    lifespan=_lifespan,
)

# Register tools from the tools module — import here to trigger @mcp.tool() decorators
from hotelrate.apps.mcp.tools import register_tools  # noqa: E402

register_tools(mcp)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hotelrate-mcp",
        description="Run the hotelrate MCP server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE/HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for SSE/HTTP transport (default: 8080)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for ``hotelrate-mcp``."""
    args = _parse_args(argv)

    run_kwargs: dict = {"transport": args.transport}
    if args.transport in ("sse", "streamable-http"):
        run_kwargs["host"] = args.host
        run_kwargs["port"] = args.port

    mcp.run(**run_kwargs)


if __name__ == "__main__":
    main()
