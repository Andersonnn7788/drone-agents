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
            base = f"Step result: {text[:300]}"
            # Extract survivor_detected events so they're never truncated
            import json as _json
            try:
                data = _json.loads(text)
                if isinstance(data, dict):
                    disasters = data.get("recent_disasters", [])
                    survivor_alerts = [
                        f"NEW SURVIVOR at ({e['position'][0]},{e['position'][1]}) severity={e.get('severity','?')}"
                        for e in disasters
                        if e.get("type") == "survivor_detected" and e.get("position")
                    ]
                    if survivor_alerts:
                        base += " | " + "; ".join(survivor_alerts)
            except (ValueError, TypeError, KeyError):
                pass
            return base

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
                        batt = data.get("battery", "?")
                        # Multi-step response has "path" and "final_position"
                        path = data.get("path")
                        if path and len(path) > 1:
                            pos = data.get("final_position", path[-1] if path else "?")
                            return f"Moved {len(path)} steps to {pos}, battery={batt}"
                        pos = data.get("final_position") or data.get("position", "?")
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
            import json as _json
            succeeded = False
            reason = ""
            for p in parts:
                try:
                    data = _json.loads(p)
                    if isinstance(data, dict):
                        if data.get("success") is True:
                            succeeded = True
                        elif data.get("reason"):
                            reason = data["reason"]
                        elif data.get("error"):
                            reason = data["error"]
                        break
                except (ValueError, TypeError):
                    pass
            # Fallback: extract error from non-JSON text (e.g. MCP exception strings)
            if not succeeded and not reason:
                for p in parts:
                    if "error" in p.lower() or "failed" in p.lower():
                        reason = p[:120].strip()
                        break
            if succeeded:
                if data.get("already_rescued"):
                    _log_to_model(
                        "Survivor confirmed safe — already rescued.",
                        msg_type="narrative",
                        is_critical=False,
                    )
                else:
                    _log_to_model(
                        "Survivor rescued successfully.",
                        msg_type="triage",
                        is_critical=True,
                    )
            else:
                _log_to_model(
                    f"Rescue failed — {reason or 'unknown error'}.",
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
            model = get_model()
            if "discover_drones" not in model.narrated_first_calls:
                model.narrated_first_calls.add("discover_drones")
                _log_to_model(
                    f"Fleet online — {drone_count} drones reporting for duty.",
                    msg_type="narrative",
                    is_critical=True,
                )
            else:
                _log_to_model(
                    f"Fleet status refreshed — {drone_count} drones active.",
                    msg_type="narrative",
                    is_critical=False,
                )
            return True

        if tool_name == "move_to":
            # Disconnection errors — don't narrate (too noisy during blackout)
            if "disconnected" in text or "blackout" in text:
                return True
            # Charging/returning drone rejections — narrate cleanly
            if "charging" in text and "error" in text:
                _log_to_model(
                    "Command rejected — drone is charging at base. Wait for full recharge.",
                    msg_type="narrative",
                    is_critical=False,
                )
                return True
            if "returning" in text and "error" in text:
                _log_to_model(
                    "Command rejected — drone is returning to base for recharge.",
                    msg_type="narrative",
                    is_critical=False,
                )
                return True
            if "false" in text or "fail" in text or "blocked" in text or "cannot" in text:
                # Parse JSON to extract clean reason and position
                import json as _json
                reason = "unknown obstacle"
                position = ""
                for p in parts:
                    try:
                        data = _json.loads(p)
                        if isinstance(data, dict):
                            if data.get("reason"):
                                reason = data["reason"]
                            pos = data.get("final_position") or data.get("position")
                            if pos:
                                position = f" at ({pos[0]},{pos[1]})"
                            break
                    except (ValueError, TypeError):
                        pass
                _log_to_model(
                    f"Movement blocked{position} — {reason}.",
                    msg_type="narrative",
                    is_critical=True,
                )
                return True
            # Success is NOT narrated (too frequent)
            return True

        if tool_name == "coordinate_swarm":
            model = get_model()
            if "coordinate_swarm" not in model.narrated_first_calls:
                model.narrated_first_calls.add("coordinate_swarm")
                _log_to_model(
                    "Swarm sectors assigned — drones dispersing for coverage.",
                    msg_type="narrative",
                    is_critical=True,
                )
            else:
                _log_to_model(
                    "Sectors reassigned — adjusting coverage.",
                    msg_type="narrative",
                    is_critical=False,
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
                f"Drone {drone_id} recalled to base — Return-To-Base engaged.",
                msg_type="narrative",
                is_critical=True,
            )
            return True

        if tool_name == "sync_findings":
            import re as _re
            count_match = _re.search(r'"count":\s*(\d+)', full)
            count = int(count_match.group(1)) if count_match else 0
            if count > 0:
                drone_match = _re.search(r'"drone_id":\s*"([^"]+)"', full)
                drone_id = drone_match.group(1) if drone_match else "?"
                _log_to_model(
                    f"Buffered findings synced — {drone_id}: {count} reports recovered.",
                    msg_type="narrative",
                    is_critical=False,
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
            batteries = _re.findall(r'"battery":\s*(\d+)', full)
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


def _summarize_for_llm(tool_name: str, raw_content: str) -> str:
    """Produce a compact version of tool output for the LLM context.

    Reuses _summarize_tool_result() for structured summaries, falling back
    to truncated raw content (500 char limit) to keep context lean.
    """
    raw_blocks = raw_content if isinstance(raw_content, list) else [raw_content]
    summary = _summarize_tool_result(tool_name, raw_blocks)
    if summary:
        return summary
    # Fallback: truncate raw content
    text = raw_content if isinstance(raw_content, str) else str(raw_content)
    if len(text) > 500:
        return text[:500] + "...[truncated]"
    return text


def _build_situational_context(model) -> str | None:
    """Build a concise context string about active blackouts and disconnected drones."""
    if not model.blackout_zones:
        return None

    zones = ", ".join(
        f"({z['center'][0]},{z['center'][1]}) r={z['radius']}"
        for z in model.blackout_zones
    )

    disconnected = [
        d.drone_id for d in model.drones.values()
        if not d.connected and d.status == "active"
    ]

    buffered_total = sum(
        len(d.findings_buffer) for d in model.drones.values()
        if not d.connected
    )

    parts = [f"ACTIVE BLACKOUT ZONES: {zones}."]
    if disconnected:
        parts.append(f"Disconnected drones (DO NOT command): {', '.join(disconnected)}.")
        parts.append("They are operating autonomously via pheromone navigation.")
    if buffered_total > 0:
        parts.append(f"{buffered_total} buffered findings waiting — call sync_findings() when blackout clears.")
    parts.append("Focus commands on connected drones only.")

    return " ".join(parts)


def _build_rescue_urgency_context(model) -> str | None:
    """Build urgency context listing unrescued survivors sorted by steps-to-death."""
    state = model.get_state()
    survivors = state.get("survivors", [])
    stats = state.get("stats", {})
    found = stats.get("found", 0)
    rescued = stats.get("rescued", 0)

    if found <= rescued:
        return None  # No unrescued survivors

    # Collect found-but-not-rescued survivors
    unrescued = []
    for s in survivors:
        if s.get("found") and not s.get("rescued") and s.get("health", 0) > 0:
            severity = s.get("severity", "STABLE")
            health = s.get("health", 100)
            drain_rate = {"CRITICAL": 0.05, "MODERATE": 0.02, "STABLE": 0.01}.get(severity, 0.01)
            steps_to_death = int(health / drain_rate) if drain_rate > 0 else 999
            pos = s.get("position", [0, 0])
            unrescued.append({
                "id": s.get("survivor_id", "?"),
                "pos": pos,
                "severity": severity,
                "health": round(health * 100),
                "steps_to_death": steps_to_death,
            })

    if not unrescued:
        return None

    # Sort by urgency (fewest steps to death first)
    unrescued.sort(key=lambda x: x["steps_to_death"])

    # Find best connected drone for each survivor (battery-aware)
    connected_drones = [
        d for d in model.drones.values()
        if d.connected and d.status == "active"
    ]

    base_pos = (6, 5)

    lines = ["RESCUE URGENCY — found survivors bleeding out:"]
    for s in unrescued:
        drone_info = "none available"
        if connected_drones:
            candidates = []
            for d in connected_drones:
                dist_to_surv = abs(d.pos[0] - s["pos"][0]) + abs(d.pos[1] - s["pos"][1])
                move_cost = 3 * dist_to_surv  # 2 move + 1 passive per cell
                battery_after = d.battery - move_cost
                return_dist = abs(s["pos"][0] - base_pos[0]) + abs(s["pos"][1] - base_pos[1])
                return_cost = 3 * return_dist
                can_rtb = (battery_after - return_cost) >= 0
                candidates.append({
                    "drone": d, "dist": dist_to_surv,
                    "battery_after": battery_after, "can_rtb": can_rtb,
                })
            # Sort: can_rtb True first, then by distance
            candidates.sort(key=lambda c: (not c["can_rtb"], c["dist"]))
            best = candidates[0]
            bd = best["drone"]
            drone_info = (
                f"BEST: {bd.drone_id} ({bd.battery}%, {best['dist']} cells"
                f"{', can Return-To-Base' if best['can_rtb'] else ', CANNOT Return-To-Base'})"
            )
            # Warn if nearest by distance is not the recommended drone
            nearest_by_dist = min(candidates, key=lambda c: c["dist"])
            nd = nearest_by_dist["drone"]
            if nd.drone_id != bd.drone_id:
                drone_info += (
                    f" | {nd.drone_id} closer ({nearest_by_dist['dist']} cells) "
                    f"but {nd.battery}% — cannot Return-To-Base"
                )
        lines.append(
            f"  - {s['id']} at ({s['pos'][0]},{s['pos'][1]}): {s['severity']}, "
            f"health={s['health']}%, ~{s['steps_to_death']} steps to death, "
            f"{drone_info}"
        )
    lines.append("ACTION REQUIRED: move_to → rescue_survivor for each. Do NOT call info tools.")
    return "\n".join(lines)


# Base station position (must match simulation)
_BASE_POS = (6, 5)


def _build_battery_context(model) -> str | None:
    """Battery check: auto-recall critically low drones and build context for LLM.

    Returns a context string listing charging/returning drones (so LLM knows
    which drones are unavailable), or None if all drones are available.
    """
    unavailable_lines = []

    for d in model.drones.values():
        if d.status == "dead" or not d.connected:
            continue

        # Report charging drones to LLM
        if d.status == "charging":
            unavailable_lines.append(
                f"  - {d.drone_id}: CHARGING at base ({d.battery}%), "
                f"will be ready next step. Do NOT command."
            )
            continue

        # Report returning drones to LLM
        if d.status == "returning":
            dist = abs(d.pos[0] - _BASE_POS[0]) + abs(d.pos[1] - _BASE_POS[1])
            _log_to_model(
                f"Battery low — {d.drone_id} returning to base at {d.battery}%, "
                f"{dist} cells away.",
                msg_type="narrative",
                is_critical=(d.battery < 20),
            )
            unavailable_lines.append(
                f"  - {d.drone_id}: RETURNING to base ({d.battery}%), "
                f"{dist} cells away. Do NOT command."
            )
            continue

        if d.status != "active":
            continue

        dist = abs(d.pos[0] - _BASE_POS[0]) + abs(d.pos[1] - _BASE_POS[1])
        return_cost = 3 * dist  # 2/move + 1/passive per cell
        safe_battery = return_cost + 15  # match agents.py margin

        if d.battery < safe_battery:
            # Force recall — don't rely on LLM to act
            d.return_to_base()
            _log_to_model(
                f"Battery critical — {d.drone_id} at {d.battery}%, "
                f"{dist} cells from base. AUTO-RECALLED to base.",
                msg_type="narrative",
                is_critical=True,
            )
            unavailable_lines.append(
                f"  - {d.drone_id}: AUTO-RECALLED ({d.battery}%), "
                f"{dist} cells from base. Do NOT command."
            )

    if unavailable_lines:
        return (
            "BATTERY STATUS — unavailable drones (commands will be rejected):\n"
            + "\n".join(unavailable_lines)
            + "\nOnly command drones with status='active'."
        )
    return None


def _get_unscanned_clusters(model) -> dict:
    """Return building clusters not yet sufficiently scanned."""
    clusters = {
        "SW": [(2, 2), (2, 3), (3, 2), (3, 3)],
        "SE": [(9, 2), (10, 2), (10, 3)],
        "NW": [(2, 9), (2, 10), (3, 9), (3, 10)],
        "NE": [(8, 8), (8, 9), (9, 8), (9, 9)],
    }
    unscanned = {}
    for name, cells in clusters.items():
        scanned_count = sum(1 for c in cells if c in model.scanned_cells)
        if scanned_count < len(cells) // 2 + 1:
            unscanned[name] = cells
    return unscanned


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


def _format_disaster_desc(events: list) -> str:
    """Format disaster events for LLM context, enriching survivor_detected with position/severity."""
    parts = []
    for e in events:
        if e.get("type") == "survivor_detected" and e.get("position"):
            pos = e["position"]
            sev = e.get("severity", "UNKNOWN")
            parts.append(f"NEW SURVIVOR at ({pos[0]},{pos[1]}) severity={sev} — deploy nearest drone!")
        else:
            parts.append(f"{e['type']} at step {e.get('step', '?')}")
    return "; ".join(parts)


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
            affected = event.get("affected_drones", [])
            drone_list = ", ".join(affected) if affected else "unknown"
            _log_to_model(
                f"⚠ BLACKOUT at ({center[0]},{center[1]}) radius {radius} — "
                f"disconnected drones: {drone_list}. They are now autonomous. "
                f"Do NOT try to command them until blackout clears.",
                msg_type="narrative",
                is_critical=True,
            )
        elif etype == "blackout_cleared":
            buffered = sum(len(d.findings_buffer) for d in get_model().drones.values())
            if buffered > 0:
                msg = f"✓ Blackout cleared — all drones reconnected. {buffered} buffered findings available — call sync_findings() NOW."
            else:
                msg = "✓ Blackout cleared — all drones reconnected. No buffered findings."
            _log_to_model(msg, msg_type="narrative", is_critical=True)
        elif etype == "survivor_detected":
            pos = event.get("position", [0, 0])
            sev = event.get("severity", "UNKNOWN")
            _log_to_model(
                f"🆘 NEW SURVIVOR SIGNAL: {sev} survivor detected near ({pos[0]},{pos[1]})! Deploy nearest drone!",
                msg_type="narrative",
                is_critical=True,
            )
    # Track how far we've narrated
    model._narrated_disaster_count = len(model.disaster_events)
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
    msg_window = int(os.environ.get("MSG_WINDOW_SIZE", "40"))

    # Step limit from env
    max_steps = int(os.environ.get("MAX_MISSION_STEPS", "50"))

    # Demo mode flag
    demo_mode = os.environ.get("DEMO_MODE", "0") == "1"

    # Minimum steps in demo mode — must run past all scripted events (last wave at step 11)
    MIN_DEMO_STEPS = 14

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

        # Remove stale injected SystemMessages (disaster alerts, warnings, checkpoints)
        # These are re-injected fresh each call, so old copies are pure context waste
        _stale_prefixes = (
            "⚠ DISASTER ALERT:",
            "⚠ DISASTER WARNING:",
            "PERFORMANCE CHECKPOINT",
            "CRITICAL WARNING:",
            "WARNING: Info-loop",
            "WARNING: You have been",
            "RESCUE URGENCY",
            "ACTIVE BLACKOUT ZONES:",
            "BATTERY STATUS",
            "BATTERY CRITICAL:",
            "BATTERY CAUTION:",
            "BATTERY OK:",
        )
        messages = [
            m for i, m in enumerate(messages)
            if not (
                isinstance(m, SystemMessage)
                and i > 0
                and any(m.content.startswith(prefix) for prefix in _stale_prefixes)
            )
        ]

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

        # Inject blackout situational awareness (zero tool-call cost)
        ctx = _build_situational_context(model)
        if ctx:
            messages.append(SystemMessage(content=ctx))

        # Inject rescue urgency when found > rescued
        urgency = _build_rescue_urgency_context(model)
        if urgency:
            messages.append(SystemMessage(content=urgency))

        # Battery check: auto-recall critically low drones + inform LLM
        battery_ctx = _build_battery_context(model)
        if battery_ctx:
            messages.append(SystemMessage(content=battery_ctx))

        response = llm_with_tools.invoke(messages)

        # Log LLM reasoning text (handle str, list of content blocks, or None)
        reasoning_text = ""
        if isinstance(response.content, str):
            reasoning_text = response.content.strip()
        elif isinstance(response.content, list):
            # Extract text from content blocks like {"type": "text", "text": "..."}
            text_parts = []
            for block in response.content:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    text_parts.append(block["text"])
                elif isinstance(block, str):
                    text_parts.append(block)
            reasoning_text = " ".join(text_parts).strip()

        if reasoning_text:
            _log_to_model(reasoning_text, msg_type="reasoning")
        elif response.tool_calls:
            # No reasoning text but tool calls exist — synthesize a brief entry
            tool_names = ", ".join(tc["name"] for tc in response.tool_calls)
            _log_to_model(f"Executing: {tool_names}", msg_type="reasoning")

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
        """Execute tool calls with parallel execution for different drones.

        Tool calls targeting different drone_ids run concurrently via
        asyncio.gather(). Calls within the same drone group stay sequential
        (order matters). Global tools (no drone_id) run after all drone
        groups complete. SSE pacing for move_to is preserved per-group."""
        last_ai_msg = state["messages"][-1]
        if not hasattr(last_ai_msg, "tool_calls") or not last_ai_msg.tool_calls:
            return {"messages": []}

        # --- Helper: execute a single tool call ---
        async def _execute_one(tc):
            tool = tools_by_name.get(tc["name"])
            pre_disaster = None
            pre_warning = None
            if tc["name"] == "advance_simulation":
                pre_disaster = len(get_model().disaster_events)
                pre_warning = len(get_model().warning_events)

            if tool is None:
                raw_content = f"Error: tool '{tc['name']}' not found"
                msg = ToolMessage(
                    content=raw_content,
                    tool_call_id=tc["id"],
                    name=tc["name"],
                )
            else:
                try:
                    result = await tool.ainvoke(tc["args"])
                    raw_content = _normalize_tool_result(result)
                    llm_content = _summarize_for_llm(tc["name"], raw_content)
                    msg = ToolMessage(
                        content=llm_content,
                        tool_call_id=tc["id"],
                        name=tc["name"],
                    )
                except Exception as e:
                    raw_content = f"Error: {e}"
                    msg = ToolMessage(
                        content=raw_content,
                        tool_call_id=tc["id"],
                        name=tc["name"],
                    )
            return msg, raw_content, pre_disaster, pre_warning

        # --- Helper: execute a group of tool calls sequentially ---
        async def _execute_group(calls):
            group_results = []
            for idx, tc in calls:
                msg, raw_content, pre_d, pre_w = await _execute_one(tc)
                # Pace single-step move_to so SSE can broadcast positions
                if tc["name"] == "move_to":
                    await asyncio.sleep(0.35)
                group_results.append((idx, tc, msg, raw_content, pre_d, pre_w))
            return group_results

        # --- Group tool calls by drone_id for parallel execution ---
        groups = {}  # drone_id -> [(original_index, tc)]
        for idx, tc in enumerate(last_ai_msg.tool_calls):
            drone_id = tc.get("args", {}).get("drone_id")
            group_key = drone_id if drone_id else "_global"
            groups.setdefault(group_key, []).append((idx, tc))

        global_calls = groups.pop("_global", [])
        drone_groups = list(groups.values())

        # Execute drone groups in parallel, then global calls sequentially
        all_results = []
        if drone_groups:
            gathered = await asyncio.gather(
                *[_execute_group(g) for g in drone_groups]
            )
            for group_result in gathered:
                all_results.extend(group_result)

        if global_calls:
            global_result = await _execute_group(global_calls)
            all_results.extend(global_result)

        # Sort by original index to preserve order for LLM context
        all_results.sort(key=lambda x: x[0])

        # --- Post-process results: logging, narrative, disaster detection ---
        # Split into tool messages and system messages to avoid OpenAI 400 error
        # (SystemMessage interleaved between ToolMessages violates API contract)
        tool_messages = []
        system_messages = []
        for idx, tc, msg, raw_content, pre_disaster, pre_warning in all_results:
            tool_messages.append(msg)

            raw_blocks = raw_content if isinstance(raw_content, list) else [raw_content]

            summary = _summarize_tool_result(msg.name, raw_blocks)
            if summary:
                content = summary
            else:
                text = raw_content if isinstance(raw_content, str) else str(raw_content)
                content = text[:300] + "..." if len(text) > 300 else text

            narrated = _emit_narrative(msg.name, raw_blocks)
            if not narrated:
                _log_to_model(
                    f"Result [{msg.name}]: {content}",
                    msg_type="result",
                )

            # Post-move battery safety net: force-recall if battery critically low
            if msg.name == "move_to":
                import json as _json
                try:
                    move_data = _json.loads(raw_content if isinstance(raw_content, str) else str(raw_content))
                    if isinstance(move_data, dict):
                        batt = move_data.get("battery")
                        drone_id = tc.get("args", {}).get("drone_id", "?")
                        if batt is not None and batt < 25:
                            sim_model = get_model()
                            drone_obj = sim_model.drones.get(drone_id)
                            if drone_obj:
                                dist = abs(drone_obj.pos[0] - 6) + abs(drone_obj.pos[1] - 5)
                                return_cost = 3 * dist
                                if batt < return_cost + 5:
                                    # Force-recall the drone, not just warn
                                    if drone_obj.status == "active":
                                        drone_obj.return_to_base()
                                    system_messages.append(SystemMessage(content=(
                                        f"BATTERY CRITICAL: {drone_id} at {batt}% after move, "
                                        f"{dist} cells from base. AUTO-RECALLED — do NOT command it."
                                    )))
                except (ValueError, TypeError, KeyError):
                    pass

            if pre_disaster is not None:
                new_disasters = _check_new_disasters(pre_disaster)
                if new_disasters:
                    disaster_desc = _format_disaster_desc(new_disasters)
                    system_messages.append(SystemMessage(content=(
                        f"⚠ DISASTER ALERT: {disaster_desc}. "
                        "Check affected areas, reroute drones if needed, and report status."
                    )))

            if pre_warning is not None:
                new_warnings = get_model().warning_events[pre_warning:]
                if new_warnings:
                    desc = "; ".join(w["message"] for w in new_warnings if not w.get("resolved"))
                    if desc:
                        _log_to_model(
                            f"⚠ WARNING: {desc}",
                            msg_type="warning",
                            is_critical=True,
                        )
                        system_messages.append(SystemMessage(content=(
                            f"⚠ DISASTER WARNING: {desc}. You have ~1 step to react!"
                        )))

        # Auto-advance simulation if batch had actions but no explicit advance
        tool_names_in_batch = {tc["name"] for tc in last_ai_msg.tool_calls}
        has_action = tool_names_in_batch & {"move_to", "thermal_scan", "rescue_survivor"}
        has_advance = "advance_simulation" in tool_names_in_batch
        if has_action and not has_advance:
            sim_model = get_model()
            if sim_model.mission_step < max_steps:
                prev_disaster_count = len(sim_model.disaster_events)
                prev_warning_count = len(sim_model.warning_events)
                sim_model.step()
                _log_to_model(f"Auto-step → step {sim_model.mission_step}", msg_type="system")
                await asyncio.sleep(0.60)
                new_disasters = _check_new_disasters(prev_disaster_count)
                if new_disasters:
                    disaster_desc = _format_disaster_desc(new_disasters)
                    system_messages.append(SystemMessage(content=(
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
                        system_messages.append(SystemMessage(content=(
                            f"⚠ DISASTER WARNING: {desc}. You have ~1 step to react!"
                        )))

        # Mid-mission reflection checkpoints
        REFLECTION_INTERVAL = 8 if max_steps <= 20 else 5
        model = get_model()
        if model.mission_step > 0 and model.mission_step % REFLECTION_INTERVAL == 0:
            score = model.compute_score()
            _log_to_model(
                f"PERFORMANCE CHECKPOINT (step {model.mission_step}): "
                f"Score={score['total']}, Grade={score['grade']}",
                msg_type="reflection",
                is_critical=True,
            )
            system_messages.append(SystemMessage(content=(
                f"PERFORMANCE CHECKPOINT — Step {model.mission_step}\n"
                f"Score: {score['total']} pts (Grade: {score['grade']})\n"
                f"Breakdown: rescue={score['rescue_points']}, speed_bonus={score['speed_bonus']}, "
                f"coverage={score['coverage_bonus']}, death_penalty={score['death_penalty']}\n"
                f"REFLECT: What is working? What should change? "
                f"Are you prioritizing the right survivors? Is drone coverage efficient?"
            )))

        # If agent is stuck in info-only loop, inject a warning to take action
        if info_loop.get("warn"):
            model = get_model()
            urgency = _build_rescue_urgency_context(model)
            if urgency:
                system_messages.append(SystemMessage(content=(
                    "CRITICAL WARNING: You are stuck in an info-gathering loop while survivors are DYING.\n"
                    f"{urgency}\n"
                    "Your ONLY acceptable next calls are move_to() and rescue_survivor(). "
                    "Do NOT call get_mission_summary, get_priority_map, assess_survivor, or any other info tool."
                )))
            else:
                # All found survivors rescued but some unfound — give scan directives
                unscanned = _get_unscanned_clusters(model)
                if unscanned:
                    # Build specific drone→cluster assignments
                    connected = [
                        d for d in model.drones.values()
                        if d.connected and d.status == "active"
                    ]
                    cluster_names = list(unscanned.keys())
                    orders = []
                    for i, drone in enumerate(connected):
                        if i < len(cluster_names):
                            cname = cluster_names[i]
                            target = unscanned[cname][0]
                            orders.append(
                                f"- Send {drone.drone_id} to {cname} cluster at ({target[0]},{target[1]}), "
                                f"call thermal_scan"
                            )
                    cluster_list = ", ".join(cluster_names)
                    orders_str = "\n".join(orders) if orders else "- Move available drones to unscanned clusters and scan"
                    system_messages.append(SystemMessage(content=(
                        f"WARNING: Info-loop detected. {model.get_state()['stats']['total_survivors'] - model.get_state()['stats']['found']} survivors still UNFOUND.\n"
                        f"UNSCANNED CLUSTERS: {cluster_list}\n"
                        f"ORDERS:\n{orders_str}\n"
                        "Execute move_to() and thermal_scan() NOW. Do NOT call info tools."
                    )))
                else:
                    system_messages.append(SystemMessage(content=(
                        "WARNING: You have been calling info-only tools repeatedly without taking action. "
                        "STOP querying and START acting. Move drones, scan areas, or rescue survivors NOW. "
                        "Use move_to(), thermal_scan(), or rescue_survivor() — not get_mission_summary()."
                    )))

        return {"messages": tool_messages + system_messages}

    # Track nudge count to prevent infinite loops
    # n = consecutive nudges, total = total nudges this step, step = last seen step
    nudge_count = {"n": 0, "total": 0, "step": 0}
    MAX_NUDGES = 5
    MAX_TOTAL_NUDGES = 10

    # Info-only tools don't advance mission state — detect stuck loops
    INFO_ONLY_TOOLS = {
        "get_mission_summary", "get_priority_map", "get_pheromone_map",
        "get_battery_status", "get_disaster_events", "get_network_resilience",
        "get_performance_score", "discover_drones", "simulate_mission",
        "assess_survivor", "coordinate_swarm",
    }
    info_loop = {"n": 0, "warn": False, "total_resets": 0}
    MAX_INFO_LOOPS = 3
    MAX_INFO_RESETS = 2
    INFO_WARN_THRESHOLD = 2

    def should_continue(state: MessagesState):
        """Custom routing: detects premature stops and nudges the agent back."""
        last_msg = state["messages"][-1]

        # ALWAYS enforce step limit, regardless of tool call type
        model = get_model()
        if model.mission_step >= max_steps:
            # Flush any remaining unnarrated disaster events
            narrated_count = getattr(model, '_narrated_disaster_count', 0)
            if narrated_count < len(model.disaster_events):
                _check_new_disasters(narrated_count)
            _log_to_model(
                f"Step limit ({max_steps}) reached — ending mission.",
                msg_type="system", is_critical=True,
            )
            return END

        # If LLM made tool calls, check if they are productive or info-only
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            tool_names = {tc["name"] for tc in last_msg.tool_calls}
            has_productive = bool(tool_names - INFO_ONLY_TOOLS)

            if has_productive:
                nudge_count["n"] = 0  # Reset on productive tool use
                nudge_count["total"] = 0
                info_loop["n"] = 0
                info_loop["warn"] = False
                return "tools"
            else:
                # Info-only tools — check for stuck loop
                info_loop["n"] += 1
                if info_loop["n"] >= INFO_WARN_THRESHOLD:
                    info_loop["warn"] = True
                if info_loop["n"] >= MAX_INFO_LOOPS:
                    # Before ending, check if there are unrescued survivors with active drones
                    model = get_model()
                    state_data = model.get_state()
                    stats = state_data.get("stats", {})
                    found = stats.get("found", 0)
                    rescued = stats.get("rescued", 0)
                    unfound = stats.get("total_survivors", 0) - found
                    active = stats.get("active_drones", 0)
                    if active > 0 and (found > rescued or unfound > 0):
                        # Survivors still need help — reset but cap total resets
                        info_loop["total_resets"] += 1
                        if info_loop["total_resets"] <= MAX_INFO_RESETS:
                            _log_to_model(
                                f"Info-loop detected ({info_loop['n']} rounds) but "
                                f"{found - rescued} found-not-rescued, {unfound} unfound — "
                                f"reset {info_loop['total_resets']}/{MAX_INFO_RESETS}.",
                                msg_type="system",
                                is_critical=True,
                            )
                            info_loop["n"] = 0
                            info_loop["warn"] = True  # Keep warning active
                            return "tools"
                        else:
                            _log_to_model(
                                f"Info-loop persists after {MAX_INFO_RESETS} resets — ending mission.",
                                msg_type="system",
                                is_critical=True,
                            )
                            return END
                    _log_to_model(
                        f"Agent stuck in info-query loop ({info_loop['n']} consecutive "
                        f"info-only rounds) — ending mission.",
                        msg_type="system",
                        is_critical=True,
                    )
                    return END
                # Still allow info calls but don't reset nudge counter
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
                if model.mission_step < max_steps:
                    prev_d = len(model.disaster_events)
                    prev_w = len(model.warning_events)
                    _log_to_model(
                        f"Agent unresponsive after {MAX_TOTAL_NUDGES} nudges at step "
                        f"{model.mission_step} — force-advancing simulation.",
                        msg_type="system",
                        is_critical=True,
                    )
                    model.step()
                    # Flush any disasters/warnings triggered by force-advance
                    _check_new_disasters(prev_d)
                    new_w = model.warning_events[prev_w:]
                    if new_w:
                        desc = "; ".join(w["message"] for w in new_w if not w.get("resolved"))
                        if desc:
                            _log_to_model(f"⚠ WARNING: {desc}", msg_type="warning", is_critical=True)
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
            # Before ending, check if survivors still need help
            if (stats.get("found", 0) > stats.get("rescued", 0) or
                    stats.get("total_survivors", 0) - stats.get("found", 0) > 0) and \
                    stats.get("active_drones", 0) > 0:
                _log_to_model(
                    f"Max nudges reached but survivors remain — resetting nudge counter.",
                    msg_type="system",
                    is_critical=True,
                )
                nudge_count["n"] = 0
                return "nudge"
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
        connected_drones = [d for d in model.drones.values() if d.connected and d.status == "active"]
        connected_ids = [d.drone_id for d in connected_drones]
        blackout_hint = ""
        if model.blackout_zones:
            blackout_hint = f" Blackout active — command only: {', '.join(connected_ids)}."

        # Build survivor-specific nudge when unrescued survivors exist
        urgency = _build_rescue_urgency_context(model)
        survivor_hint = ""
        if urgency:
            survivor_hint = f"\n{urgency}"

        # Build cluster scan directives when survivors are still unfound
        cluster_hint = ""
        unscanned = _get_unscanned_clusters(model)
        if unscanned and not urgency:
            cluster_names = list(unscanned.keys())
            orders = []
            for i, drone in enumerate(connected_drones):
                if i < len(cluster_names):
                    cname = cluster_names[i]
                    target = unscanned[cname][0]
                    orders.append(
                        f"- {drone.drone_id} → {cname} cluster ({target[0]},{target[1]}), thermal_scan"
                    )
            if orders:
                cluster_hint = "\nUNSCANNED CLUSTERS: " + ", ".join(cluster_names) + "\n" + "\n".join(orders)

        if demo_mode and model.mission_step < MIN_DEMO_STEPS:
            return {"messages": [SystemMessage(content=(
                f"CONTINUE OPERATING. Step {model.mission_step}/{MIN_DEMO_STEPS}. "
                "Move drones toward building clusters, thermal_scan, rescue survivors. "
                "Batch all move_to + scan + rescue in one response. You MUST call tools."
                + blackout_hint + survivor_hint + cluster_hint
            ))]}
        return {"messages": [SystemMessage(content=(
            "DO NOT STOP. The mission is NOT complete — there are still survivors "
            "to find and rescue. You are FULLY AUTONOMOUS with no human operator. "
            "Make the best decision and execute it NOW. You MUST call tools. "
            "Do NOT re-call discover_drones() or coordinate_swarm() — focus on moving, scanning, and rescuing."
            + blackout_hint + survivor_hint + cluster_hint
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
