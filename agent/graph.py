"""LangGraph StateGraph factory — builds the agent + tool-calling loop."""

import asyncio
import os
import re
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END

from simulation.state import get_model
from .prompts import SYSTEM_PROMPT, build_adaptive_prompt
from .memory import load_lessons, format_lessons_for_prompt, get_mission_count


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

        if tool_name == "move_to":
            import json as _json
            for p in parts:
                try:
                    data = _json.loads(p)
                    if isinstance(data, dict):
                        ok = data.get("success", False)
                        pos = data.get("position", "?")
                        batt = data.get("battery", "?")
                        if ok:
                            return f"Moved to {pos}, battery={batt}"
                        return f"Move failed: {data.get('reason', '?')}"
                except (ValueError, TypeError):
                    pass
            return f"move_to: {parts[0][:100]}" if parts else None

        if tool_name == "get_performance_score":
            import json as _json
            for p in parts:
                try:
                    data = _json.loads(p)
                    if isinstance(data, dict):
                        return (
                            f"Score: {data.get('total', 0)} pts (grade {data.get('grade', '?')}), "
                            f"{data.get('mission_progress_pct', 0)}% through mission"
                        )
                except (ValueError, TypeError):
                    pass
            return None

        if tool_name == "coordinate_swarm":
            import json as _json
            for p in parts:
                try:
                    data = _json.loads(p)
                    if isinstance(data, dict) and data.get("assignments"):
                        assigns = data["assignments"]
                        summary = ", ".join(f"{k}→{v}" for k, v in assigns.items())
                        return f"Sectors: {summary}"
                except (ValueError, TypeError):
                    pass
            return f"Swarm: {parts[0][:150]}" if parts else None

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

        if tool_name == "get_performance_score":
            _log_to_model(
                "Performance checkpoint — reviewing mission effectiveness.",
                msg_type="reflection",
                is_critical=True,
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


def _normalize_tool_result(result) -> str:
    """Convert MCP tool result to a plain string for ToolMessage.content."""
    import json as _json
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, int, float, bool)):
        return _json.dumps(result)
    # MCP content blocks (list of TextContent objects)
    if isinstance(result, list):
        parts = []
        for block in result:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    # Single MCP TextContent object
    if hasattr(result, "text"):
        return result.text
    return str(result)


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


def _check_new_disasters(prev_count: int) -> list:
    """Check for disasters that occurred since prev_count and emit narrative logs.

    Returns the list of new disaster events (may be empty).
    """
    model = get_model()
    new_events = model.disaster_events[prev_count:]
    for event in new_events:
        etype = event.get("type", "unknown")
        if etype == "aftershock":
            center = event.get("center", "?")
            cells = event.get("affected_cells", [])
            _log_to_model(
                f"⚠ AFTERSHOCK at ({center[0]},{center[1]}) — {len(cells)} cells converted to DEBRIS. Reroute drones!",
                msg_type="narrative",
                is_critical=True,
            )
        elif etype == "rising_water":
            flooded = event.get("flooded_cells", [])
            _log_to_model(
                f"⚠ RISING WATER — {len(flooded)} cells flooded. Check for survivors in danger!",
                msg_type="narrative",
                is_critical=True,
            )
        elif etype == "blackout":
            center = event.get("center", "?")
            radius = event.get("radius", "?")
            _log_to_model(
                f"⚠ BLACKOUT at ({center[0]},{center[1]}) radius {radius} — affected drones switching to autonomous mode.",
                msg_type="narrative",
                is_critical=True,
            )
        elif etype == "blackout_cleared":
            _log_to_model(
                "✓ Blackout cleared — call sync_findings() to recover buffered data.",
                msg_type="narrative",
                is_critical=True,
            )
    return new_events


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
    max_tok = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
    llm = ChatOpenAI(model=model_name, temperature=0.1, max_tokens=max_tok)
    llm_with_tools = llm.bind_tools(tools)

    tools_by_name = {tool.name: tool for tool in tools}

    # Message window size (0 = disabled)
    msg_window = int(os.environ.get("MSG_WINDOW_SIZE", "0"))

    # Step limit from env
    max_steps = int(os.environ.get("MAX_MISSION_STEPS", "50"))

    # Demo mode flag
    demo_mode = os.environ.get("DEMO_MODE", "0") == "1"

    # Minimum steps in demo mode — must run past all scripted events (last at step 7)
    MIN_DEMO_STEPS = 8

    # Select prompt with adaptive intelligence
    if demo_mode:
        from .prompts import DEMO_SYSTEM_PROMPT
        base_prompt = DEMO_SYSTEM_PROMPT
    else:
        base_prompt = SYSTEM_PROMPT

    lessons = load_lessons()
    lessons_block = format_lessons_for_prompt(lessons)
    mission_num = get_mission_count() + 1
    system_prompt = build_adaptive_prompt(base_prompt, lessons_block, mission_num)

    if lessons:
        print(f"  [Adaptive] Mission #{mission_num} — loaded {len(lessons)} lessons from past missions")

    def agent_node(state: MessagesState):
        messages = list(state["messages"])

        # Prepend system prompt if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages.insert(0, SystemMessage(content=system_prompt))

        # Sliding window: keep system prompt + last N messages (preserving tool pairs)
        messages = _trim_messages(messages, msg_window)

        # Filter stale nudge SystemMessages — keep only the most recent one
        # Nudge messages start with "CONTINUE OPERATING" or "DO NOT STOP"
        nudge_indices = [
            i for i, m in enumerate(messages)
            if isinstance(m, SystemMessage)
            and i > 0  # never touch the system prompt at index 0
            and (m.content.startswith("CONTINUE OPERATING")
                 or m.content.startswith("DO NOT STOP"))
        ]
        if len(nudge_indices) > 1:
            # Remove all but the last nudge message
            stale = set(nudge_indices[:-1])
            messages = [m for i, m in enumerate(messages) if i not in stale]

        # Enforce step limit using actual simulation step counter
        model = get_model()
        if model.mission_step >= max_steps:
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
        """Execute tool calls sequentially with pacing so SSE can broadcast
        intermediate drone positions (prevents the 'teleport' effect)."""
        last_ai_msg = state["messages"][-1]
        if not hasattr(last_ai_msg, "tool_calls") or not last_ai_msg.tool_calls:
            return {"messages": []}

        results = []
        for tc in last_ai_msg.tool_calls:
            tool = tools_by_name.get(tc["name"])

            # Track disaster and warning counts before advance_simulation
            pre_advance_disaster_count = None
            pre_advance_warning_count = None
            if tc["name"] == "advance_simulation":
                pre_advance_disaster_count = len(get_model().disaster_events)
                pre_advance_warning_count = len(get_model().warning_events)

            if tool is None:
                msg = ToolMessage(
                    content=f"Error: tool '{tc['name']}' not found",
                    tool_call_id=tc["id"],
                    name=tc["name"],
                )
            else:
                try:
                    result = await tool.ainvoke(tc["args"])
                    msg = ToolMessage(
                        content=_normalize_tool_result(result),
                        tool_call_id=tc["id"],
                        name=tc["name"],
                    )
                except Exception as e:
                    msg = ToolMessage(
                        content=f"Error: {e}",
                        tool_call_id=tc["id"],
                        name=tc["name"],
                    )

            results.append(msg)

            # Log tool result with smart summarization
            raw = msg.content
            raw_blocks = raw if isinstance(raw, list) else [raw]

            summary = _summarize_tool_result(msg.name, raw_blocks)
            if summary:
                content = summary
            else:
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

            narrated = _emit_narrative(msg.name, raw_blocks)
            if not narrated:
                _log_to_model(
                    f"Result [{msg.name}]: {content}",
                    msg_type="result",
                )

            # Check for new disasters after explicit advance_simulation
            if pre_advance_disaster_count is not None:
                new_disasters = _check_new_disasters(pre_advance_disaster_count)
                if new_disasters:
                    disaster_desc = "; ".join(
                        f"{e['type']} at step {e.get('step', '?')}" for e in new_disasters
                    )
                    results.append(SystemMessage(content=(
                        f"⚠ DISASTER ALERT: {disaster_desc}. "
                        "Check affected areas, reroute drones if needed, and report status."
                    )))

            # Check for new warnings after advance_simulation
            if pre_advance_warning_count is not None:
                new_warnings = get_model().warning_events[pre_advance_warning_count:]
                if new_warnings:
                    desc = "; ".join(w["message"] for w in new_warnings if not w.get("resolved"))
                    if desc:
                        _log_to_model(
                            f"⚠ WARNING: {desc}",
                            msg_type="warning",
                            is_critical=True,
                        )
                        results.append(SystemMessage(content=(
                            f"⚠ DISASTER WARNING: {desc}. You have ~1 step to react!"
                        )))

            # Pace move_to calls so SSE can broadcast intermediate positions
            if tc["name"] == "move_to":
                await asyncio.sleep(0.25)

        # Auto-advance simulation if batch had actions but no explicit advance
        tool_names_in_batch = {tc["name"] for tc in last_ai_msg.tool_calls}
        has_action = tool_names_in_batch & {"move_to", "thermal_scan", "rescue_survivor"}
        has_advance = "advance_simulation" in tool_names_in_batch
        if has_action and not has_advance:
            sim_model = get_model()
            prev_disaster_count = len(sim_model.disaster_events)
            prev_warning_count = len(sim_model.warning_events)
            sim_model.step()
            _log_to_model(f"Auto-step → step {sim_model.mission_step}", msg_type="system")
            new_disasters = _check_new_disasters(prev_disaster_count)
            if new_disasters:
                disaster_desc = "; ".join(
                    f"{e['type']} at step {e.get('step', '?')}" for e in new_disasters
                )
                results.append(SystemMessage(content=(
                    f"⚠ DISASTER ALERT: {disaster_desc}. "
                    "Check affected areas, reroute drones if needed, and report status."
                )))
            # Check for new warnings after auto-advance
            new_warnings = sim_model.warning_events[prev_warning_count:]
            if new_warnings:
                desc = "; ".join(w["message"] for w in new_warnings if not w.get("resolved"))
                if desc:
                    _log_to_model(
                        f"⚠ WARNING: {desc}",
                        msg_type="warning",
                        is_critical=True,
                    )
                    results.append(SystemMessage(content=(
                        f"⚠ DISASTER WARNING: {desc}. You have ~1 step to react!"
                    )))

        # Mid-mission reflection checkpoints
        REFLECTION_INTERVAL = 5
        model = get_model()
        if model.mission_step > 0 and model.mission_step % REFLECTION_INTERVAL == 0:
            score = model.compute_score()
            _log_to_model(
                f"PERFORMANCE CHECKPOINT (step {model.mission_step}): "
                f"Score={score['total']}, Grade={score['grade']}",
                msg_type="reflection",
                is_critical=True,
            )
            results.append(SystemMessage(content=(
                f"PERFORMANCE CHECKPOINT — Step {model.mission_step}\n"
                f"Score: {score['total']} pts (Grade: {score['grade']})\n"
                f"Breakdown: rescue={score['rescue_points']}, speed_bonus={score['speed_bonus']}, "
                f"coverage={score['coverage_bonus']}, death_penalty={score['death_penalty']}\n"
                f"REFLECT: What is working? What should change? "
                f"Are you prioritizing the right survivors? Is drone coverage efficient?"
            )))

        return {"messages": results}

    # Track nudge count to prevent infinite loops
    # n = consecutive nudges, total = total nudges this step, step = last seen step
    nudge_count = {"n": 0, "total": 0, "step": 0}
    MAX_NUDGES = 3
    MAX_TOTAL_NUDGES = 6

    def should_continue(state: MessagesState):
        """Custom routing: detects premature stops and nudges the agent back."""
        last_msg = state["messages"][-1]

        # If LLM made tool calls, proceed normally (execute tools)
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            nudge_count["n"] = 0  # Reset on successful tool use
            nudge_count["total"] = 0
            return "tools"

        # LLM stopped calling tools — check if mission is actually complete
        model = get_model()

        # Reset total counter when simulation advances to a new step
        if model.mission_step != nudge_count["step"]:
            nudge_count["total"] = 0
            nudge_count["step"] = model.mission_step

        # Mission step limit reached
        if model.mission_step >= max_steps:
            return END

        # In demo mode, don't allow early exit before scripted events have fired
        if demo_mode and model.mission_step < MIN_DEMO_STEPS:
            nudge_count["n"] += 1
            nudge_count["total"] += 1
            if nudge_count["n"] >= MAX_NUDGES:
                nudge_count["n"] = 0  # Reset consecutive counter

            # Hard cap: if total nudges exceeded, force-advance the simulation
            if nudge_count["total"] >= MAX_TOTAL_NUDGES:
                _log_to_model(
                    f"Agent unresponsive after {MAX_TOTAL_NUDGES} nudges at step "
                    f"{model.mission_step} — force-advancing simulation.",
                    msg_type="system",
                    is_critical=True,
                )
                model.step()
                nudge_count["n"] = 0
                nudge_count["total"] = 0
                nudge_count["step"] = model.mission_step

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
