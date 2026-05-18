import json
from langchain_mcp_adapters.client import MultiServerMCPClient
from chatbot_cli.settings import MCP_CONFIG_PATH


async def get_mcp_tools():
    if not MCP_CONFIG_PATH.exists():
        return []
    config = json.loads(MCP_CONFIG_PATH.read_text())
    servers = config.get("mcpServers", {})
    if not servers:
        return []
    client = MultiServerMCPClient(servers)  # pass servers, not full config
    tools = await client.get_tools()
    return tools