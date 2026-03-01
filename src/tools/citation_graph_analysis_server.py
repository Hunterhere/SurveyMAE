#!/usr/bin/env python
"""MCP Server for Citation Graph Analysis Tool.

Run this script to start the Citation Graph Analysis MCP server:
    python -m src.tools.citation_graph_analysis_server
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from mcp.server.stdio import stdio_server
from src.tools.citation_graph_analysis import create_citation_graph_analysis_mcp_server


async def main():
    """Main entry point for the Citation Graph Analysis MCP server."""
    app = create_citation_graph_analysis_mcp_server()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
