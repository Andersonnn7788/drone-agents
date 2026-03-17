"""LangGraph StateGraph factory — builds the agent + tool-calling loop."""

import os
import re
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

from simulation.state import get_model
from .prompts import SYSTEM_PROMPT


def _summarize_tool_result(tool_name: str, raw_content_blocks: list) -> str | None:
    """Produce a human-readable one-liner for noisy MCP tool results.

    Returns None when no special summarizer exists (caller falls back to truncation).
    """
    # Flatten content blocks into text parts
    parts: list[str] = []
    for block in raw_content_blocks:
        if isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)

    if not parts:
        return None

    try:
        if tool_name == "get_priority_map":
            vals = [float(p) for p in parts if p.strip().replace(".", "", 1).replace("-", "", 1).isdigit()]
            if not vals:
                return None
            lo, hi = min(vals), max(vals)
            # top cells — interpret as row-major 12x12
            indexed = list(enumerate(vals))
            indexed.sort(key=lambda x: x[1], reverse=True)
            top = indexed[:3]
            top_str = ", ".join(f"({i % 12},{i // 12})={v:.2f}" for i, v in top)
            return f"Priority map: range [{lo:.2f}, {hi:.2f}], top: {top_str}"

        if tool_name == "get_pheromone_map":
            # MCP returns {"scanned": [[...], ...], "survivor_nearby": [[...], ...], "danger": [[...], ...]}
            # Parse the JSON and count cells > 0 for each layer.
            import json as _json
            counts: dict[str, int] = {}
            try:
                data = _json.loads("\n".join(parts))
                for layer in ("scanned", "survivor_nearby", "danger"):
                    grid = data.get(layer, [])
                    count = sum(1 for row in grid for val in row if val > 0)
                    counts[layer] = count
            except (ValueError, TypeError, KeyError):
                for layer in ("scanned", "survivor_nearby", "danger"):
                    counts[layer] = 0
            entries = ", ".join(f"{k}={v} active" for k, v in counts.items())
            return f"Pheromone map: {entries}"

        if tool_name == "discover_drones":
            drones = []
            for p in parts:
                if "drone" in p.lower() or "id" in p.lower():
                    drones.append(p.strip())
            if drones:
                return f"Drones: {' | '.join(drones[:5])}"
            text = " | ".join(p.strip() for p in parts[:5])
            return f"Drones: {text[:200]}"

        if tool_name == "thermal_scan":
            text = "\n".join(parts)
            # Check for actual survivors, not just the substring "survivor"
            has_survivors = '"survivors_found": [' in text and '"survivors_found": []' not in text
            if has_survivors:
                return f"Scan: {text[:200]}"
            return f"Scan: no survivors detected. {text[:100]}"

        if tool_name == "rescue_survivor":
            text = "\n".join(parts)
            return f"Rescue: {text[:200]}"

        if tool_name == "advance_simulation":
            text = "\n".join(parts)
            return f"Step result: {text[:200]}"

        if tool_name == "simulate_mission":
            text = "\n".join(parts)
            return f"Simulation: {text[:200]}"

        if tool_name == "get_battery_status":
            text = " | ".join(p.strip() for p in parts[:5])
            return f"Battery: {text[:200]}"

    except Exception:
        return None

    return None


def _emit_narrative(tool_name: str, raw_content_blocks: list) -> bool:
    """Generate human-language narrative log entries for mission events.

    Returns True if a narrative entry was emitted, False otherwise.
    """
    parts: list[str] = []
    for block in raw_content_blocks:
        if isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)

    text = "\n".join(parts).lower()
    full = "\n".join(parts)

    try:
        # --- Triage events (keep as msg_type="triage") ---

        if tool_name == "thermal_scan":
            # Only emit triage when survivors were actually found.
            # The result JSON contains "survivors_found": [...]; an empty list
            # still has the word "survivor" so we must check for real content.
            has_survivors = False
            try:
                import json as _json
                for p in parts:
                    parsed = _json.loads(p)
                    if isinstance(parsed, dict) and parsed.get("survivors_found"):
                        has_survivors = True
                        break
            except (ValueError, TypeError, KeyError):
                # Fallback: look for a non-empty survivors_found list in raw text
                has_survivors = '"survivors_found": [' in full and '"survivors_found": []' not in full

            if has_survivors:
                severity = "CRITICAL" if "critical" in text else "MODERATE" if "moderate" in text else "STABLE"
                _log_to_model(
                    f"Survivor detected — {severity}. Initiating triage protocol.",
                    msg_type="triage",
                    is_critical=(severity == "CRITICAL"),
                )
            else:
                _log_to_model(
                    "Thermal scan clear — no survivors in this sector.",
                    msg_type="narrative",
                )
            return True

        if tool_name == "rescue_survivor":
            if "rescued" in text or "success" in text:
                _log_to_model(
                    "Survivor rescued successfully.",
                    msg_type="triage",
                    is_critical=True,
                )
            return True

        if tool_name == "assess_survivor":
            level = "IMMEDIATE" if "immediate" in text else "URGENT" if "urgent" in text else "DELAYED" if "delayed" in text else "STANDARD"
            is_crit = level in ("IMMEDIATE", "URGENT")
            detail = full[:120].strip()
            _log_to_model(
                f"Triage: {level} priority — {detail}.",
                msg_type="triage" if is_crit else "narrative",
                is_critical=is_crit,
            )
            return True

        # --- Narrative events (msg_type="narrative") ---

        if tool_name == "discover_drones":
            # Count drones by parsing JSON drone entries
            import json as _json
            drone_count = 0
            for p in parts:
                try:
                    parsed = _json.loads(p)
                    if isinstance(parsed, list):
                        drone_count += len(parsed)
                    elif isinstance(parsed, dict) and "drone_id" in parsed:
                        drone_count += 1
                except (ValueError, TypeError):
                    pass
            if drone_count < 1:
                # Fallback: count unique "drone_id" occurrences in text
                drone_count = max(len(re.findall(r'"drone_id"', full)), 1)
            _log_to_model(
                f"Fleet online — {drone_count} drones reporting for duty.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "move_to":
            if "false" in text or "fail" in text or "blocked" in text or "cannot" in text:
                # Extract reason if available
                reason = full[:150].strip()
                _log_to_model(
                    f"Movement blocked — {reason}.",
                    msg_type="narrative",
                    is_critical=True,
                )
                return True
            # Success is NOT narrated (too frequent)
            return True

        if tool_name == "coordinate_swarm":
            _log_to_model(
                "Swarm sectors assigned — drones dispersing for coverage.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "deploy_as_relay":
            # Try to extract drone id and position
            import re as _re
            drone_match = _re.search(r"drone[_\s]?(\w+)", text)
            pos_match = _re.search(r"\((\d+),\s*(\d+)\)", full)
            drone_id = drone_match.group(1) if drone_match else "?"
            pos = f"({pos_match.group(1)},{pos_match.group(2)})" if pos_match else "(?)"
            _log_to_model(
                f"Drone {drone_id} deployed as relay at {pos} — mesh range extended.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "recall_drone":
            import re as _re
            drone_match = _re.search(r"drone[_\s]?(\w+)", text)
            drone_id = drone_match.group(1) if drone_match else "?"
            _log_to_model(
                f"Drone {drone_id} recalled to base — RTB engaged.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "sync_findings":
            import re as _re
            count_match = _re.search(r"(\d+)", full)
            count = count_match.group(1) if count_match else "?"
            _log_to_model(
                f"Buffered findings synced — {count} reports recovered.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "get_disaster_events":
            # Only narrate when actual events exist
            if "aftershock" in text or "rising_water" in text or "blackout" in text:
                dtype = "Aftershock" if "aftershock" in text else "Rising water" if "rising_water" in text else "Blackout"
                _log_to_model(
                    f"Disaster alert — {dtype} detected. Adjusting operations.",
                    msg_type="narrative",
                    is_critical=True,
                )
            return True

        if tool_name == "trigger_blackout":
            _log_to_model(
                "Comms blackout — affected drones switching to autonomous mode.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "simulate_mission":
            if "infeasible" in text or "insufficient" in text or "false" in text or "cannot" in text:
                _log_to_model(
                    "Digital twin warns: insufficient fuel for round trip.",
                    msg_type="narrative",
                    is_critical=True,
                )
            return True

        if tool_name == "get_battery_status":
            # Only narrate when low batteries detected
            import re as _re
            batteries = _re.findall(r"(\d+)%?", full)
            low = [int(b) for b in batteries if int(b) < 20 and int(b) > 0]
            if low:
                _log_to_model(
                    f"Battery alert — drone(s) below 20%.",
                    msg_type="narrative",
                    is_critical=True,
                )
            return True

        if tool_name == "get_network_resilience":
            _log_to_model(
                "Mesh analysis complete — reviewing connectivity.",
                msg_type="narrative",
            )
            return True

        if tool_name == "get_pheromone_map":
            _log_to_model(
                "Pheromone trails analyzed — checking hot spots.",
                msg_type="narrative",
            )
            return True

        if tool_name == "get_priority_map":
            _log_to_model(
                "Priority heatmap refreshed — targeting high-probability zones.",
                msg_type="narrative",
            )
            return True

        if tool_name == "advance_simulation":
            _log_to_model(
                f"Step advanced: {full[:150]}",
                msg_type="system",
            )
            return True

    except Exception:
        return False

    return False


def _log_to_model(message: str, msg_type: str = "system", is_critical: bool = False):
    """Append a log entry to the shared model so the SSE bridge can stream it."""
    model = get_model()
    model.agent_logs.append({
        "step": model.mission_step,
        "timestamp": time.time(),
        "message": message,
        "is_critical": is_critical,
        "type": msg_type,
    })


def _trim_messages(messages: list, window: int) -> list:
    """Trim messages to window size while preserving tool call/result pairs."""
    if window <= 0 or len(messages) <= window + 1:
        return messages

    system = messages[0]
    recent = messages[-(window):]

    # If the first message in `recent` is a ToolMessage, we need to find
    # its paired AIMessage (with tool_calls) and include it too
    while recent and isinstance(recent[0], ToolMessage):
        trim_start = len(messages) - len(recent)
        found_pair = False
        for i in range(trim_start - 1, 0, -1):
            msg = messages[i]
            if isinstance(msg, AIMessage) and msg.tool_calls:
                recent = messages[i:]
                found_pair = True
                break
            elif isinstance(msg, ToolMessage):
                continue  # Keep looking past adjacent ToolMessages
            else:
                # Hit a non-tool, non-AI message — drop orphan ToolMessages
                while recent and isinstance(recent[0], ToolMessage):
                    recent.pop(0)
                found_pair = True
                break
        if not found_pair:
            # Didn't find a paired AIMessage — drop orphan ToolMessages
            while recent and isinstance(recent[0], ToolMessage):
                recent.pop(0)
            break

    return [system] + recent


def build_graph(tools: list):
    """Build and compile the LangGraph agent with the given MCP tools."""

    model_name = os.environ.get("LLM_MODEL", "gpt-5-mini")
    llm = ChatOpenAI(model=model_name, temperature=0.1)
    llm_with_tools = llm.bind_tools(tools)

    tool_node = ToolNode(tools)

    # Message window size (0 = disabled)
    msg_window = int(os.environ.get("MSG_WINDOW_SIZE", "0"))

    # Step limit from env
    max_steps = int(os.environ.get("MAX_MISSION_STEPS", "50"))

    # Demo mode flag
    demo_mode = os.environ.get("DEMO_MODE", "0") == "1"

    # Minimum steps in demo mode — must run past all scripted events (last at step 11)
    MIN_DEMO_STEPS = 13

    # Select prompt
    if demo_mode:
        from .prompts import DEMO_SYSTEM_PROMPT
        system_prompt = DEMO_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    def agent_node(state: MessagesState):
        messages = list(state["messages"])

        # Prepend system prompt if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages.insert(0, SystemMessage(content=system_prompt))

        # Sliding window: keep system prompt + last N messages (preserving tool pairs)
        messages = _trim_messages(messages, msg_window)

        # Count advance_simulation calls to enforce step limit
        advance_count = 0
        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "advance_simulation":
                        advance_count += 1

        if advance_count >= max_steps:
            messages.append(SystemMessage(
                content=(
                    f"MISSION STEP LIMIT REACHED ({max_steps} steps). You MUST wrap up now. "
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
                args_str = ", ".join(
                    f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                    for k, v in tc.get("args", {}).items()
                )
                _log_to_model(
                    f"Tool call: {tc['name']}({args_str})",
                    msg_type="tool_call",
                )

        return {"messages": [response]}

    async def tools_with_logging(state: MessagesState):
        result = await tool_node.ainvoke(state)

        # Log tool results with smart summarization
        for msg in result.get("messages", []):
            if isinstance(msg, ToolMessage):
                raw = msg.content
                raw_blocks = raw if isinstance(raw, list) else [raw]

                # Try smart summary first
                summary = _summarize_tool_result(msg.name, raw_blocks)
                if summary:
                    content = summary
                else:
                    # Fallback: extract text and truncate
                    if isinstance(raw, list):
                        parts = []
                        for block in raw:
                            if isinstance(block, dict) and "text" in block:
                                parts.append(block["text"])
                        content = "\n".join(parts) if parts else str(raw)
                    else:
                        content = str(raw)
                    if len(content) > 300:
                        content = content[:300] + "..."

                # Emit narrative entries for key events; skip raw result if narrative was emitted
                narrated = _emit_narrative(msg.name, raw_blocks)
                if not narrated:
                    _log_to_model(
                        f"Result [{msg.name}]: {content}",
                        msg_type="result",
                    )

        return result

    # Track nudge count to prevent infinite loops
    nudge_count = {"n": 0}
    MAX_NUDGES = 3

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
        if model.mission_step >= max_steps:
            return END

        # In demo mode, don't allow early exit before scripted events have fired
        if demo_mode and model.mission_step < MIN_DEMO_STEPS:
            nudge_count["n"] += 1
            if nudge_count["n"] >= MAX_NUDGES:
                nudge_count["n"] = 0  # Reset — keep trying in demo mode
            _log_to_model(
                f"Continuing mission — step {model.mission_step}/{MIN_DEMO_STEPS}.",
                msg_type="system",
            )
            return "nudge"

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
        model = get_model()
        if demo_mode and model.mission_step < MIN_DEMO_STEPS:
            return {"messages": [SystemMessage(content=(
                f"CONTINUE OPERATING. Step {model.mission_step}/{MIN_DEMO_STEPS}. "
                "Call advance_simulation() to progress time. Check get_disaster_events() "
                "for new threats. Monitor drone batteries. Manage any blackouts or emergencies. "
                "Keep scanning unexplored areas. You MUST call tools."
            ))]}
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
