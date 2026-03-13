"""MCP Client Manager.

Provides a unified interface for managing MCP (Model Context Protocol) connections.
Supports both local subprocess-based MCP servers and remote HTTP-based servers.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.

    Attributes:
        name: Unique identifier for the server.
        command: The command to launch the server (e.g., "uv", "python").
        args: Command line arguments for the server.
        env: Optional environment variables for the server.
        url: For HTTP-based servers, the URL to connect to.
        timeout: Request timeout in seconds.
    """

    name: str
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    timeout: float = 30.0


class MCPTool:
    """Wrapper for an MCP tool definition.

    Attributes:
        name: Tool name.
        description: Tool description.
        input_schema: JSON schema for tool arguments.
    """

    def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def to_langchain_tool(self) -> Dict[str, Any]:
        """Convert to LangChain tool format for create_react_agent."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class MCPManager:
    """Manages connections to multiple MCP servers.

    Provides a unified interface for calling tools across all configured servers.
    Handles server lifecycle (connection/disconnection) automatically.

    Example:
        >>> config = MCPServerConfig(name="search", command="uv",
        ...     args=["run", "python", "-m", "src.tools.search.server"])
        >>> manager = MCPManager([config])
        >>> await manager.connect()
        >>> result = await manager.call_tool("search", "search_server", {"query": "..."})
    """

    def __init__(self, server_configs: List[MCPServerConfig]):
        """Initialize the MCP manager with server configurations.

        Args:
            server_configs: List of MCP server configurations.
        """
        self.server_configs = {cfg.name: cfg for cfg in server_configs}
        self.sessions: Dict[str, ClientSession] = {}
        self._tools: Dict[str, List[MCPTool]] = {}
        self._contexts: List[Any] = []

    async def connect(self) -> None:
        """Establish connections to all configured MCP servers.

        Raises:
            RuntimeError: If server configuration is invalid.
        """
        for name, config in self.server_configs.items():
            try:
                if config.url:
                    # HTTP-based SSE connection
                    context = sse_client(url=config.url)
                    read, write = await context.__aenter__()
                    session = ClientSession(read, write)
                    await session.initialize()
                    self.sessions[name] = session
                    logger.info(f"Connected to HTTP MCP server: {name}")

                elif config.command and config.args:
                    # Subprocess-based stdio connection
                    server_params = StdioServerParameters(
                        command=config.command,
                        args=config.args,
                        env=config.env if config.env else None,
                    )
                    context = stdio_client(server_params)
                    read, write = await context.__aenter__()
                    session = ClientSession(read, write)
                    await session.initialize()
                    self.sessions[name] = session
                    self._contexts.append(context)
                    logger.info(f"Connected to stdio MCP server: {name}")

                else:
                    logger.warning(f"Server {name}: no valid connection config provided")

            except Exception as e:
                logger.error(f"Failed to connect to MCP server {name}: {e}")
                raise

        # Cache available tools after connection
        await self._refresh_tools()

    async def _refresh_tools(self) -> None:
        """Refresh the cached tool list from all servers."""
        for name, session in self.sessions.items():
            try:
                tools = await session.list_tools()
                self._tools[name] = [
                    MCPTool(
                        name=t.name,
                        description=t.description,
                        input_schema=t.inputSchema,
                    )
                    for t in tools
                ]
                logger.debug(f"Server {name} has {len(self._tools[name])} tools")
            except Exception as e:
                logger.error(f"Failed to list tools from {name}: {e}")

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """Call a tool on a specific MCP server.

        Args:
            server_name: The name of the configured server.
            tool_name: The name of the tool to call.
            arguments: Tool arguments as a dictionary.

        Returns:
            Parsed result from the tool (typically a dict or list).

        Raises:
            KeyError: If server_name is not configured.
            ValueError: If tool_name is not found on the server.
            MCPError: If the tool call fails.
        """
        if server_name not in self.sessions:
            raise KeyError(f"MCP server not configured: {server_name}")

        session = self.sessions[server_name]

        try:
            result = await session.call_tool(tool_name, arguments)

            # Parse TextContent results
            if result.content:
                parsed_results = []
                for content in result.content:
                    if hasattr(content, "text") and content.text:
                        try:
                            parsed_results.append(json.loads(content.text))
                        except json.JSONDecodeError:
                            parsed_results.append(content.text)
                    else:
                        parsed_results.append(content)

                # Return single result or list
                return parsed_results[0] if len(parsed_results) == 1 else parsed_results

            return None

        except Exception as e:
            logger.error(f"Tool call failed: {server_name}.{tool_name}: {e}")
            raise

    def get_tools(self, server_name: Optional[str] = None) -> List[MCPTool]:
        """Get available tools from servers.

        Args:
            server_name: Optional filter for specific server.
                        If None, returns tools from all servers.

        Returns:
            List of MCPTool objects.
        """
        if server_name:
            return self._tools.get(server_name, [])
        return [tool for tools in self._tools.values() for tool in tools]

    def get_langchain_tools(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tools formatted for LangChain create_react_agent.

        Args:
            server_name: Optional filter for specific server.

        Returns:
            List of tool dictionaries in LangChain format.
        """
        return [tool.to_langchain_tool() for tool in self.get_tools(server_name)]

    async def disconnect(self) -> None:
        """Close all server connections and clean up resources."""
        for name, session in self.sessions.items():
            try:
                # ClientSession doesn't have a close method, just cleanup contexts
                logger.info(f"Disconnected from MCP server: {name}")
            except Exception as e:
                logger.error(f"Error disconnecting from {name}: {e}")

        self.sessions.clear()
        self._tools.clear()

        for context in self._contexts:
            try:
                await context.__aexit__(None, None, None)
            except Exception:
                pass
        self._contexts.clear()

    def __repr__(self) -> str:
        return f"MCPManager(servers={list(self.server_configs.keys())})"


async def load_mcp_config(config_path: str) -> List[MCPServerConfig]:
    """Load MCP server configurations from a JSON or YAML file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        List of MCPServerConfig objects.
    """
    path = Path(config_path)

    if path.suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

    servers = []
    for name, cfg in config_data.get("mcp_servers", {}).items():
        server = MCPServerConfig(
            name=name,
            command=cfg.get("command"),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            url=cfg.get("url"),
            timeout=cfg.get("timeout", 30.0),
        )
        servers.append(server)

    return servers
