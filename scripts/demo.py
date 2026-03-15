"""
demo.py — 5-Act Demo Script for Drone Swarm Rescue Simulation
═══════════════════════════════════════════════════════════════
Drives the API with timed pauses, designed for live narration.
Prerequisite: all 4 services running (use scripts/run_all.sh).

Usage:
    python scripts/demo.py
"""

import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

API = "http://localhost:8001"
STEP_PAUSE = 2.0  # seconds between auto-steps


def banner(text: str) -> None:
    width = 60
    print()
    print("=" * width)
    print(f"  {text}".center(width))
    print("=" * width)
    print()


def check_connection() -> bool:
    try:
        r = requests.get(f"{API}/api/state", timeout=3)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


def get_state() -> dict:
    return requests.get(f"{API}/api/state", timeout=5).json()


def print_stats(label: str = "Current Status") -> None:
    state = get_state()
    stats = state.get("stats", {})
    step = state.get("mission_step", 0)
    drones = state.get("drones", {})

    active = sum(1 for d in drones.values() if d.get("status") != "dead")
    connected = sum(1 for d in drones.values() if d.get("connected", False))

    print(f"\n  ┌─ {label} (Step {step}) ─────────────────────")
    print(f"  │ Survivors: {stats.get('found', 0)}/{stats.get('total_survivors', '?')} found, "
          f"{stats.get('rescued', 0)} rescued, {stats.get('alive', '?')} alive")
    print(f"  │ Coverage:  {stats.get('coverage_pct', 0)}% ({stats.get('cells_scanned', 0)}/{stats.get('total_cells', 144)} cells)")
    print(f"  │ Drones:    {active}/{stats.get('total_drones', 4)} active, {connected} connected")

    for did, d in drones.items():
        name = did.replace("drone_", "").capitalize()
        print(f"  │   {name}: bat={d.get('battery', '?')}% pos={d.get('position', '?')} "
              f"status={d.get('status', '?')} {'[RELAY]' if d.get('is_relay') else ''}"
              f"{'[DISCO]' if not d.get('connected') else ''}")

    print(f"  └──────────────────────────────────────────\n")


def step(n: int = 1) -> None:
    requests.post(f"{API}/api/step", json={"steps": n}, timeout=10)


def start_mission() -> None:
    requests.post(f"{API}/api/start", timeout=10)


def trigger_blackout(zone_x: int, zone_y: int, radius: int) -> None:
    requests.post(f"{API}/api/blackout",
                  json={"zone_x": zone_x, "zone_y": zone_y, "radius": radius},
                  timeout=10)


def wait_steps(n: int, pause: float = STEP_PAUSE) -> None:
    """Advance n steps with pauses for narration."""
    for i in range(n):
        step(1)
        time.sleep(pause)
        if (i + 1) % 5 == 0:
            print_stats(f"After {i + 1} steps")


# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    banner("DRONE SWARM RESCUE — LIVE DEMO")

    print("Checking API connection...")
    if not check_connection():
        print(f"ERROR: Cannot reach API at {API}")
        print("Start all services first: bash scripts/run_all.sh")
        sys.exit(1)
    print("Connected!\n")

    # ── Act 1: Discovery ─────────────────────────────────────────────
    banner("ACT 1 — DISCOVERY")
    print("Starting mission. The LLM Commander will discover drones,")
    print("analyze the disaster zone, and deploy the swarm...\n")

    start_mission()
    time.sleep(3)  # Let agent initialize and call discover_drones

    print("Mission started. Agent is deploying drones to sectors...")
    wait_steps(6, 2.5)
    print_stats("After Initial Deployment")

    input("\n  Press Enter to continue to Act 2...\n")

    # ── Act 2: Living Disaster ───────────────────────────────────────
    banner("ACT 2 — THE LIVING DISASTER")
    print("Drones are scanning the grid, finding survivors.")
    print("Watch for triage decisions and aftershock events...\n")

    wait_steps(10, 2.0)
    print_stats("Mid-Mission")

    input("\n  Press Enter to continue to Act 3...\n")

    # ── Act 3: Communication Crisis ──────────────────────────────────
    banner("ACT 3 — COMMUNICATION CRISIS")
    print("Triggering a communication blackout at zone (8, 8) radius 3.")
    print("Drones in the blackout zone will lose contact and go autonomous.\n")

    time.sleep(1)
    trigger_blackout(8, 8, 3)
    print("BLACKOUT DEPLOYED! Watch the dashboard for disconnected drones.\n")

    wait_steps(8, 2.5)
    print_stats("During Blackout")

    input("\n  Press Enter to continue to Act 4...\n")

    # ── Act 4: Race Against Time ─────────────────────────────────────
    banner("ACT 4 — RACE AGAINST TIME")
    print("Battery levels dropping. Survivors losing health.")
    print("The agent must make critical triage decisions...\n")

    wait_steps(10, 2.0)
    print_stats("Late Mission")

    input("\n  Press Enter to continue to Act 5...\n")

    # ── Act 5: Victory & Replay ──────────────────────────────────────
    banner("ACT 5 — MISSION COMPLETE")

    # Run remaining steps
    wait_steps(6, 1.5)
    print_stats("FINAL RESULTS")

    print("The mission is complete!")
    print()
    print("Use the Timeline Slider in the dashboard to replay the entire")
    print("mission step-by-step. Toggle Voice Narration to hear critical")
    print("events spoken aloud.")
    print()
    print("Thank you for watching!")

    banner("END OF DEMO")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDemo interrupted. Goodbye!")
    except requests.ConnectionError:
        print(f"\nERROR: Lost connection to API at {API}")
        print("Make sure all services are still running.")
        sys.exit(1)
