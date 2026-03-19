"""DroneAgent (local autonomy) and SurvivorAgent (health decay) for Mesa 3."""

import mesa

BASE_POS = (6, 5)  # Center of the 12x12 grid — must match simulation/model.py


class SurvivorAgent(mesa.Agent):
    """A survivor trapped in the disaster zone with decaying health."""

    DRAIN_RATES = {"CRITICAL": 0.05, "MODERATE": 0.02, "STABLE": 0.01}

    def __init__(self, model, severity="MODERATE"):
        super().__init__(model)
        self.severity = severity
        self.health = 1.0
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

    def __init__(self, model, drone_id):
        super().__init__(model)
        self.drone_id = drone_id
        self.battery = 100
        self.status = "active"  # active, returning, charging, relay, dead
        self.connected = True
        self.comm_range = 4
        self.findings_buffer = []
        self.scan_radius = 1
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
        """Compute a greedy diagonal path from current position to (x, y).

        Returns list[tuple[int,int]] of waypoints (excludes current position).
        Does NOT move the drone or deduct battery — planning only.
        Stops if battery would be insufficient for the remaining path.
        """
        path = []
        cx, cy = self.pos
        # Reserve battery: each step costs 2, need enough for entire path
        budget = self.battery

        for _ in range(self.model.grid.width + self.model.grid.height):
            if (cx, cy) == (x, y):
                break
            if budget < 2:
                break  # Can't afford another move

            dx = 1 if cx < x else (-1 if cx > x else 0)
            dy = 1 if cy < y else (-1 if cy > y else 0)

            # Try diagonal first, then cardinal directions toward target
            candidates = []
            if dx != 0 and dy != 0:
                candidates.append((cx + dx, cy + dy))
            if dx != 0:
                candidates.append((cx + dx, cy))
            if dy != 0:
                candidates.append((cx, cy + dy))

            moved = False
            for tx, ty in candidates:
                if (0 <= tx < self.model.grid.width
                        and 0 <= ty < self.model.grid.height
                        and self.model.terrain[ty][tx] != "WATER"):
                    path.append((tx, ty))
                    cx, cy = tx, ty
                    budget -= 2
                    moved = True
                    break

            if not moved:
                break  # Stuck — no valid move toward target

        return path

    def thermal_scan(self):
        """Scan surrounding cells for survivors. Costs 3 battery."""
        if self.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {self.status}"}
        if self.battery < 3:
            return {"success": False, "reason": "insufficient battery"}

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

        self.model.update_heatmap(self.pos, found)

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
            return {"success": False, "reason": "survivor already rescued"}
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

    # ── Local autonomy (runs each simulation step) ────────────────────

    def step(self):
        """Called by Mesa each simulation step."""
        if self.status == "dead":
            return

        # Relays just sit there
        if self.status == "relay":
            return

        # Auto-return at low battery
        if self.battery < 15 and self.status == "active":
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
        if self.status == "active":
            cellmates = self.model.grid.get_cell_list_contents([self.pos])
            for agent in cellmates:
                if (isinstance(agent, SurvivorAgent) and agent.found
                        and agent.alive and not agent.rescued):
                    self.rescue_survivor(agent)
                    break

        # Autonomous navigation when disconnected
        if not self.connected and self.status == "active" and self.battery >= 5:
            self._pheromone_navigate()

    def _pathfind_to_base(self):
        """Greedy pathfinding toward BASE_POS."""
        if self.pos == BASE_POS:
            self.status = "charging"
            return
        if self.battery < 2:
            self.status = "dead"
            return

        x, y = self.pos
        bx, by = BASE_POS
        dx = 1 if x < bx else (-1 if x > bx else 0)
        dy = 1 if y < by else (-1 if y > by else 0)

        # Try diagonal first, then cardinal directions
        candidates = []
        if dx != 0 and dy != 0:
            candidates.append((x + dx, y + dy))
        if dx != 0:
            candidates.append((x + dx, y))
        if dy != 0:
            candidates.append((x, y + dy))

        for tx, ty in candidates:
            if (0 <= tx < self.model.grid.width and 0 <= ty < self.model.grid.height
                    and self.model.terrain[ty][tx] != "WATER"):
                self.move_to(tx, ty)
                return

    def _charge(self):
        """Charge battery at base station."""
        if self.pos != BASE_POS:
            self.status = "returning"
            return
        charge_rate = 15 if getattr(self.model, "demo_mode", False) else 10
        self.battery = min(100, self.battery + charge_rate)
        if self.battery >= 100:
            self.status = "active"

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
