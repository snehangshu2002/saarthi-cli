import uuid
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

# ──────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────
# ──────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are an elite, deeply capable AI assistant integrated directly into the user's terminal environment.

# CORE DIRECTIVES
1. Be concise, highly technical, and action-oriented. Avoid unnecessary conversational filler.
2. If the user asks you to perform a task, DO IT using your tools. Do not just explain how to do it.
3. If you lack context, use search, file-reading, or shell tools to gather it before answering.

# PERSONALIZATION & MEMORY
The following facts about the user and their environment are permanently stored in your memory:
<user_memory>
{user_details_content}
</user_memory>

- Seamlessly adapt to the user's preferred languages, frameworks, operating system, and coding style based on the memory above.
- Address the user by name if known, and maintain a friendly but professional, collaborative tone.
- NEVER explicitly say "Based on my memory..." or "I see in your profile...". Just naturally incorporate the context.

# TOOL USAGE PROTOCOL
When the user asks about or requests actions related to:
- Git operations (status, commit, push, branch management)
- File system navigation or manipulation
- Shell commands, scripting, or package management
- Code execution or running tests

**CRITICAL:** You MUST aggressively use your available tools to execute these actions or gather live context. 
- Example: If the user asks "What changed?", do not explain how to check git status. Actually execute `git status` or `git diff` using your bash tool and report the results.
- Chain tools together if needed (e.g., search for a file, then read it, then modify it).

# OUTPUT FORMAT
- Use clean Markdown.
- Use syntax highlighting for all code blocks.
- Keep explanations brief and focused on the "why" rather than stating the obvious.
- At the very end of your response, ALWAYS provide exactly 3 concise, highly relevant follow-up questions or actions the user might want to take next, formatted as a numbered list.
"""

MEMORY_PROMPT = """You are a strict, highly accurate Memory Manager for an AI assistant.
Your job is to extract long-term, stable facts about the user and their environment from the conversation.

<existing_memories>
{user_details_content}
</existing_memories>

# EXTRACTION RULES
1. ONLY extract stable facts: User identity, OS/environment details, project paths, preferred tools, languages, and distinct personal preferences.
2. IGNORE transient information: Current emotions, temporary bugs, specific code snippets, or immediate short-term tasks.
3. Keep memories as SHORT, atomic, standalone sentences (e.g., "User uses Windows 11", "User prefers Python for data science", "Main project is located at C:\\apps\\chatbot"). No speculation.

# ACTION MAPPING
For each extracted fact, determine the action:
- `add`: This is completely new information not present in <existing_memories>.
- `update`: This modifies, corrects, or expands on an existing memory. You MUST set the `replaces` field to the EXACT KEY (e.g., abc-123) of the memory being updated.
- `delete`: The user explicitly states an existing memory is no longer true. Set `replaces` to the EXACT KEY.

- Set `is_new=False` if the user just repeated something already in memory with no new details.
- If there is absolutely nothing memory-worthy in the latest message, return `should_write=false`.

# EXAMPLE
Existing: [key-123] Prefers Python for programming
User says: "I actually switched to using Java full time now, and I'm on a Mac."
-> Action 1: action=update, text="Prefers Java for programming", replaces="key-123", is_new=True
-> Action 2: action=add, text="Uses macOS", replaces="", is_new=True
"""

# ──────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────

class MemoryItem(BaseModel):
    text: str = Field(description="Atomic user memory")
    is_new: bool = Field(description="True if new, False if duplicate")
    action: Literal["add", "update", "delete"] = Field(
        description="add=new fact, update=replace existing, delete=remove outdated fact"
    )
    replaces: str = Field(
        default="",
        description=(
            "The EXACT KEY (e.g. 3f7a2b1c-9d4e-...) of the existing memory to update or delete. "
            "Empty string if action=add."
        ),
    )


class MemoryDecision(BaseModel):
    should_write: bool
    memories: list[MemoryItem] = Field(default_factory=list)


# ──────────────────────────────────────────
# State
# ──────────────────────────────────────────

class ChatState(MessagesState):
    summary: str
    pending_tool_calls: list  # tool call dicts waiting to be executed


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

async def _get_all_memories(store: BaseStore, query: str, namespace: tuple) -> list:
    """asearch(query=None) returns all items — alist() does not exist."""
    return await store.asearch(namespace, query=query, limit=500)


def _sanitize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    Remove or fix messages that would cause a 400 from Mistral.

    Rules:
    1. AIMessage with empty content AND no tool_calls -> drop (leftover streaming artifact).
    2. AIMessage with empty content BUT has tool_calls -> KEEP (required anchor for ToolMessages).
    3. ToolMessage whose preceding non-tool message is not an AIMessage with tool_calls -> drop
       (orphaned tool result; sending it confuses Mistral with wrong role order).
    """
    # Pass 1: drop truly empty AIMessages that carry no tool calls
    pass1 = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            has_tool_calls = bool(getattr(msg, "tool_calls", None))
            content = msg.content
            is_empty = not content or content == ""
            if is_empty and not has_tool_calls:
                continue  # pure streaming artifact, safe to drop
        pass1.append(msg)

    # Pass 2: drop ToolMessages that are now orphaned (no AIMessage(tool_calls) before them)
    clean = []
    for msg in pass1:
        if isinstance(msg, ToolMessage):
            preceding = next(
                (m for m in reversed(clean) if not isinstance(m, ToolMessage)),
                None,
            )
            if not (
                isinstance(preceding, AIMessage)
                and bool(getattr(preceding, "tool_calls", None))
            ):
                continue  # orphaned -- skip to avoid role-order error
        clean.append(msg)

    return clean


def _latest_human_content(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
        if getattr(msg, "type", "") == "human":
            return str(getattr(msg, "content", ""))
        if isinstance(msg, dict) and msg.get("role") in {"human", "user"}:
            return str(msg.get("content", ""))
    return ""


# ──────────────────────────────────────────
# Build graph — called once from main.py
# ──────────────────────────────────────────

def build_graph(model, checkpointer, store, tools=None):
    """
    Compile and return the graph.
    Nodes are defined inside so they close over `model` naturally —
    no global registry needed.
    """
    tools = tools or []
    tool_map = {t.name: t for t in tools}
    model_with_tools = model.bind_tools(tools) if tools else model
    memory_extractor = model.with_structured_output(MemoryDecision)

    # ── nodes ──────────────────────────────

    async def remember_node(state: ChatState, config: RunnableConfig, store: BaseStore):
        """Extract facts from the latest user message and persist them."""
        user_id = config["configurable"]["user_id"]
        namespace = ("user", user_id, "details")
        last_message = _latest_human_content(state["messages"])
        if not last_message:
            return {}

        query = last_message + ". Are there any similar memories that should be updated or deleted?"
        all_items = await _get_all_memories(store, query, namespace)
        existing = (
            "\n".join(f"[{it.key}] {it.value.get('data', '')}" for it in all_items)
            if all_items else "(empty)"
        )

        decision: MemoryDecision = await memory_extractor.ainvoke([
            SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing)),
            {"role": "user", "content": last_message},
        ])

        if decision.should_write:
            item_map = {it.key: it for it in all_items}
            for mem in decision.memories:
                if not mem.is_new and mem.action == "add":
                    continue
                if mem.action == "add":
                    await store.aput(namespace, str(uuid.uuid4()), {"data": mem.text})
                elif mem.action == "update" and mem.replaces in item_map:
                    await store.aput(namespace, mem.replaces, {"data": mem.text})
                elif mem.action == "delete" and mem.replaces in item_map:
                    await store.adelete(namespace, mem.replaces)

        return {}

    async def chat_node(state: ChatState, config: RunnableConfig, store: BaseStore):
        """Retrieve memories, sanitize history, call model once."""
        user_id = config["configurable"]["user_id"]
        namespace = ("user", user_id, "details")
        last_message = _latest_human_content(state["messages"])
        query = last_message + ". Are there any similar memories that should be updated or deleted?"
        all_items = await _get_all_memories(store, query, namespace)
        user_details = "\n".join(it.value["data"] for it in all_items) if all_items else ""

        messages = []

        if state.get("summary", ""):
            messages.append(
                SystemMessage(content=f"Conversation summary so far:\n{state['summary']}")
            )

        messages.append(
            SystemMessage(
                content=SYSTEM_PROMPT_TEMPLATE.format(
                    user_details_content=user_details or "(empty)"
                )
            )
        )

        messages.extend(_sanitize_messages(state["messages"]))

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            # Park the assistant message + pending calls; route to tools_node
            return {
                "messages": [response],
                "pending_tool_calls": response.tool_calls,
            }

        final_message = AIMessage(content=response.content or "(no response)")
        return {"messages": [final_message], "pending_tool_calls": []}

    async def tools_node(state: ChatState, config: RunnableConfig, store: BaseStore):
        """Execute all pending tool calls and return ToolMessages."""
        pending = state.get("pending_tool_calls", [])
        if not pending:
            return {"pending_tool_calls": []}

        tool_messages = []
        for tc in pending:
            t = tool_map.get(tc["name"])
            if t is None:
                result = f"ERROR: unknown tool '{tc['name']}'"
            else:
                try:
                    if hasattr(t, "ainvoke"):
                        result = await t.ainvoke(tc["args"])
                    else:
                        result = t.invoke(tc["args"])
                except Exception as e:
                    result = f"ERROR: {e}"
            tool_messages.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tc["id"],
                    name=tc["name"],
                )
            )

        return {"messages": tool_messages, "pending_tool_calls": []}

    async def tool_followup_node(state: ChatState, config: RunnableConfig, store: BaseStore):
        """After tools execute, call model again with tool results in context."""
        user_id = config["configurable"]["user_id"]
        namespace = ("user", user_id, "details")
        last_message = _latest_human_content(state["messages"])
        query = last_message + ". Are there any similar memories?"
        all_items = await _get_all_memories(store, query, namespace)
        user_details = "\n".join(it.value["data"] for it in all_items) if all_items else ""

        messages = []
        if state.get("summary", ""):
            messages.append(
                SystemMessage(content=f"Conversation summary so far:\n{state['summary']}")
            )
        messages.append(
            SystemMessage(
                content=SYSTEM_PROMPT_TEMPLATE.format(
                    user_details_content=user_details or "(empty)"
                )
            )
        )
        messages.extend(_sanitize_messages(state["messages"]))

        response = await model_with_tools.ainvoke(messages)

        if response.tool_calls:
            # Model wants more tools — loop back
            return {
                "messages": [response],
                "pending_tool_calls": response.tool_calls,
            }

        final_message = AIMessage(content=response.content or "(no response)")
        return {"messages": [final_message], "pending_tool_calls": []}

    async def summarize_conversation(state: ChatState):
        """Summarise older messages to keep context window manageable."""
        existing_summary = state.get("summary", "")
        summary_prompt = (
            f"Existing summary:\n{existing_summary}\n\nExtend the summary using the new conversation above."
            if existing_summary
            else "Summarize the conversation above."
        )
        # sanitize here too — summary node also reads full history
        clean_messages = _sanitize_messages(state["messages"])
        message_for_summary = clean_messages + [HumanMessage(content=summary_prompt)]
        response = await model.ainvoke(message_for_summary)
        return {"summary": response.content}

    # ── conditional edges ───────────────────

    def route_after_chat(state: ChatState) -> str:
        if state.get("pending_tool_calls"):
            return "tools"
        return "summarize" if len(state["messages"]) % 6 == 0 else "remember"

    def route_after_tools(state: ChatState) -> str:
        return "tool_followup"

    def route_after_followup(state: ChatState) -> str:
        if state.get("pending_tool_calls"):
            return "tools"  # model wants more tools — loop
        return "summarize" if len(state["messages"]) % 6 == 0 else "remember"

    # ── compile ────────────────────────────

    builder = StateGraph(ChatState)
    builder.add_node("remember", remember_node)
    builder.add_node("chat", chat_node)
    builder.add_node("tools", tools_node)
    builder.add_node("tool_followup", tool_followup_node)
    builder.add_node("summarize", summarize_conversation)

    builder.add_edge(START, "chat")
    builder.add_conditional_edges(
        "chat",
        route_after_chat,
        {"tools": "tools", "summarize": "summarize", "remember": "remember"},
    )
    builder.add_edge("tools", "tool_followup")
    builder.add_conditional_edges(
        "tool_followup",
        route_after_followup,
        {"tools": "tools", "summarize": "summarize", "remember": "remember"},
    )
    builder.add_edge("summarize", "remember")
    builder.add_edge("remember", END)

    return builder.compile(checkpointer=checkpointer, store=store)