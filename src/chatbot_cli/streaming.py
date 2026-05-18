import json

from langchain_core.messages import AIMessageChunk, ToolMessage


def _args_preview(args: dict, max_chars: int = 80) -> str:
    """Compact single-line preview of tool arguments."""
    try:
        s = json.dumps(args, ensure_ascii=False)
    except Exception:
        s = str(args)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


async def stream_response(graph, user_input: str, config: dict, ui) -> str:
    full_text = ""
    ui.start_bot_message()
    # Reset tool blocks for this new response turn
    ui._tool_blocks = []
    ui._tool_expanded = set()

    # Track tool call names keyed by tool_call_id so ToolMessage can label itself
    _pending_tool_names: dict[str, str] = {}
    _pending_tool_args: dict[str, dict] = {}

    async for chunk, metadata in graph.astream(
        {"messages": [{"role": "user", "content": user_input}]},
        config=config,
        stream_mode="messages",
    ):
        node = metadata.get("langgraph_node")

        # ── Tool call announced by model (chat or tool_followup node) ──────
        if node in ("chat", "tool_followup") and isinstance(chunk, AIMessageChunk):
            for tc in (chunk.tool_calls or []):
                name = tc.get("name", "tool")
                tid = tc.get("id", "")
                args = tc.get("args", {})
                if tid:
                    _pending_tool_names[tid] = name
                    _pending_tool_args[tid] = args
                preview = _args_preview(args) if args else ""
                ui.set_status(f"⚙  {name}({preview})…")

        # ── Tool result from tools_node ─────────────────────────────────────
        if node == "tools" and isinstance(chunk, ToolMessage):
            tid = getattr(chunk, "tool_call_id", "") or ""
            tool_name = (
                getattr(chunk, "name", None)
                or _pending_tool_names.get(tid, "tool")
            )
            args = _pending_tool_args.get(tid, {})
            header = f"({_args_preview(args)})" if args else ""

            raw_output = str(chunk.content)
            full_block = f"{tool_name}{header}\n{raw_output}"
            ui.append_tool_block(tool_name, full_block)
            ui.set_status("")

        # ── Stream final text ───────────────────────────────────────────────
        if (
            node in ("chat", "tool_followup")
            and isinstance(chunk, AIMessageChunk)
            and isinstance(chunk.content, str)
            and chunk.content
        ):
            if not full_text:
                ui.set_status("")
            full_text += chunk.content
            ui.update_bot_message(full_text)

    if not full_text:
        full_text = "No response received. Check your API key in settings.json."

    ui.finish_bot_message(full_text)
    return full_text