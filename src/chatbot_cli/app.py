import asyncio
import os
import random
import uuid
import json

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from rich.console import Console
from rich.rule import Rule

from chatbot_cli.app_config import COMMANDS, DATA_DIR, STATUS_MESSAGES, USER_DATA_DIR
from chatbot_cli.chatbot import build_graph
from chatbot_cli.formatting import format_checkpoint_time, render_messages
from chatbot_cli.memory import seed_username
from chatbot_cli.providers import get_models
from chatbot_cli.sessions import list_user_sessions, load_thread_snapshot
from chatbot_cli.settings import first_run_setup, load_settings, settings_complete
from chatbot_cli.streaming import stream_response
from chatbot_cli.ui import ChatUI, create_chat_session
from chatbot_cli.settings import ensure_mcp_config
from chatbot_cli.tool import build_tools
console = Console()

# Version - kept in sync with pyproject.toml
__version__ = "0.1.0"

SAARTHI_LOGO = """
███████╗ █████╗  █████╗ ██████╗ ████████╗██╗  ██╗██╗
██╔════╝██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██║  ██║██║
███████╗███████║███████║██████╔╝   ██║   ███████║██║
╚════██║██╔══██║██╔══██║██╔══██╗   ██║   ██╔══██║██║
███████║██║  ██║██║  ██║██║  ██║   ██║   ██║  ██║██║
╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝
"""

def create_double_boxed_text(lines: list[str]) -> str:
    """Wraps a list of text strings cleanly into a double-lined box structure."""
    if not lines:
        return ""
        
    # Calculate box width based on the longest string
    max_len = max(len(line) for line in lines)
    
    # Double-line box unicode characters
    top_left, top_right = "╔", "╗"
    bottom_left, bottom_right = "╚", "╝"
    horiz, vert = "═", "║"
    
    boxed_lines = []
    
    # Top border line
    boxed_lines.append(f"{top_left}{horiz * (max_len + 2)}{top_right}")
    
    # Content padded lines
    for line in lines:
        padded_line = line.ljust(max_len)
        boxed_lines.append(f"{vert} {padded_line} {vert}")
        
    # Bottom border line
    boxed_lines.append(f"{bottom_left}{horiz * (max_len + 2)}{bottom_right}")
    
    return "\n".join(boxed_lines)
def get_gradient_logo():
    """Maps the logo lines to the invisible gradient markers defined in ui.py"""
    markers = ["\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202b"]
    lines = SAARTHI_LOGO.strip("\n").split("\n")
    styled_lines = []
    
    for i, line in enumerate(lines):
        marker = markers[i % len(markers)]
        styled_lines.append(f"{marker}{line}")
        
    return "\n".join(styled_lines)

def start_new_conversation(user_id: str) -> dict:
    new_thread_id = str(uuid.uuid4())
    return {"configurable": {"user_id": user_id, "thread_id": new_thread_id}}


async def run():
    os.makedirs(DATA_DIR, exist_ok=True)
    session = create_chat_session()
    created = ensure_mcp_config()
    
    # Check for updates in background (non-blocking)
    asyncio.create_task(check_for_updates(__version__))
    
    # console.print(Rule("[bold cyan]Chatbot[/]"))
    tools = await build_tools()
    settings = load_settings()
    if not settings_complete(settings):
        settings = await first_run_setup(session)
    else:
        console.print(f"[dim]Welcome back, [bold]{settings['username']}[/]![/]")

    user_id = settings["username"]
    provider = settings["provider"]
    api_key = settings["api_key"]
    model_name = settings.get("model")
    embedding_provider = settings.get("embedding_provider")
    embedding_model_name = settings.get("embedding_model")
    api_keys = settings.get("api_keys", {})

    try:
        model, embedding_model, dims = get_models(
            provider,
            api_key,
            model_name=model_name,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model_name,
            api_keys=api_keys,
        )
        import chatbot_cli.providers
        chatbot_cli.providers.ACTIVE_CHAT_MODEL = model
    except Exception as e:
        console.print(f"[red]Failed to load provider '{provider}': {e}[/]")
        console.print("[dim]Edit settings.json and restart.[/]")
        return

    async with AsyncSqliteSaver.from_conn_string(f"{DATA_DIR}/checkpoints.db") as checkpointer:
        async with AsyncSqliteStore.from_conn_string(
            f"{DATA_DIR}/memory.db",
            index={"embed": embedding_model, "dims": dims},
        ) as store:
            await store.setup()

            graph_ref = [build_graph(
                model=model,
                checkpointer=checkpointer,
                store=store,
                tools=tools,
            )]
            await seed_username(store, user_id)

            ui = ChatUI()
            ui.set_model_name(model.provider if hasattr(model, 'provider') else provider)
            config = start_new_conversation(user_id)
            gradient_logo = get_gradient_logo()
            ui.append_block(gradient_logo)

            ui.append_block("Welcome back, " + settings["username"] + "!")
            ui.append_block("New session started. Type /help for commands.")
            if created:
                ui.append_block("mcp_config.json created at your data directory. Edit it to add MCP servers.")
            
            async def chat_loop():
                nonlocal config, model, model_name, provider, api_key, embedding_model, dims
                active_selection_mode = None

                while True:
                    try:
                        user_input = (await ui.prompt()).strip()
                    except (KeyboardInterrupt, EOFError):
                        ui.append_block("Bye!")
                        ui.app.exit()
                        break

                    if not user_input:
                        continue

                    if active_selection_mode is not None:
                        mode = active_selection_mode
                        active_selection_mode = None

                        if user_input == "__cancel_select__":
                            ui.append_block("Selection cancelled.")
                            ui.cancel_selection()
                            continue

                        if user_input != "__select__":
                            ui.cancel_selection()
                            continue

                        selected = ui.current_selection()
                        ui.cancel_selection()

                        if selected is None:
                            continue

                        if mode == "resume":
                            config = {
                                "configurable": {
                                    "user_id": user_id,
                                    "thread_id": selected["thread_id"],
                                }
                            }

                            snapshot = await load_thread_snapshot(checkpointer, selected["thread_id"])
                            ui.clear_transcript()
                            if snapshot is not None:
                                messages = snapshot.checkpoint.get("channel_values", {}).get("messages", [])
                                
                                # REBUILD HISTORY USING INTERACTIVE UI COMPONENTS
                                tool_args_map = {}
                                for msg in messages:
                                    if isinstance(msg, HumanMessage):
                                        ui.append_block(f"> {msg.content}")
                                    elif isinstance(msg, AIMessage):
                                        for tc in getattr(msg, "tool_calls", []):
                                            tool_args_map[tc["id"]] = tc["args"]
                                        if msg.content:
                                            ui.start_bot_message()
                                            ui.finish_bot_message(str(msg.content))
                                    elif isinstance(msg, ToolMessage):
                                        name = getattr(msg, "name", "tool")
                                        tid = getattr(msg, "tool_call_id", "")
                                        args = tool_args_map.get(tid, {})
                                        
                                        header = ""
                                        if args:
                                            try:
                                                s = json.dumps(args, ensure_ascii=False)
                                                header = f"({s if len(s)<=80 else s[:80]+'…'})"
                                            except Exception:
                                                pass
                                                
                                        full_output = f"{name}{header}\n{msg.content}"
                                        ui.append_tool_block(name, full_output, in_flight=False)
                                        
                            ui.append_block(
                                "Resumed session: "
                                + format_checkpoint_time(selected["ts"])
                                + f"  ({selected['thread_id'][:8]})"
                            )
                            continue

                        elif mode == "model":
                            new_model_name = selected["value"]
                            
                            if new_model_name == "custom":
                                ui.append_block("To use a custom model, type: /model <name>")
                                continue

                            try:
                                new_model, new_embed, new_dims = get_models(
                                    provider,
                                    api_key,
                                    model_name=new_model_name,
                                    embedding_provider=embedding_provider,
                                    embedding_model=embedding_model_name,
                                    api_keys=api_keys,
                                )
                                model = new_model
                                model_name = new_model_name
                                import chatbot_cli.providers as _prov
                                _prov.ACTIVE_CHAT_MODEL = model
                                graph_ref[0] = build_graph(
                                    model=model,
                                    checkpointer=checkpointer,
                                    store=store,
                                    tools=tools,
                                )
                                saved = load_settings()
                                saved["model"] = new_model_name
                                from chatbot_cli.settings import save_settings
                                save_settings(saved)

                                ui.set_model_name(model.provider if hasattr(model, "provider") else provider)
                                ui.append_block(f"Model switched to: {new_model_name}")
                            except Exception as err:
                                ui.append_block(f"Failed to switch model: {err}")
                            continue
                            
                        elif mode == "skill":
                            skill_name = selected["value"]
                            ui.input.buffer.insert_text(f"/skill run {skill_name} ")
                            ui.app.layout.focus(ui.input)
                            continue

                        elif mode == "mcp":
                            selected_tool_name = selected["value"]
                            tool_details = "No details available."
                            for t in tools:
                                if t.name == selected_tool_name:
                                    desc = getattr(t, "description", "No description")
                                    args_schema = ""
                                    if hasattr(t, "args_schema") and t.args_schema:
                                        try:
                                            import json
                                            schema = t.args_schema.schema()
                                            args_schema = "\n\nArguments:\n" + json.dumps(schema.get("properties", {}), indent=2)
                                        except Exception:
                                            pass
                                    tool_details = desc + args_schema
                                    break
                            ui.append_block(f"MCP Tool: {selected_tool_name}\n\n{tool_details}")
                            continue

                    ui.append_block(f"> {user_input}")

                    if user_input == "/exit":
                        ui.append_block("Bye!")
                        ui.app.exit()
                        break

                    if user_input == "?":
                        lines = [
                            "Keyboard Shortcuts:",
                            "  Ctrl+C      : Exit application (or cancel current action/selection)",
                            "  Ctrl+O      : Expand or collapse tool output blocks",
                            "  Ctrl+G      : Open external editor for long multi-line prompts",
                            "  Ctrl+Space  : Start text highlighting (use arrow keys to expand, Ctrl+C to copy)",
                            "  Ctrl+V      : Paste text (use /image for pasting images)",
                            "  Up/Down     : Browse message history (when input is empty)",
                            "  Tab         : Autocomplete commands",
                            "",
                            "Type /help to see all slash commands."
                        ]
                        ui.append_block("\n".join(lines))
                        continue

                    if user_input == "/help":
                        lines = ["Available commands:"]
                        for cmd, desc in COMMANDS.items():
                            lines.append(f"  {cmd}  -  {desc}")
                            
                        # ---> NEW COPY/PASTE INSTRUCTIONS ADDED HERE <---
                        lines.append("")
                        lines.append("Text Selection & Copying:")
                        lines.append("  • Mouse Method: Hold the Shift key, click and drag your mouse to highlight, and right-click (or press Ctrl+C) to copy.")
                        lines.append("  • Keyboard Method: Press Ctrl+Space to start highlighting. Use your Arrow Keys to select text, then press Ctrl+C to copy it!")
                        lines.append("    (Note: Double-pressing Ctrl+C will still exit the app).")
                        
                        ui.append_block("\n".join(lines))
                        continue

                    if user_input == "/settings" or user_input.startswith("/settings "):
                        parts = user_input.split()
                        if len(parts) > 1 and parts[1] == "edit":
                            async def run_wizard():
                                nonlocal settings, user_id, provider, api_key, model, model_name, embedding_model, dims
                                try:
                                    new_settings = await first_run_setup(session)
                                    settings = new_settings
                                    user_id = settings["username"]
                                    provider = settings["provider"]
                                    api_key = settings["api_key"]
                                    m_name = settings.get("model")
                                    e_prov = settings.get("embedding_provider")
                                    e_mod = settings.get("embedding_model")
                                    a_keys = settings.get("api_keys", {})

                                    new_model, new_embed, new_dims = get_models(
                                        provider,
                                        api_key,
                                        model_name=m_name,
                                        embedding_provider=e_prov,
                                        embedding_model=e_mod,
                                        api_keys=a_keys,
                                    )
                                    
                                    # Hot reload components
                                    model = new_model
                                    import chatbot_cli.providers
                                    chatbot_cli.providers.ACTIVE_CHAT_MODEL = model
                                    embedding_model = new_embed
                                    dims = new_dims
                                    store.index = {"embed": new_embed, "dims": new_dims}
                                    ui.set_model_name(model.provider if hasattr(model, 'provider') else provider)
                                    
                                    # Recompile graph
                                    graph_ref[0] = build_graph(
                                        model=model,
                                        checkpointer=checkpointer,
                                        store=store,
                                        tools=tools,
                                    )
                                    ui.append_block("Settings updated and model reloaded successfully!")
                                except Exception as err:
                                    ui.append_block(f"Error reloading settings: {err}")
                            
                            await run_wizard()
                            continue

                        saved_settings = load_settings()
                        lines = ["Current settings:"]
                        for key, value in saved_settings.items():
                            if key == "api_key":
                                display = value[:6] + "..." + value[-4:] if len(value) > 10 else ("****" if value else "(not set)")
                            elif key == "api_keys":
                                masked_map = {}
                                for pk, pv in value.items():
                                    masked_map[pk] = pv[:6] + "..." + pv[-4:] if len(pv) > 10 else "****"
                                display = str(masked_map)
                            else:
                                display = str(value)
                            lines.append(f"  {key}: {display}")
                        lines.append("\nType '/settings edit' to update settings.")
                        ui.append_block("\n".join(lines))
                        continue

                    if user_input == "/new":
                        config = start_new_conversation(user_id)
                        ui.clear_transcript()
                        
                        # ---> USE THE NEW GRADIENT LOGO <---
                        ui.append_block(get_gradient_logo())
                        
                        ui.append_block("New conversation started. Type /help for commands.")
                        continue

                    if user_input == "/resume":
                        sessions = await list_user_sessions(checkpointer, user_id)
                        if not sessions:
                            ui.append_block("No previous conversations found.")
                        else:
                            active_selection_mode = "resume"
                            ui.start_selection(
                                "Saved conversations:",
                                sessions,
                                "Use Up/Down and Enter to resume. Esc or Ctrl+C cancels.",
                            )
                        continue

                    if user_input == "/export" or user_input.startswith("/export "):
                        parts = user_input.split(maxsplit=1)
                        if len(parts) > 1:
                            filepath = parts[1].strip()
                        else:
                            import datetime
                            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            filepath = f"chat_export_{ts}.txt"

                        try:
                            from pathlib import Path
                            export_path = Path(filepath).resolve()
                            export_path.parent.mkdir(parents=True, exist_ok=True)
                            
                            clean_text = ui.get_clean_transcript_text()
                            export_path.write_text(clean_text, encoding="utf-8")
                            ui.append_block(f"Successfully exported chat to: {export_path}")
                        except Exception as e:
                            ui.append_block(f"Failed to export chat: {e}")
                        continue

                    if user_input == "/plan":
                        ui.plan_mode = not ui.plan_mode
                        status = "enabled" if ui.plan_mode else "disabled"
                        ui.append_block(f"Plan Mode {status}.")
                        continue

                    if user_input == "/mcp":
                        builtin_names = {"bash", "calculator", "tavily_search_results_json", 
                                         "duckduckgo_search", "wikipedia", "arxiv", "fetch_webpage",
                                         "delegate_task", "save_skill", "save_md_skill"}
                        
                        mcp_tools_list = [
                            t for t in tools
                            if t.name not in builtin_names and not t.name.startswith("skill_")
                        ]
                        
                        if not mcp_tools_list:
                            ui.append_block("No MCP servers connected. Edit mcp_config.json to add servers.")
                            continue

                        dialog_values = []
                        for t in mcp_tools_list:
                            desc = (getattr(t, "description", "") or "").splitlines()[0][:60]
                            dialog_values.append({"label": f"[MCP] {t.name}  —  {desc}", "value": t.name})

                        active_selection_mode = "mcp"
                        ui.start_selection(
                            f"Connected MCP Tools ({len(mcp_tools_list)}):",
                            dialog_values,
                            "Use Up/Down to select, Enter to view tool details. Esc cancels."
                        )
                        continue

                    if user_input == "/model" or user_input.startswith("/model "):
                        from chatbot_cli.providers import PROVIDER_MODELS, DEFAULT_MODELS, SUPPORTED_PROVIDERS

                        parts = user_input.split(maxsplit=1)
                        inline_model = parts[1].strip() if len(parts) > 1 else None

                        if inline_model:
                            new_model_name = inline_model
                            # Hot-reload directly
                            try:
                                new_model, new_embed, new_dims = get_models(
                                    provider,
                                    api_key,
                                    model_name=new_model_name,
                                    embedding_provider=embedding_provider,
                                    embedding_model=embedding_model_name,
                                    api_keys=api_keys,
                                )
                                model = new_model
                                model_name = new_model_name
                                import chatbot_cli.providers as _prov
                                _prov.ACTIVE_CHAT_MODEL = model
                                graph_ref[0] = build_graph(
                                    model=model,
                                    checkpointer=checkpointer,
                                    store=store,
                                    tools=tools,
                                )
                                saved = load_settings()
                                saved["model"] = new_model_name
                                from chatbot_cli.settings import save_settings
                                save_settings(saved)

                                ui.set_model_name(model.provider if hasattr(model, "provider") else provider)
                                ui.append_block(f"Model switched to: {new_model_name}")
                            except Exception as err:
                                ui.append_block(f"Failed to switch model: {err}")
                            continue
                        else:
                            # Show inline UI picker instead of full-screen dialog
                            models_list = PROVIDER_MODELS.get(provider, [])
                            dialog_values = [{"label": m, "value": m} for m in models_list]
                            dialog_values.append({"label": "Custom model name...", "value": "custom"})
                            
                            active_selection_mode = "model"
                            ui.start_selection(
                                f"Switch Model — {SUPPORTED_PROVIDERS.get(provider, provider)}",
                                dialog_values,
                                "Use Up/Down to move, Enter to select. Esc cancels."
                            )
                        continue

                    if user_input == "/skills":
                        from chatbot_cli.tool import load_skill_tools
                        from chatbot_cli.app_config import SKILLS_DIR
                        if SKILLS_DIR.exists():
                            skill_files = sorted(list(SKILLS_DIR.glob("*.py")) + list(SKILLS_DIR.glob("*.md")))
                        else:
                            skill_files = []
                        if not skill_files:
                            ui.append_block("No skills saved yet. Ask the AI to create one using save_skill, or run /help for usage.")
                        else:
                            dialog_values = []
                            for sf in skill_files:
                                if sf.suffix == ".py":
                                    try:
                                        import ast
                                        code = sf.read_text(encoding="utf-8")
                                        tree = ast.parse(code)
                                        doc = ast.get_docstring(tree) or "(no description)"
                                        short_doc = doc.splitlines()[0][:70]
                                        dialog_values.append({"label": f"skill_{sf.stem}  —  {short_doc}", "value": sf.stem})
                                    except Exception:
                                        dialog_values.append({"label": f"skill_{sf.stem}  —  (could not read description)", "value": sf.stem})
                                elif sf.suffix == ".md":
                                    try:
                                        import re
                                        content = sf.read_text(encoding="utf-8").strip()
                                        content_no_fm = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
                                        
                                        desc = ""
                                        fm_match = re.match(r"^---\n(.*?)\n---", content, flags=re.DOTALL)
                                        if fm_match:
                                            for line in fm_match.group(1).split('\n'):
                                                if line.startswith("description:"):
                                                    desc = line.split(":", 1)[1].strip()
                                                    if desc == "|":
                                                        desc = ""
                                                    break
                                                    
                                        if not desc:
                                            for line in content_no_fm.split('\n'):
                                                line = line.strip()
                                                if line and not line.startswith('---'):
                                                    desc = line.lstrip('#').strip()
                                                    break
                                                    
                                        desc = desc or "(no description)"
                                        short_doc = desc[:70] + ("..." if len(desc) > 70 else "")
                                        dialog_values.append({"label": f"skill_{sf.stem} [MD] — {short_doc}", "value": sf.stem})
                                    except Exception:
                                        dialog_values.append({"label": f"skill_{sf.stem} [MD]", "value": sf.stem})
                            
                            active_selection_mode = "skill"
                            ui.start_selection(
                                f"Saved skills ({len(skill_files)}):",
                                dialog_values,
                                "Use Up/Down to select a skill to run, Enter to select. Esc cancels."
                            )
                        continue

                    if user_input.startswith("/skill ") or user_input.startswith("/skills "):
                        parts = user_input.split(maxsplit=2)
                        subcommand = parts[1] if len(parts) > 1 else ""

                        if subcommand == "run":
                            if len(parts) < 3:
                                ui.append_block("Usage: /skill run <name> [args...]")
                                continue
                            rest = parts[2]
                            run_parts = rest.split(maxsplit=1)
                            skill_name = run_parts[0]
                            if skill_name.endswith(".py") or skill_name.endswith(".md"):
                                skill_name = skill_name[:-3]
                            skill_args = run_parts[1] if len(run_parts) > 1 else ""

                            from chatbot_cli.app_config import SKILLS_DIR
                            skill_py = SKILLS_DIR / f"{skill_name}.py"
                            skill_md = SKILLS_DIR / f"{skill_name}.md"

                            if skill_py.exists():
                                import subprocess
                                import sys
                                cmd = [sys.executable, str(skill_py)]
                                try:
                                    # Pass the arguments via stdin to preserve all formatting and avoid command line limits
                                    result = subprocess.run(cmd, input=skill_args, capture_output=True, text=True, timeout=30)
                                    output = (result.stdout or "") + (result.stderr or "")
                                    # Trim the output for display
                                    ui.append_block(f"skill_{skill_name} output:\n{output.strip() or '(no output)'}")
                                except subprocess.TimeoutExpired:
                                    ui.append_block(f"Skill '{skill_name}' timed out after 30 seconds.")
                                except Exception as e:
                                    ui.append_block(f"Error running skill '{skill_name}': {e}")
                                continue
                            elif skill_md.exists():
                                try:
                                    skill_content = skill_md.read_text(encoding="utf-8")
                                    user_input = f"Skill context/instructions:\n<skill_prompt>\n{skill_content}\n</skill_prompt>\n\nPlease apply the skill instructions above to the following input:\n{skill_args}"
                                    ui.append_block(f"⚙️ Running MD skill '{skill_name}'...")
                                    # Do not continue, fall through so stream_response will execute the LLM call
                                except Exception as e:
                                    ui.append_block(f"Error reading MD skill '{skill_name}': {e}")
                                    continue
                            else:
                                ui.append_block(f"Skill '{skill_name}' not found. Use /skills to list available skills.")
                                continue

                        elif subcommand == "show":
                            if len(parts) < 3:
                                ui.append_block("Usage: /skill show <name>")
                                continue
                            skill_name = parts[2].strip()
                            if skill_name.endswith(".py") or skill_name.endswith(".md"):
                                skill_name = skill_name[:-3]
                            from chatbot_cli.app_config import SKILLS_DIR
                            skill_py = SKILLS_DIR / f"{skill_name}.py"
                            skill_md = SKILLS_DIR / f"{skill_name}.md"

                            if skill_py.exists():
                                try:
                                    code = skill_py.read_text(encoding="utf-8")
                                    ui.append_block(f"Source of skill_{skill_name} ({skill_py.name}):\n\n{code}")
                                except Exception as e:
                                    ui.append_block(f"Error reading skill '{skill_name}': {e}")
                            elif skill_md.exists():
                                try:
                                    code = skill_md.read_text(encoding="utf-8")
                                    ui.append_block(f"Source of skill_{skill_name} ({skill_md.name}):\n\n{code}")
                                except Exception as e:
                                    ui.append_block(f"Error reading skill '{skill_name}': {e}")
                            else:
                                ui.append_block(f"Skill '{skill_name}' not found. Use /skills to list available skills.")
                            continue

                        elif subcommand == "delete":
                            if len(parts) < 3:
                                ui.append_block("Usage: /skill delete <name>")
                                continue
                            skill_name = parts[2].strip()
                            if skill_name.endswith(".py") or skill_name.endswith(".md"):
                                skill_name = skill_name[:-3]
                            from chatbot_cli.app_config import SKILLS_DIR
                            skill_py = SKILLS_DIR / f"{skill_name}.py"
                            skill_md = SKILLS_DIR / f"{skill_name}.md"

                            if skill_py.exists():
                                try:
                                    skill_py.unlink()
                                    ui.append_block(f"Skill '{skill_name}' deleted successfully.")
                                except Exception as e:
                                    ui.append_block(f"Error deleting skill '{skill_name}': {e}")
                            elif skill_md.exists():
                                try:
                                    skill_md.unlink()
                                    ui.append_block(f"MD Skill '{skill_name}' deleted successfully.")
                                except Exception as e:
                                    ui.append_block(f"Error deleting MD skill '{skill_name}': {e}")
                            else:
                                ui.append_block(f"Skill '{skill_name}' not found. Use /skills to list available skills.")
                            continue

                        else:
                            ui.append_block("Unknown /skill subcommand.")
                            continue

                    if user_input == "/image":
                        from chatbot_cli.ui import _grab_clipboard_image
                        filepath, filename = _grab_clipboard_image()
                        if filepath:
                            ui.pasted_images.append(filepath)
                            ui.append_block(f"✅ Image attached: {filename}. It will be sent with your next prompt.")
                        elif filename:
                            ui.append_block(f"❌ Could not attach image: {filename}")
                        else:
                            ui.append_block("❌ No image found in the clipboard.")
                        continue

                    if user_input.startswith("/"):
                        ui.append_block(f"Unknown command: {user_input}. Type /help.")
                        continue
                    try:
                        attached_images = list(ui.pasted_images)
                        ui.pasted_images.clear()
                        await stream_response(graph_ref[0], user_input, config, ui, image_paths=attached_images)
                    finally:
                        ui.set_status("")

            await ui.run(chat_loop)

async def check_for_updates(current_version: str):
    import asyncio
    import json
    import urllib.request
    from packaging.version import Version

    def _fetch():
        url = "https://pypi.org/pypi/saarthi-cli/json"
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.load(r)

    try:
        data = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        latest = data["info"]["version"]
        if Version(latest) > Version(current_version):
            console.print(
                f"[yellow]A new version is available: {latest} "
                f"(you have {current_version}). "
                f"Run 'pip install --upgrade saarthi-cli' to update.[/]"
            )
    except (OSError, KeyError, ValueError):
        pass  # network unavailable or unexpected API response — silently skip
    
def main():
    import logging
    from chatbot_cli.app_config import USER_DATA_DIR

    # Redirect logging to a local file instead of stderr to prevent TUI screen pollution
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(USER_DATA_DIR / "saarthi.log"),
            level=logging.ERROR,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    except Exception:
        # Fallback if log directory/file is not writable, just suppress root logger outputs
        logging.basicConfig(handlers=[logging.NullHandler()])

    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Suppress the ugly traceback when exiting via Ctrl+C
        pass