from langchain_tavily import TavilySearch
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import ArxivAPIWrapper
from langchain_community.tools import ArxivQueryRun
from langchain.chains import LLMMathChain
from langchain.tools import Tool
from langchain_mistralai import ChatMistralAI
from dotenv import load_dotenv
import os
from pathlib import Path
from backend.mcp_client import get_mcp_tools

load_dotenv(Path(__file__).with_name(".env"))
llm_calc = ChatMistralAI(model="devstral-2512")

# Wrap LLMMathChain as a proper Tool so bind_tools() can handle it
_math_chain = LLMMathChain.from_llm(llm=llm_calc, verbose=True)
math_tool = Tool(
    name="Calculator",
    func=_math_chain.run,
    description=(
        "Useful for answering math questions. "
        "Input should be a mathematical expression or word problem."
    ),
)

# 1. Tavily Search (requires TAVILY_API_KEY in .env)
tavily_tool = TavilySearch(max_results=1)

# 2. DuckDuckGo Search (100% Free, no API key needed)
ddg_tool = DuckDuckGoSearchRun()

# 3. Wikipedia (100% Free, great for facts)
wiki_tool = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

# 4. ArXiv (100% Free, great for academic papers)
arxiv_tool = ArxivQueryRun(api_wrapper=ArxivAPIWrapper())


async def build_tools():

    normal_list = [
        tavily_tool,
        ddg_tool,
        wiki_tool,
        arxiv_tool,
        math_tool,
    ]

    mcp_tools = await get_mcp_tools()

    return normal_list + mcp_tools