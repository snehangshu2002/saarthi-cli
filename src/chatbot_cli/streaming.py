import json
import logging

from langchain_core.messages import AIMessageChunk, ToolMessage

logger = logging.getLogger(__name__)


def _args_preview(args: dict, max_chars: int = 65) -> str:
    """Compact single-line preview of tool arguments, optimized for readability."""
    if not args:
        return ""
    if not isinstance(args, dict):
        preview_str = str(args).strip()
    else:
        # Try to extract the most descriptive argument
        preview = None
        if "CommandLine" in args:
            preview = args["CommandLine"]
        elif "command" in args:
            preview = args["command"]
        elif "TargetFile" in args:
            preview = args["TargetFile"]
        elif "AbsolutePath" in args:
            preview = args["AbsolutePath"]
        elif "SearchPath" in args:
            preview = args["SearchPath"]
        elif "Query" in args:
            preview = args["Query"]
        elif "query" in args:
            preview = args["query"]
        elif "Url" in args:
            preview = args["Url"]
        elif "url" in args:
            preview = args["url"]
        elif "Prompt" in args:
            preview = args["Prompt"]
        elif "prompt" in args:
            preview = args["prompt"]

        if preview is None:
            # Fallback to general formatting of the values
            if len(args) == 1:
                preview = list(args.values())[0]
            else:
                try:
                    preview = json.dumps(args, ensure_ascii=False)
                except Exception:
                    preview = str(args)
        
        preview_str = str(preview).strip()

    # Normalize path separators if it looks like a path
    if "\\" in preview_str or "/" in preview_str:
        preview_str = preview_str.replace("\\", "/")

    # Middle-truncation if longer than max_chars
    if len(preview_str) <= max_chars:
        return preview_str
    
    half = (max_chars - 3) // 2
    return f"{preview_str[:half]}...{preview_str[-half:]}"


async def stream_response(graph, user_input: str, config: dict, ui, image_paths: list[str] = None) -> str:
    full_text = ""
    ui.start_bot_message()

    # Track tool call names keyed by tool_call_id so ToolMessage can label itself
    _pending_tool_names: dict[str, str] = {}
    _pending_tool_args: dict[str, dict] = {}
    # Track in-flight tool blocks by tool_call_id
    _in_flight_blocks: dict[str, int] = {}

    _active_thought_idx = None
    _accumulated_thought = ""

    # Construct user payload
    if image_paths:
        import base64
        import mimetypes
        from pathlib import Path
        content_payload = [{"type": "text", "text": user_input}]
        for path in image_paths:
            try:
                p = Path(path)
                if p.exists():
                    mime_type, _ = mimetypes.guess_type(path)
                    if not mime_type:
                        mime_type = "image/png"
                    encoded = base64.b64encode(p.read_bytes()).decode("utf-8")
                    content_payload.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded}"
                        }
                    })
            except Exception as e:
                logger.error(f"Error encoding image {path}: {e}")
    else:
        content_payload = user_input

    try:
        async for chunk, metadata in graph.astream(
            {"messages": [{"role": "user", "content": content_payload}]},
            config=config,
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node")

            # ── Thought / reasoning stream from model ──────────────────────────
            if node in ("chat", "tool_followup") and isinstance(chunk, AIMessageChunk):
                reasoning = None
                if hasattr(chunk, "reasoning_content") and chunk.reasoning_content:
                    reasoning = chunk.reasoning_content
                elif "reasoning_content" in chunk.additional_kwargs:
                    reasoning = chunk.additional_kwargs["reasoning_content"]
                elif "reasoning" in chunk.additional_kwargs:
                    reasoning = chunk.additional_kwargs["reasoning"]

                if reasoning:
                    if _active_thought_idx is None:
                        _active_thought_idx = ui.start_thought()
                    _accumulated_thought += reasoning
                    ui.update_thought(_active_thought_idx, _accumulated_thought, in_flight=True)

            # ── Tool call announced by model (chat or tool_followup node) ──────
            if node in ("chat", "tool_followup") and isinstance(chunk, AIMessageChunk):
                if chunk.tool_calls:
                    # Finalize thought if active before tool call
                    if _active_thought_idx is not None:
                        ui.update_thought(_active_thought_idx, _accumulated_thought, in_flight=False)
                        _active_thought_idx = None
                        _accumulated_thought = ""

                for tc in (chunk.tool_calls or []):
                    name = tc.get("name", "tool")
                    tid = tc.get("id", "")
                    args = tc.get("args", {})
                    if tid:
                        _pending_tool_names[tid] = name
                        _pending_tool_args[tid] = args
                    preview = _args_preview(args) if args else ""
                    from chatbot_cli.ui import get_friendly_tool_name
                    friendly_name = get_friendly_tool_name(name)
                    ui.set_status(f"⚙  {friendly_name}({preview})…")

                    # Create in-flight tool block showing execution in progress
                    header = f"({_args_preview(args)})" if args else ""
                    in_flight_output = "Running…"
                    idx = ui.append_tool_block(name, f"{name}{header}\n{in_flight_output}", in_flight=True)
                    if tid:
                        _in_flight_blocks[tid] = idx

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

                # Update the in-flight block with actual results and mark it complete
                if tid and tid in _in_flight_blocks:
                    ui.update_tool_block(_in_flight_blocks.pop(tid), full_block, in_flight=False)
                else:
                    ui.append_tool_block(tool_name, full_block, in_flight=False)

                # Clean up stale tracking state for this call
                _pending_tool_names.pop(tid, None)
                _pending_tool_args.pop(tid, None)
                ui.set_status("")

            # ── Stream final text ───────────────────────────────────────────────
            if (
                node in ("chat", "tool_followup")
                and isinstance(chunk, AIMessageChunk)
                and isinstance(chunk.content, str)
                and chunk.content
            ):
                if _active_thought_idx is not None:
                    # Finalize active thought block
                    ui.update_thought(_active_thought_idx, _accumulated_thought, in_flight=False)
                    _active_thought_idx = None
                    _accumulated_thought = ""

                if not full_text:
                    ui.set_status("")
                full_text += chunk.content
                ui.update_bot_message(full_text)

    except Exception as e:
        logger.exception("Streaming error: %s", e)
        ui.set_status("")
        # Close any tool blocks that are still in-flight so the UI is not stuck
        for tid, idx in _in_flight_blocks.items():
            tool_name = _pending_tool_names.get(tid, "tool")
            ui.update_tool_block(idx, f"{tool_name}\n(interrupted)", in_flight=False)
        _in_flight_blocks.clear()

        if not full_text:
            full_text = (
                "Something went wrong while generating a response. "
                "Check your API key and network connection, then try again."
            )
        ui.update_bot_message(full_text)

    finally:
        # Finalize thought if active
        if _active_thought_idx is not None:
            ui.update_thought(_active_thought_idx, _accumulated_thought, in_flight=False)
            _active_thought_idx = None
            _accumulated_thought = ""

        # Always close any remaining in-flight blocks (e.g. on KeyboardInterrupt)
        for tid, idx in list(_in_flight_blocks.items()):
            tool_name = _pending_tool_names.get(tid, "tool")
            ui.update_tool_block(idx, f"{tool_name}\n(interrupted)", in_flight=False)
        _in_flight_blocks.clear()

    if not full_text:
        full_text = "No response received. Check your API key in settings.json."

    ui.finish_bot_message(full_text)
    return full_text