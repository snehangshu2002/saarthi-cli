from langchain_mcp_adapters.client import MultiServerMCPClient
from chatbot_cli.settings import MCP_CONFIG_PATH


async def get_mcp_tools():
    if not MCP_CONFIG_PATH.exists():
        return []
    config = json.load(MCP_CONFIG_PATH.open("r"))
    client = MultiServerMCPClient(config)
    tools = await client.get_tools()
    return tools