"""LangGraph StateGraph factory — builds the agent + tool-calling loop."""

import os
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from simulation.state import get_model
from .prompts import SYSTEM_PROMPT


def _log_to_model(message: str, msg_type: str = "system", is_critical: bool = False):
    """Append a log entry to the shared model so the SSE bridge can stream it."""
    model = get_model()
    # Auto-detect triage-critical entries
    triage_keywords = ["IMMEDIATE", "CRITICAL survivor", "URGENT", "health < 30"]
    if any(kw in message for kw in triage_keywords):
        is_critical = True
        msg_type = "triage"
    model.agent_logs.append({
        "step": model.mission_step,
        "timestamp": time.time(),
        "message": message,
        "is_critical": is_critical,
        "type": msg_type,
    })


def build_graph(tools: list):
    """Build and compile the LangGraph agent with the given MCP tools."""

    model_name = os.environ.get("LLM_MODEL", "gpt-5-mini")
    llm = ChatOpenAI(model=model_name, temperature=0.1)
    llm_with_tools = llm.bind_tools(tools)

    tool_node = ToolNode(tools)

    def agent_node(state: MessagesState):
        messages = list(state["messages"])

        # Prepend system prompt if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages.insert(0, SystemMessage(content=SYSTEM_PROMPT))

        # Count advance_simulation calls to enforce step limit
        advance_count = 0
        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "advance_simulation":
                        advance_count += 1

        if advance_count >= 50:
            messages.append(SystemMessage(
                content=(
                    "MISSION STEP LIMIT REACHED (50 steps). You MUST wrap up now. "
                    "Call get_mission_summary() to review results, then give your "
                    "final assessment. Do NOT call advance_simulation again."
                )
            ))

        response = llm_with_tools.invoke(messages)

        # Log LLM reasoning text
        if response.content and isinstance(response.content, str) and response.content.strip():
            _log_to_model(response.content, msg_type="reasoning")

        # Log tool calls
        if response.tool_calls:
            for tc in response.tool_calls:
                args_str = ", ".join(f"{k}={v}" for k, v in tc.get("args", {}).items())
                _log_to_model(
                    f"Tool call: {tc['name']}({args_str})",
                    msg_type="tool_call",
                )

        return {"messages": [response]}

    def tools_with_logging(state: MessagesState):
        result = tool_node.invoke(state)

        # Log tool results
        for msg in result.get("messages", []):
            if isinstance(msg, ToolMessage):
                content = str(msg.content)
                if len(content) > 300:
                    content = content[:300] + "..."
                _log_to_model(
                    f"Result [{msg.name}]: {content}",
                    msg_type="result",
                )

        return result

    # Build the graph
    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_with_logging)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile()
