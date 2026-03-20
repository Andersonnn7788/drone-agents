"""DroneAgent (local autonomy) and SurvivorAgent (health decay) for Mesa 3."""

import mesa

BASE_POS = (6, 5)  # Center of the 12x12 grid — must match simulation/model.py


class SurvivorAgent(mesa.Agent):
    """A survivor trapped in the disaster zone with decaying health."""

    DRAIN_RATES = {"CRITICAL": 0.05, "MODERATE": 0.02, "STABLE": 0.01}

    def __init__(self, model, severity="MODERATE"):
        super().__init__(model)
        self.severity = severity
        INITIAL_HEALTH = {"CRITICAL": 0.40, "MODERATE": 0.70, "STABLE": 0.90}
        self.health = INITIAL_HEALTH.get(severity, 0.70)
        self.found = False
        self.rescued = False
        self.alive = True
        self.survivor_number = None  # Set by model after creation (1-based)

    def step(self):
        if not self.alive or self.rescued:
            return
        self.health -= self.DRAIN_RATES.get(self.severity, 0.01)
        if self.health <= 0:
            self.health = 0
            self.alive = False


class DroneAgent(mesa.Agent):
    """A rescue drone with local autonomy for disconnected operation."""

    def __init__(self, model, drone_id, initial_battery=100):
        super().__init__(model)
        self.drone_id = drone_id
        self.battery = initial_battery
        self.status = "active"  # active, returning, charging, relay, dead
        self.connected = True
        self.comm_range = 4
        self.findings_buffer = []
        self.scan_radius = 2
        self.assigned_sector = None  # (x, y, w, h) tuple or None
        self.is_relay = False
        self.recent_positions = []   # Last 6 positions for anti-oscillation
        self.previous_pos = None     # Immediate prior position (fast backtrack check)

    # ── LLM-directed actions (called via MCP) ──────────────────────────

    def move_to(self, x, y):
        """Move drone to target position. Costs 2 battery."""
        if self.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {self.status}"}
        if self.battery < 2:
            return {"success": False, "reason": "insufficient battery"}
        if not (0 <= x < self.model.grid.width and 0 <= y < self.model.grid.height):
            return {"success": False, "reason": "out of bounds"}
        if self.model.terrain[y][x] == "WATER":
            return {"success": False, "reason": "cannot move to water"}

        # Return-trip feasibility: block moves that strand the drone
        new_return_cost = self._return_cost_from((x, y))
        cur_return_cost = self._return_cost_from()
        battery_after_move = self.battery - 2
        # Allow moves toward base (return cost decreases) so returning drones aren't stuck
        moving_toward_base = new_return_cost < cur_return_cost
        if not moving_toward_base and battery_after_move < new_return_cost + 5:
            return {
                "success": False,
                "reason": (
                    f"insufficient battery for round trip — "
                    f"battery after move={battery_after_move}, "
                    f"return cost={new_return_cost}. Recall to base instead."
                ),
            }

        # Single-cell movement enforcement — drones move one step at a time
        dx_dist = abs(x - self.pos[0])
        dy_dist = abs(y - self.pos[1])
        if dx_dist > 1 or dy_dist > 1:
            return {
                "success": False,
                "reason": f"Can only move 1 cell at a time. Current: {list(self.pos)}, target: [{x},{y}]",
            }

        # No-op guard: don't waste battery moving to current position
        if (x, y) == self.pos:
            return {"success": True, "position": [x, y], "battery": self.battery}

        old_pos = self.pos
        self.model.grid.move_agent(self, (x, y))
        self.battery -= 2

        # Track movement history for anti-oscillation
        self.previous_pos = old_pos
        self.recent_positions.append(old_pos)
        if len(self.recent_positions) > 6:
            self.recent_positions = self.recent_positions[-6:]

        # Deposit light trail pheromone (avoid overwriting stronger scan pheromone)
        ox, oy = old_pos
        self.model.pheromone_scanned[oy][ox] = max(
            self.model.pheromone_scanned[oy][ox], 0.3
        )

        if self.battery <= 0:
            self.battery = 0
            self.status = "dead"
        return {"success": True, "position": [x, y], "battery": self.battery}

    def plan_path_to(self, x, y):
        """BFS pathfinder over the 8-directional grid from current position to (x, y).

        Returns list[tuple[int,int]] of waypoints (excludes current position).
        Does NOT move the drone or deduct battery — planning only.
        Path length is capped by battery budget (battery // 2 steps).
        Avoids WATER cells and out-of-bounds.
        """
        from collections import deque

        start = self.pos
        goal = (x, y)
        if start == goal:
            return []

        w, h = self.model.grid.width, self.model.grid.height
        max_steps = self.battery // 2  # each move costs 2 battery

        if not (0 <= x < w and 0 <= y < h):
            return []
        if self.model.terrain[y][x] == "WATER":
            return []

        # BFS with 8-directional neighbors
        visited = {start}
        parent = {}
        queue = deque([(start, 0)])

        while queue:
            (cx, cy), depth = queue.popleft()
            if depth >= max_steps:
                continue
            for ddx in (-1, 0, 1):
                for ddy in (-1, 0, 1):
                    if ddx == 0 and ddy == 0:
                        continue
                    nx, ny = cx + ddx, cy + ddy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if self.model.terrain[ny][nx] == "WATER":
                        continue
                    if (nx, ny) in visited:
                        continue
                    visited.add((nx, ny))
                    parent[(nx, ny)] = (cx, cy)
                    if (nx, ny) == goal:
                        # Reconstruct path
                        path = []
                        node = goal
                        while node != start:
                            path.append(node)
                            node = parent[node]
                        path.reverse()
                        return path
                    queue.append(((nx, ny), depth + 1))

        return []  # No path found within budget

    def thermal_scan(self):
        """Scan surrounding cells for survivors. Costs 3 battery."""
        if self.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {self.status}"}
        if self.battery < 3:
            return {"success": False, "reason": "insufficient battery"}

        # Return-trip feasibility: refuse scans that strand the drone
        battery_after_scan = self.battery - 3
        return_cost = self._return_cost_from()
        if battery_after_scan < return_cost + 5:
            return {
                "success": False,
                "reason": (
                    f"insufficient battery for scan + return — "
                    f"battery after scan={battery_after_scan}, "
                    f"return cost={return_cost}. Recall to base instead."
                ),
            }

        self.battery -= 3
        x, y = self.pos
        found = []

        for dx in range(-self.scan_radius, self.scan_radius + 1):
            for dy in range(-self.scan_radius, self.scan_radius + 1):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < self.model.grid.width and 0 <= ny < self.model.grid.height):
                    continue

                self.model.scanned_cells.add((nx, ny))
                self.model.pheromone_scanned[ny][nx] = 1.0

                for agent in self.model.grid.get_cell_list_contents([(nx, ny)]):
                    if isinstance(agent, SurvivorAgent) and agent.alive and not agent.found:
                        agent.found = True
                        found.append({
                            "survivor_id": agent.survivor_number,
                            "position": [nx, ny],
                            "severity": agent.severity,
                            "health": round(agent.health, 2),
                        })
                        # Deposit survivor_nearby pheromone at cell + neighbors
                        self.model.pheromone_survivor_nearby[ny][nx] = 1.0
                        for ddx in range(-1, 2):
                            for ddy in range(-1, 2):
                                nnx, nny = nx + ddx, ny + ddy
                                if 0 <= nnx < self.model.grid.width and 0 <= nny < self.model.grid.height:
                                    self.model.pheromone_survivor_nearby[nny][nnx] = max(
                                        self.model.pheromone_survivor_nearby[nny][nnx], 0.5
                                    )

        self.model.update_heatmap(self.pos, found, scan_radius=self.scan_radius)

        result = {
            "success": True,
            "position": list(self.pos),
            "survivors_found": found,
            "cells_scanned": (2 * self.scan_radius + 1) ** 2,
            "battery": self.battery,
        }

        if not self.connected:
            self.findings_buffer.append(result)

        if self.battery <= 0:
            self.battery = 0
            self.status = "dead"

        return result

    def rescue_survivor(self, survivor):
        """Mark a survivor as rescued. Drone must be on the same cell."""
        if self.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {self.status}"}
        if not isinstance(survivor, SurvivorAgent):
            return {"success": False, "reason": "invalid survivor"}
        if not survivor.found:
            return {"success": False, "reason": "survivor not yet found — scan first"}
        if not survivor.alive:
            return {"success": False, "reason": "survivor is already dead"}
        if survivor.rescued:
            return {
                "success": True,
                "already_rescued": True,
                "drone_id": self.drone_id,
                "survivor_id": survivor.survivor_number,
                "severity": survivor.severity,
                "health": round(survivor.health, 2),
            }
        if self.pos != survivor.pos:
            return {
                "success": False,
                "reason": f"drone at {list(self.pos)}, survivor at {list(survivor.pos)} — must be same cell",
            }

        survivor.rescued = True
        survivor.rescue_position = list(self.pos)
        self.model.record_rescue(self.drone_id, survivor.survivor_number, survivor.severity, survivor.health)
        self.model.grid.remove_agent(survivor)
        return {
            "success": True,
            "drone_id": self.drone_id,
            "survivor_id": survivor.survivor_number,
            "severity": survivor.severity,
            "health": round(survivor.health, 2),
            "position": list(self.pos),
        }

    def return_to_base(self):
        """Set drone to return-to-base mode."""
        if self.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {self.status}"}
        self.status = "returning"
        return {"success": True, "drone_id": self.drone_id, "status": "returning"}

    def deploy_as_relay(self):
        """Convert drone to a stationary relay node with extended range."""
        if self.status == "dead":
            return {"success": False, "reason": "drone is dead"}
        self.is_relay = True
        self.status = "relay"
        self.comm_range = 6
        return {
            "success": True,
            "drone_id": self.drone_id,
            "position": list(self.pos),
            "comm_range": self.comm_range,
        }

    def _return_cost_from(self, pos=None):
        """Estimate battery cost to return to base from a given position.

        Each cell costs ~3 battery (2 move + 1 passive drain).
        """
        if pos is None:
            pos = self.pos
        dist = abs(pos[0] - BASE_POS[0]) + abs(pos[1] - BASE_POS[1])
        return 3 * dist

    # ── Local autonomy (runs each simulation step) ────────────────────

    def step(self):
        """Called by Mesa each simulation step."""
        if self.status == "dead":
            return

        # Relays just sit there
        if self.status == "relay":
            return

        # Auto-return at low battery (distance-aware)
        if self.status == "active":
            dist = abs(self.pos[0] - BASE_POS[0]) + abs(self.pos[1] - BASE_POS[1])
            return_cost = 3 * dist  # 2/move + 1/passive per cell
            safe_threshold = return_cost + 15  # generous 15-unit safety margin
            if self.battery < max(safe_threshold, 35):  # minimum 35% floor
                self.status = "returning"

        # Handle returning: pathfind toward base
        if self.status == "returning":
            self._pathfind_to_base()
            return

        # Handle charging at base
        if self.status == "charging":
            self._charge()
            return

        # Auto-rescue any found survivor at current cell
        if self.status == "active" and not self.connected:
            cellmates = self.model.grid.get_cell_list_contents([self.pos])
            for agent in cellmates:
                if (isinstance(agent, SurvivorAgent) and agent.found
                        and agent.alive and not agent.rescued):
                    result = self.rescue_survivor(agent)
                    if result.get("success") and not result.get("already_rescued"):
                        import time
                        self.model.agent_logs.append({
                            "step": self.model.mission_step,
                            "timestamp": time.time(),
                            "message": (
                                f"[AUTONOMOUS] {self.drone_id} rescued survivor "
                                f"#{agent.survivor_number} ({agent.severity}) independently "
                                f"during blackout at ({self.pos[0]},{self.pos[1]})"
                            ),
                            "is_critical": True,
                            "type": "system",
                        })
                    break

        # Autonomous navigation when disconnected: seek known survivors first, then pheromones
        if not self.connected and self.status == "active" and self.battery >= 5:
            if not self._seek_known_survivor():
                self._pheromone_navigate()

    def _pathfind_to_base(self):
        """BFS pathfinding toward BASE_POS — takes one step per call."""
        if self.pos == BASE_POS:
            self.status = "charging"
            return
        if self.battery < 2:
            if self.pos == BASE_POS:
                self.status = "charging"
            else:
                self.status = "dead"
            return

        path = self.plan_path_to(*BASE_POS)
        if path:
            self.move_to(*path[0])
        # If no path found, drone is stuck — stay in place

    def _charge(self):
        """Charge battery at base station — instant full recharge."""
        if self.pos != BASE_POS:
            self.status = "returning"
            return
        self.battery = 100
        self.status = "active"

    def _seek_known_survivor(self):
        """When disconnected, pathfind toward the nearest known found-but-unrescued survivor.

        Returns True if a target was found and movement was attempted, False otherwise.
        """
        # Collect found, alive, unrescued survivors
        targets = [
            s for s in self.model.survivors
            if s.found and s.alive and not s.rescued and s.pos is not None
        ]
        if not targets:
            return False

        # Find nearest by Manhattan distance
        nearest = min(
            targets,
            key=lambda s: abs(s.pos[0] - self.pos[0]) + abs(s.pos[1] - self.pos[1]),
        )

        # Already co-located — rescue will be handled by the auto-rescue block above
        if self.pos == nearest.pos:
            return False

        # Plan one BFS step toward nearest survivor
        path = self.plan_path_to(*nearest.pos)
        if not path:
            return False

        self.move_to(*path[0])

        # Auto-scan at new location if unscanned and battery allows
        if self.battery >= 3 and path[0] not in self.model.scanned_cells:
            self.thermal_scan()

        return True

    def _pheromone_navigate(self):
        """Navigate using pheromone gradients when disconnected from LLM."""
        import random

        x, y = self.pos
        best_score = -float("inf")
        best_candidates = []

        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < self.model.grid.width and 0 <= ny < self.model.grid.height):
                    continue
                if self.model.terrain[ny][nx] == "WATER":
                    continue

                score = (
                    self.model.pheromone_survivor_nearby[ny][nx]
                    - 1.5 * self.model.pheromone_scanned[ny][nx]
                    - 2.0 * self.model.pheromone_danger[ny][nx]
                    + 0.5 * self.model.heatmap[ny][nx]
                )

                # Prefer assigned sector
                if self.assigned_sector:
                    sx, sy, sw, sh = self.assigned_sector
                    if sx <= nx < sx + sw and sy <= ny < sy + sh:
                        score += 0.3

                # Anti-backtrack: penalize immediate previous position
                if self.previous_pos and (nx, ny) == self.previous_pos:
                    score -= 0.8

                # Penalize recently visited positions (stronger for more recent)
                if (nx, ny) in self.recent_positions:
                    recency = self.recent_positions.index((nx, ny))
                    age = len(self.recent_positions) - recency
                    score -= 0.1 * age

                # Collect candidates for random tie-breaking
                if score > best_score:
                    best_score = score
                    best_candidates = [(nx, ny)]
                elif score == best_score:
                    best_candidates.append((nx, ny))

        if best_candidates:
            best_pos = random.choice(best_candidates)
            self.move_to(*best_pos)
            # Auto-scan if at a new location with battery
            if self.battery >= 3 and best_pos not in self.model.scanned_cells:
                self.thermal_scan()

    def to_dict(self):
        """Serialize drone state for JSON output."""
        return {
            "drone_id": self.drone_id,
            "position": list(self.pos) if self.pos else [0, 0],
            "battery": self.battery,
            "status": self.status,
            "connected": self.connected,
            "is_relay": self.is_relay,
            "comm_range": self.comm_range,
            "assigned_sector": list(self.assigned_sector) if self.assigned_sector else None,
            "findings_buffer_size": len(self.findings_buffer),
            "recent_positions": [list(p) for p in self.recent_positions[-4:]],
        }
