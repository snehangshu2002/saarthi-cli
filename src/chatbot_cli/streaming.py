from langchain_core.messages import AIMessageChunk, ToolMessage


async def stream_response(graph, user_input: str, config: dict, ui) -> str:
    full_text = ""
    ui.start_bot_message()

    async for chunk, metadata in graph.astream(
        {"messages": [{"role": "user", "content": user_input}]},
        config=config,
        stream_mode="messages",
    ):
        node = metadata.get("langgraph_node")

        # Show tool status while executing
        if node == "chat" and isinstance(chunk, AIMessageChunk):
            if chunk.tool_calls:
                tool_name = chunk.tool_calls[0].get("name", "tool")
                ui.set_status(f"Running {tool_name}...")

        # Stream final text response
        if (
            node == "chat"
            and isinstance(chunk, AIMessageChunk)
            and isinstance(chunk.content, str)
            and chunk.content
        ):
            if not full_text:
                ui.set_status("")
            full_text += chunk.content
            ui.update_bot_message(full_text)

        # Render tool results as collapsible blocks in transcript
        if node == "chat" and isinstance(chunk, ToolMessage):
            # Extract tool name from the preceding context isn't available here,
            # so we label with a generic name — chatbot.py sets the tool_call_id
            tool_label = getattr(chunk, "name", None) or "bash"
            ui.append_tool_block(tool_label, str(chunk.content))

    if not full_text:
        full_text = "No response received. Check your API key in settings.json."

    ui.finish_bot_message(full_text)
    return full_text