#!/usr/bin/env python
"""MCP Server for PDF Parser Tool.

Run this script to start the PDF Parser MCP server:
    python -m src.tools.pdf_parser_server

The server will communicate via stdio using the MCP protocol.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from mcp.server.stdio import stdio_server
from src.tools.pdf_parser import create_pdf_parser_mcp_server


async def main():
    """Main entry point for the PDF Parser MCP server."""
    app = create_pdf_parser_mcp_server()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
