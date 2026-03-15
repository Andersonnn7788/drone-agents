"""LangGraph StateGraph factory — builds the agent + tool-calling loop."""

import os
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

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

    async def tools_with_logging(state: MessagesState):
        result = await tool_node.ainvoke(state)

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

    # Track nudge count to prevent infinite loops
    nudge_count = {"n": 0}
    MAX_NUDGES = 5

    def should_continue(state: MessagesState):
        """Custom routing: detects premature stops and nudges the agent back."""
        last_msg = state["messages"][-1]

        # If LLM made tool calls, proceed normally (execute tools)
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            nudge_count["n"] = 0  # Reset on successful tool use
            return "tools"

        # LLM stopped calling tools — check if mission is actually complete
        model = get_model()

        # Mission step limit reached
        if model.mission_step >= 50:
            return END

        # Check if all survivors found/rescued or no drones left
        state_data = model.get_state()
        stats = state_data.get("stats", {})
        if stats.get("rescued", 0) >= stats.get("total_survivors", 1):
            return END  # All rescued
        if stats.get("active_drones", 0) == 0:
            return END  # No drones left

        # Guard against infinite nudge loops
        if nudge_count["n"] >= MAX_NUDGES:
            _log_to_model(
                "Agent stuck after max nudges — ending mission.",
                msg_type="system",
                is_critical=True,
            )
            return END

        # Mission not complete — nudge agent to continue
        nudge_count["n"] += 1
        _log_to_model(
            f"Agent stopped without tool calls (nudge {nudge_count['n']}/{MAX_NUDGES}). "
            "Forcing continuation.",
            msg_type="system",
        )
        return "nudge"

    def nudge_node(state: MessagesState):
        """Inject a system message forcing the agent to keep acting."""
        return {"messages": [SystemMessage(content=(
            "DO NOT STOP. The mission is NOT complete — there are still survivors "
            "to find and rescue. You are FULLY AUTONOMOUS with no human operator. "
            "Make the best decision and execute it NOW. You MUST call tools."
        ))]}

    # Build the graph
    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_with_logging)
    graph.add_node("nudge", nudge_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", "nudge", END])
    graph.add_edge("tools", "agent")
    graph.add_edge("nudge", "agent")

    return graph.compile()
