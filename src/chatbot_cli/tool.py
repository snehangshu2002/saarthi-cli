from langchain_tavily import TavilySearch
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import ArxivAPIWrapper
from langchain_community.tools import ArxivQueryRun
from langchain_core.tools import tool
from chatbot_cli.mcp_client import get_mcp_tools
import subprocess
import sys
from dotenv import load_dotenv
load_dotenv()


# ── Bash / code runner ─────────────────────────────────────────────────────

PREVIEW_LINES = 10   # lines shown in transcript before Ctrl+T expands

@tool
def bash(command: str) -> str:
    """Run any shell command or code using bash. Use for:
    - Running Python scripts: bash(command='python3 -c "print(1+1)"')
    - Running JS/Node: bash(command='node -e "console.log(1+1)"')
    - File operations: bash(command='ls -la')
    - Git commands: bash(command='git status')
    - Installing packages, compiling, anything shell-based.
    Always use bash for executing code or system commands.
    Returns stdout + stderr combined. Timeout: 30 seconds.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr
        if not output:
            output = "(no output)"
        return output
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 30 seconds."
    except Exception as e:
        return f"ERROR: {e}"


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression.
    Input should be a valid Python math expression like '2 + 2', 'sqrt(16)', '2 ** 10'.
    Supports all Python math module functions.
    """
    import math
    try:
        result = eval(expression, {"__builtins__": {}}, vars(math))
        return str(result)
    except Exception as e:
        return f"ERROR: {e}"


# ── Search / knowledge tools ───────────────────────────────────────────────

tavily_tool = TavilySearch(max_results=1)
ddg_tool    = DuckDuckGoSearchRun()
wiki_tool   = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
arxiv_tool  = ArxivQueryRun(api_wrapper=ArxivAPIWrapper())


# ── Entry point ────────────────────────────────────────────────────────────

async def build_tools():
    normal_list = [
        bash,
        calculator,
        tavily_tool,
        ddg_tool,
        wiki_tool,
        arxiv_tool,
    ]
    mcp_tools = await get_mcp_tools()
    return normal_list + mcp_tools