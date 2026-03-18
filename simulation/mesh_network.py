"""Mesh network topology, blackout handling, relay paths, and resilience analysis."""

from collections import deque


def manhattan_distance(pos1, pos2):
    return abs(pos1[0] - pos2[0]) + abs(pos1[1] - pos2[1])


def compute_mesh_topology(drones, base_pos=(6, 5)):
    """Build adjacency graph using Manhattan distance and comm_range.
    Update each drone's connected status via BFS from base.

    Returns adjacency dict: {drone_id: [neighbor_ids]}
    """
    drone_list = list(drones.values()) if isinstance(drones, dict) else drones
    adjacency = {d.drone_id: [] for d in drone_list}
    adjacency["base"] = []

    # Build edges based on comm_range
    for d in drone_list:
        if d.status == "dead":
            continue
        # Check connectivity to base
        if manhattan_distance(d.pos, base_pos) <= d.comm_range:
            adjacency["base"].append(d.drone_id)
            adjacency[d.drone_id].append("base")

        # Check connectivity to other drones
        for other in drone_list:
            if other.drone_id == d.drone_id or other.status == "dead":
                continue
            if manhattan_distance(d.pos, other.pos) <= d.comm_range:
                if other.drone_id not in adjacency[d.drone_id]:
                    adjacency[d.drone_id].append(other.drone_id)

    # BFS from base to determine connected status
    visited = set()
    queue = deque(["base"])
    visited.add("base")
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    for d in drone_list:
        if d.status == "dead":
            d.connected = False
        else:
            d.connected = d.drone_id in visited

    return adjacency


def apply_blackout(drones, zone_center, radius):
    """Force drones within blackout zone to disconnect.
    Returns list of affected drone IDs.
    """
    drone_list = list(drones.values()) if isinstance(drones, dict) else drones
    affected = []
    for d in drone_list:
        if d.status == "dead":
            continue
        if manhattan_distance(d.pos, zone_center) <= radius:
            d.connected = False
            affected.append(d.drone_id)
    return affected


def check_relay_path(drone, base_pos, all_drones):
    """BFS to find a relay path from drone back to base through other connected drones.
    Returns the path as a list of drone_ids, or None if no path exists.
    """
    drone_list = list(all_drones.values()) if isinstance(all_drones, dict) else all_drones
    drone_map = {d.drone_id: d for d in drone_list}

    # BFS from the target drone toward base
    visited = {drone.drone_id}
    queue = deque([(drone.drone_id, [drone.drone_id])])

    while queue:
        current_id, path = queue.popleft()
        current = drone_map[current_id]

        # Check if current can reach base directly
        if manhattan_distance(current.pos, base_pos) <= current.comm_range:
            return path + ["base"]

        # Expand to neighboring drones
        for other in drone_list:
            if other.drone_id in visited or other.status == "dead":
                continue
            if manhattan_distance(current.pos, other.pos) <= current.comm_range:
                visited.add(other.drone_id)
                queue.append((other.drone_id, path + [other.drone_id]))

    return None


def sync_drone(drone):
    """Flush and return the drone's findings buffer."""
    findings = list(drone.findings_buffer)
    drone.findings_buffer.clear()
    return findings


def get_network_resilience(drones, base_pos=(6, 5)):
    """Analyze mesh network resilience.
    Returns dict with connectivity_ratio, critical_nodes, coverage_gaps, relay_suggestions.
    """
    drone_list = list(drones.values()) if isinstance(drones, dict) else drones
    active_drones = [d for d in drone_list if d.status != "dead"]

    if not active_drones:
        return {
            "connectivity_ratio": 0.0,
            "critical_nodes": [],
            "coverage_gaps": [],
            "relay_suggestions": [],
        }

    # Current connectivity
    connected_count = sum(1 for d in active_drones if d.connected)
    connectivity_ratio = connected_count / len(active_drones) if active_drones else 0

    # Find critical nodes (removing them disconnects others)
    critical_nodes = []
    for test_drone in active_drones:
        if not test_drone.connected:
            continue
        # Temporarily remove and recheck
        remaining = {d.drone_id: d for d in active_drones if d.drone_id != test_drone.drone_id}
        temp_adj = compute_mesh_topology(remaining, base_pos)
        new_connected = sum(1 for d in remaining.values() if d.connected)
        # Restore
        compute_mesh_topology(drones, base_pos)
        if new_connected < connected_count - 1:
            critical_nodes.append(test_drone.drone_id)

    # Coverage gaps: areas far from any drone
    covered_positions = set()
    for d in active_drones:
        if d.pos:
            x, y = d.pos
            for dx in range(-d.comm_range, d.comm_range + 1):
                for dy in range(-d.comm_range, d.comm_range + 1):
                    if abs(dx) + abs(dy) <= d.comm_range:
                        covered_positions.add((x + dx, y + dy))

    coverage_gaps = []
    for x in range(12):
        for y in range(12):
            if (x, y) not in covered_positions:
                coverage_gaps.append((x, y))

    # Relay suggestions: disconnected drones that could be bridged
    relay_suggestions = []
    for d in active_drones:
        if not d.connected and d.battery > 20:
            relay_suggestions.append({
                "drone_id": d.drone_id,
                "position": d.pos,
                "suggestion": "Deploy nearby drone as relay to restore connectivity",
            })

    return {
        "connectivity_ratio": round(connectivity_ratio, 2),
        "critical_nodes": critical_nodes,
        "coverage_gaps": coverage_gaps[:10],  # Limit output size
        "relay_suggestions": relay_suggestions,
    }
