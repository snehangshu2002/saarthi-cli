import uuid
from typing import Literal

from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.store.memory import InMemoryStore
from langgraph.store.base import BaseStore
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field
from langgraph.store.sqlite import AsyncSqliteStore
from langgraph.checkpoint.sqlite import AsyncSqliteSaver
import os
import sqlite3

load_dotenv()

# ──────────────────────────────────────────
# Models
# ──────────────────────────────────────────

model = ChatMistralAI()          
embedding_model = MistralAIEmbeddings()

# ──────────────────────────────────────────
# Store + Checkpointer  (module-level so main.py can import store)
# ──────────────────────────────────────────

os.makedirs("data", exist_ok=True)

# Separate connection for checkpoints
checkpoint_conn = AsyncSqliteSaver.connect(
    "data/checkpoints.db",
    check_same_thread=False
)

# Separate connection for store
store_conn = AsyncSqliteStore.connect(
    "data/memory.db",
    check_same_thread=False
)

store=SqliteStore(conn=store_conn,index={"embed": embedding_model, "dims": 1024})
store.setup()
checkpointer=SqliteSaver(conn=checkpoint_conn)

# ──────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant with memory capabilities.
If user-specific memory is available, use it to personalize
your responses based on what you know about the user.
Your goal is to provide relevant, friendly, and tailored
assistance that reflects the user's preferences, context, and past interactions.
If the user's name or relevant personal context is available, always personalize your responses by:
    - Address the user by name (e.g., "Sure, Snehangshu...") when appropriate
    - Reference known projects, tools, or preferences
    - Adjust the tone to feel friendly, natural, and directly aimed at the user
Avoid generic phrasing when personalization is possible.
Always ensure that personalization is based only on known user details and not assumed.
In the end suggest 3 relevant further questions based on the current response and user profile.
The user's memory (which may be empty) is provided as: {user_details_content}
"""

MEMORY_PROMPT = """You maintain accurate user memory.
Existing memories (format: [key] text):
{user_details_content}
From the user's latest message:
- Extract stable user-specific facts (identity, preferences, projects).
- For each fact decide the action:
    * add    -> completely new information not in existing memories
    * update -> replaces/corrects an existing memory (set replaces= to the EXACT KEY like abc-123)
    * delete -> existing memory is outdated (set replaces= to the EXACT KEY like abc-123)
- Set is_new=False for duplicates with no new info.
- Short atomic sentences only. No speculation.
- Nothing memory-worthy? Return should_write=false.
Example:
Existing: [abc-123] Prefers Python for programming
User says: "I switched to Java"
-> action=update, text="Prefers Java", replaces="abc-123"
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
            "Get this key from the [key] prefix shown in existing memories. "
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


# ──────────────────────────────────────────
# Memory extractor
# ──────────────────────────────────────────

memory_extractor = model.with_structured_output(MemoryDecision)

# ──────────────────────────────────────────
# Nodes
# ──────────────────────────────────────────

async def remember_node(state: ChatState, config: RunnableConfig, store: BaseStore):
    """Extract facts from the latest user message and persist them to the store."""
    user_id = config["configurable"]["user_id"]
    namespace = ("user", user_id, "details")
    last_message = state["messages"][-1].content

    items:list[Document] = await store.search(namespace, query=last_message, limit=5)
    filtered = [it for it in items if it.score > 0.70]
    existing = (
        "\n".join(f"[{it.key}] {it.value.get('data', '')}" for it in filtered)
        if filtered
        else "(empty)"
    )

    decision: MemoryDecision = await memory_extractor.ainvoke([
        SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing)),
        {"role": "user", "content": last_message},
    ])

    if decision.should_write:
        for mem in decision.memories:
            if not mem.is_new and mem.action == "add":
                continue
            if mem.action == "add":
                await store.put(namespace, str(uuid.uuid4()), {"data": mem.text})
            elif mem.action in ("update", "delete"):
                for item in items:
                    if item.key == mem.replaces:
                        if mem.action == "update":
                            await store.put(namespace, item.key, {"data": mem.text})
                        elif mem.action == "delete":
                            await store.delete(namespace, item.key)
                        break

    return {}


async def chat_node(state: ChatState, config: RunnableConfig, store: BaseStore):
    """Build the full message list and call the model."""
    user_id = config["configurable"]["user_id"]
    namespace = ("user", user_id, "details")
    last_message = state["messages"][-1].content

    items:list[Document] = await store.search(namespace, query=last_message, limit=5)
    filtered = [it for it in items if it.score > 0.70]
    user_details = "\n".join(it.value["data"] for it in filtered) if filtered else ""

    messages = []

    # prepend summary if one exists
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
    messages.extend(state["messages"])

    response = await model.ainvoke(messages)
    return {"messages": [response]}


async def summarize_conversation(state: ChatState):
    """Summarise older messages to keep context window manageable."""
    existing_summary = state.get("summary", "")
    if existing_summary:
        prompt = (
            f"Existing summary:\n{existing_summary}\n\n"
            "Extend the summary using the new conversation above."
        )
    else:
        prompt = "Summarize the conversation above."

    message_for_summary = state["messages"] + [HumanMessage(content=prompt)]
    response = await model.ainvoke(message_for_summary)
    return {"summary": response.content}


# ──────────────────────────────────────────
# Conditional edge
# ──────────────────────────────────────────

async def should_summarize(state: ChatState):
    """Summarise every 6 messages, not on every turn after 6."""
    return len(state["messages"]) % 6 == 0


# ──────────────────────────────────────────
# Build graph
# ──────────────────────────────────────────

builder = StateGraph(ChatState)
builder.add_node("remember", remember_node)
builder.add_node("chat", chat_node)
builder.add_node("summarize", summarize_conversation)

builder.add_edge(START, "remember")
builder.add_edge("remember", "chat")
builder.add_conditional_edges(
    "chat",
    should_summarize,
    {True: "summarize", False: END},
)
builder.add_edge("summarize", END)

graph = builder.compile(checkpointer=checkpointer, store=store)