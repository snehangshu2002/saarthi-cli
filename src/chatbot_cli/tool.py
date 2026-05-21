import os
import subprocess
import sys
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import ArxivAPIWrapper
from langchain_community.tools import ArxivQueryRun
from chatbot_cli.mcp_client import get_mcp_tools

load_dotenv()

SUBAGENT_TOOLS = []

# ── Bash / code runner ─────────────────────────────────────────────────────

PREVIEW_LINES = 10   # lines shown in transcript before Ctrl+T expands

@tool
def bash(command: str) -> str:
    """Run any shell command or code using the terminal shell (bash on Linux/macOS, PowerShell on Windows).
    Use for:
    - Running Python scripts: bash(command='python -c "print(1+1)"')
    - Running JS/Node: bash(command='node -e "console.log(1+1)"')
    - File operations: bash(command='ls -la' or 'dir')
    - Git commands: bash(command='git status')
    - Installing packages, compiling, anything shell-based.
    Always use bash for executing code or system commands.
    Returns stdout + stderr combined. Timeout: 30 seconds.
    """
    import os
    try:
        if os.name == "nt":  # Windows
            # Run using PowerShell to support Unix-like aliases (ls, cat, rm, pwd) and modern cmdlets
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:  # Unix (Linux / macOS)
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


# ── Web Fetcher ────────────────────────────────────────────────────────────

@tool
def fetch_webpage(url: str) -> str:
    """Fetch the text content of a webpage and convert it to clean, readable plain text.
    Use this to read articles, documentation, or search results from a specific URL.
    """
    import requests
    from bs4 import BeautifulSoup
    import urllib.parse
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return f"ERROR: Invalid URL '{url}'. Please make sure to include the scheme (http/https)."
            
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            return response.text[:8000]
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove navigation, headers, footers, and scripts to isolate readable body text
        for element in soup(["script", "style", "head", "iframe", "noscript", "footer", "nav"]):
            element.decompose()
            
        text = soup.get_text(separator="\n")
        
        # Clean up consecutive empty lines
        lines = [line.strip() for line in text.splitlines()]
        chunks = [line for line in lines if line]
        cleaned_text = "\n".join(chunks)
        
        if len(cleaned_text) > 8000:
            cleaned_text = cleaned_text[:8000] + "\n\n... (content truncated for length) ..."
        return cleaned_text
    except Exception as e:
        return f"ERROR fetching '{url}': {e}"


# ── Search / knowledge tools ───────────────────────────────────────────────

ddg_tool    = DuckDuckGoSearchRun()
wiki_tool   = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
arxiv_tool  = ArxivQueryRun(api_wrapper=ArxivAPIWrapper())


# ── Entry point ────────────────────────────────────────────────────────────

@tool
async def delegate_task(agent_role: str, instruction: str, context: str = "") -> str:
    """Delegates a specific sub-task or instruction to a specialized sub-agent.
    The sub-agent will execute the instruction and return its findings, response, or output.
    
    Roles available:
    - 'researcher': Best for searching the web, reading documentation, or gathering information.
    - 'coder': Best for writing, editing, refactoring, or reviewing code.
    - 'debugger': Best for analyzing stack traces, log files, or fixing syntax/runtime errors.
    - 'writer': Best for writing reports, documentation, export summaries, or emails.
    - 'custom': Use this for any other specialized tasks, and describe the role in the instruction.
    
    Returns the sub-agent's response/output.
    """
    from chatbot_cli.ui import ACTIVE_CHAT_UI
    import chatbot_cli.providers as providers
    
    model = providers.ACTIVE_CHAT_MODEL
    if model is None:
        return "ERROR: Active chat model is not initialized."
    
    role_prompts = {
        "researcher": (
            "You are a specialized Researcher sub-agent. Your goal is to gather detailed context, search the web, "
            "read documentation, and compile comprehensive details on the given instruction. "
            "Use the search tools and webpage fetching tools to locate reliable facts and URLs."
        ),
        "coder": (
            "You are a specialized Coder sub-agent. Your goal is to write, edit, refactor, or review code. "
            "Use the bash tool to write files, run tests, compile code, and check results. Ensure the code is robust and correct."
        ),
        "debugger": (
            "You are a specialized Debugger sub-agent. Your goal is to analyze errors, logs, tracebacks, or bugs, "
            "locate the root cause, and formulate/apply fixes. Use the bash tool to run diagnostics, compile, read log files, or execute tests."
        ),
        "writer": (
            "You are a specialized Writer sub-agent. Your goal is to draft summaries, reports, documentation, "
            "or user-facing descriptions. Focus on clarity, structure, and professional formatting."
        ),
        "custom": (
            f"You are a specialized sub-agent tasked with: {instruction}. Use the available tools to complete the task."
        )
    }
    
    system_prompt = role_prompts.get(agent_role.lower(), role_prompts["custom"])
    system_prompt += (
        "\n\nCORE DIRECTIVE: You must aggressively use your tools to perform the task. "
        "Do NOT just explain how to do it. Return a clear, detailed, and direct final answer once the task is complete."
    )
    
    if ACTIVE_CHAT_UI:
        ACTIVE_CHAT_UI.append_block(
            f"\n🤖 [Multi-Agent] Spawning specialized '{agent_role}' sub-agent to handle:\n"
            f"   \"{instruction}\"\n"
        )
        ACTIVE_CHAT_UI.app.invalidate()
        
    sub_tools = SUBAGENT_TOOLS
    model_with_tools = model.bind_tools(sub_tools) if sub_tools else model
    tool_map = {t.name: t for t in sub_tools}
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Instruction: {instruction}\nContext: {context}")
    ]
    
    max_steps = 7
    step = 0
    
    while step < max_steps:
        step += 1
        try:
            response = await model_with_tools.ainvoke(messages)
        except Exception as e:
            err_msg = f"ERROR: Sub-agent model invocation failed: {e}"
            if ACTIVE_CHAT_UI:
                ACTIVE_CHAT_UI.append_block(f"❌ [{agent_role.upper()}] Model error: {e}")
            return err_msg
            
        messages.append(response)
        
        if not response.tool_calls:
            final_content = response.content or "(no response)"
            if ACTIVE_CHAT_UI:
                ACTIVE_CHAT_UI.append_block(
                    f"\n🤖 [{agent_role.upper()}] Sub-agent completed task.\n"
                )
                ACTIVE_CHAT_UI.app.invalidate()
            return final_content
            
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]
            
            from chatbot_cli.streaming import _args_preview
            from chatbot_cli.ui import get_friendly_tool_name
            friendly_name = get_friendly_tool_name(tool_name)
            args_str = _args_preview(tool_args)
            
            approved = True
            if ACTIVE_CHAT_UI and getattr(ACTIVE_CHAT_UI, "tool_approval_mode", "ask") == "ask":
                ACTIVE_CHAT_UI.append_block(
                    f"\n🤖 [{agent_role.upper()}] Requesting approval to run: {friendly_name}({args_str})"
                )
                ACTIVE_CHAT_UI.app.invalidate()
                
                title = f"\n⚠️  Sub-agent [{agent_role.upper()}] requests approval to run:\n   • {friendly_name}({args_str})\n\nProceed?"
                options = [
                    {"label": "Approve & Execute", "value": "approve"},
                    {"label": "Reject & Skip", "value": "reject"},
                ]
                
                ACTIVE_CHAT_UI.start_selection(title, options, "Use Up/Down to choose, then press Enter.")
                try:
                    choice_input = await ACTIVE_CHAT_UI.prompt()
                    if choice_input == "__select__":
                        sel = ACTIVE_CHAT_UI.current_selection()
                        choice = sel.get("value", "reject") if sel else "reject"
                    else:
                        choice = "reject"
                except Exception:
                    choice = "reject"
                finally:
                    ACTIVE_CHAT_UI.cancel_selection()
                    
                if choice == "approve":
                    ACTIVE_CHAT_UI.append_block(f"✅ [{agent_role.upper()}] Tool execution approved.")
                else:
                    ACTIVE_CHAT_UI.append_block(f"❌ [{agent_role.upper()}] Tool execution rejected.")
                    approved = False
            
            if not approved:
                tool_output = "ERROR: Tool execution rejected by the user."
            else:
                if ACTIVE_CHAT_UI:
                    ACTIVE_CHAT_UI.append_block(f"⚙️ [{agent_role.upper()}] Running {friendly_name}({args_str})...")
                    ACTIVE_CHAT_UI.app.invalidate()
                    
                t = tool_map.get(tool_name)
                if t is None:
                    tool_output = f"ERROR: unknown tool '{tool_name}'"
                else:
                    try:
                        if hasattr(t, "ainvoke"):
                            tool_output = await t.ainvoke(tool_args)
                        else:
                            tool_output = t.invoke(tool_args)
                    except Exception as e:
                        tool_output = f"ERROR: {e}"
                        
                if ACTIVE_CHAT_UI:
                    # Clean up whitespace and newlines for a compact UI display
                    snippet = str(tool_output).strip()
                    snippet = " ".join(snippet.split())
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "..."
                    ACTIVE_CHAT_UI.append_block(f"📥 [{agent_role.upper()}] Tool output: {snippet}")
                    ACTIVE_CHAT_UI.app.invalidate()
            
            messages.append(
                ToolMessage(
                    content=str(tool_output),
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )
            
    timeout_msg = f"ERROR: Sub-agent [{agent_role.upper()}] exceeded the maximum number of steps ({max_steps})."
    if ACTIVE_CHAT_UI:
        ACTIVE_CHAT_UI.append_block(f"❌ [{agent_role.upper()}] Max steps exceeded.")
    return timeout_msg

@tool
def save_skill(name: str, description: str, python_code: str) -> str:
    """Save a custom Python script as a dynamically registered tool (skill) in the skills/ directory.
    - name: The name of the skill (e.g. 'greet_user', 'parse_logs'). Use alphanumeric/underscores only.
    - description: A clear, descriptive explanation of what the skill does and what arguments it accepts.
                   This will be used as the docstring for the registered tool.
    - python_code: The Python code content. The script should run as a standalone script.
                   It can accept arguments from command line (sys.argv) or stdin if needed.
    """
    import re
    from chatbot_cli.app_config import SKILLS_DIR
    
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        return "ERROR: Skill name must contain only alphanumeric characters and underscores."
        
    filepath = SKILLS_DIR / f"{name}.py"
    content = f'"""{description}"""\n\n{python_code}\n'
    
    try:
        filepath.write_text(content, encoding="utf-8")
        return f"SUCCESS: Skill '{name}' saved successfully to {filepath}."
    except Exception as e:
        return f"ERROR: Failed to save skill: {e}"

@tool
def save_md_skill(name: str, instructions: str) -> str:
    """Save a text-based prompt or instruction set as a Markdown (.md) skill in the skills/ directory.
    - name: The name of the skill (e.g. 'summarize', 'translate'). Use alphanumeric/underscores only.
    - instructions: The text prompt or instructions the LLM should follow when executing this skill.
    This is best used for prompt-based tasks where you want the LLM to process input natively, rather than using Python.
    """
    import re
    from chatbot_cli.app_config import SKILLS_DIR
    
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        return "ERROR: Skill name must contain only alphanumeric characters and underscores."
        
    filepath = SKILLS_DIR / f"{name}.md"
    
    try:
        filepath.write_text(instructions, encoding="utf-8")
        return f"SUCCESS: MD Skill '{name}' saved successfully to {filepath}."
    except Exception as e:
        return f"ERROR: Failed to save MD skill: {e}"


def make_skill_tool(skill_name: str, docstring: str, filepath: str):
    from langchain_core.tools import StructuredTool
    
    def run_skill(arguments: str = "") -> str:
        """Run the custom skill.
        - arguments: The command line arguments string to pass to the script.
        """
        import sys
        import subprocess
        import shlex
        
        cmd = [sys.executable, filepath]
        if arguments:
            cmd.extend(shlex.split(arguments))
            
        try:
            result = subprocess.run(
                cmd,
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
            return "ERROR: Skill execution timed out after 30 seconds."
        except Exception as e:
            return f"ERROR: {e}"
            
    run_skill.__name__ = f"skill_{skill_name}"
    run_skill.__doc__ = docstring or f"Run custom skill {skill_name}."
    
    return StructuredTool.from_function(
        func=run_skill,
        name=f"skill_{skill_name}",
        description=docstring or f"Run custom skill {skill_name}."
    )


def load_skill_tools() -> list:
    import ast
    from chatbot_cli.app_config import SKILLS_DIR
    
    if not SKILLS_DIR.exists():
        return []
        
    skill_tools = []
    for filepath in SKILLS_DIR.glob("*.py"):
        skill_name = filepath.stem
        try:
            code = filepath.read_text(encoding="utf-8")
            tree = ast.parse(code)
            docstring = ast.get_docstring(tree) or f"Run custom skill {skill_name}."
            tool_obj = make_skill_tool(skill_name, docstring, str(filepath))
            skill_tools.append(tool_obj)
        except Exception as e:
            # Silently log/print loading issue to prevent crashes
            print(f"Error loading skill {skill_name}: {e}")
            
    return skill_tools


_CACHED_BASE_TOOLS = None

async def build_tools():
    global _CACHED_BASE_TOOLS
    from chatbot_cli.settings import load_settings
    
    if _CACHED_BASE_TOOLS is None:
        normal_list = [
            bash,
            calculator,
            ddg_tool,
            wiki_tool,
            arxiv_tool,
            fetch_webpage,
        ]
        
        # Dynamically enable Tavily search if the user has configured an API key for it
        try:
            settings = load_settings()
            api_keys = settings.get("api_keys", {})
            tavily_key = api_keys.get("tavily", "").strip() or os.environ.get("TAVILY_API_KEY", "").strip()
            
            if tavily_key:
                # Set the environment variable so langchain_tavily can find it
                os.environ["TAVILY_API_KEY"] = tavily_key
                from langchain_tavily import TavilySearchResults
                tavily_tool = TavilySearchResults(max_results=3)
                normal_list.append(tavily_tool)
        except Exception:
            # Graceful fallback if anything fails (e.g. settings file corrupt or import fails)
            pass
            
        try:
            mcp_tools = await get_mcp_tools()
            _CACHED_BASE_TOOLS = normal_list + mcp_tools
        except Exception as e:
            if ACTIVE_CHAT_UI:
                ACTIVE_CHAT_UI.append_block(f"[red]Error loading MCP servers:[/] {e}")
            else:
                print(f"Error loading MCP servers: {e}")
            _CACHED_BASE_TOOLS = normal_list
        
    # Dynamically discover and append user-defined skills
    skill_tools = load_skill_tools()
    all_tools = _CACHED_BASE_TOOLS + skill_tools
    
    # Save to global SUBAGENT_TOOLS so subagents can invoke all main tools
    global SUBAGENT_TOOLS
    SUBAGENT_TOOLS = all_tools
    
    return all_tools + [delegate_task, save_skill, save_md_skill]