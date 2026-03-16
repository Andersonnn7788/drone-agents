"""DisasterModel — Mesa 3 simulation: grid, terrain, heatmap, pheromones, disasters."""

import mesa
import numpy as np
import random

from .agents import DroneAgent, SurvivorAgent
from .mesh_network import compute_mesh_topology, apply_blackout, manhattan_distance


class DisasterModel(mesa.Model):
    def __init__(self, seed=42, width=12, height=12, num_drones=4, num_survivors=8, demo_mode=False):
        super().__init__(seed=seed)
        self.width = width
        self.height = height
        self.demo_mode = demo_mode
        self.grid = mesa.space.MultiGrid(width, height, torus=False)
        self._rng = random.Random(seed)

        # Terrain
        self.terrain = self._generate_terrain()

        # Bayesian heatmap (prior probabilities of survivors)
        self.heatmap = self._init_heatmap()

        # Pheromone layers (numpy arrays indexed [y][x])
        self.pheromone_scanned = np.zeros((height, width))
        self.pheromone_survivor_nearby = np.zeros((height, width))
        self.pheromone_danger = np.zeros((height, width))

        # State tracking
        self.mission_step = 0
        self.state_history = []
        self.scanned_cells = set()
        self.disaster_events = []
        self.agent_logs = []
        self.blackout_zones = []

        # Create drones at base (0, 0)
        drone_names = ["drone_alpha", "drone_bravo", "drone_charlie", "drone_delta", "drone_echo"]
        self.drones = {}
        for name in drone_names[:num_drones]:
            drone = DroneAgent(self, name)
            self.drones[name] = drone
            self.grid.place_agent(drone, (0, 0))

        # Create survivors
        if demo_mode:
            self._place_demo_survivors(num_survivors)
        else:
            self._place_random_survivors(num_survivors)

        # Initial mesh computation
        self.mesh_topology = compute_mesh_topology(self.drones)

        # Record initial state
        self.state_history.append(self.get_state())

    # ── Survivor placement ─────────────────────────────────────────────

    def _place_random_survivors(self, num_survivors):
        """Place survivors at random passable positions (full sim)."""
        self.survivors = []
        severities = (["CRITICAL"] * 3 + ["MODERATE"] * 3 + ["STABLE"] * 2)[:num_survivors]
        while len(severities) < num_survivors:
            severities.append("MODERATE")
        passable = [
            (x, y) for x in range(self.width) for y in range(self.height)
            if self.terrain[y][x] not in ("WATER",) and (x, y) != (0, 0)
        ]
        positions = self._rng.sample(passable, min(num_survivors, len(passable)))
        for pos, severity in zip(positions, severities):
            survivor = SurvivorAgent(self, severity)
            self.survivors.append(survivor)
            self.grid.place_agent(survivor, pos)

    def _place_demo_survivors(self, num_survivors):
        """Place survivors at strategic positions near building clusters (demo mode).
        Guarantees each quadrant drone finds a survivor quickly."""
        self.survivors = []
        # Deterministic placements: 2 CRITICAL, 2 MODERATE, 1 STABLE
        demo_placements = [
            ((3, 3), "CRITICAL"),    # SW building cluster
            ((9, 9), "CRITICAL"),    # NE building cluster
            ((3, 10), "MODERATE"),   # NW building cluster
            ((10, 2), "MODERATE"),   # SE building cluster
            ((6, 6), "STABLE"),      # center of map
        ]
        for (x, y), severity in demo_placements[:num_survivors]:
            survivor = SurvivorAgent(self, severity)
            self.survivors.append(survivor)
            self.grid.place_agent(survivor, (x, y))

    # ── Terrain ───────────────────────────────────────────────────────

    def _generate_terrain(self):
        """Generate deterministic 12x12 terrain grid. Indexed as terrain[y][x]."""
        t = [["OPEN"] * self.width for _ in range(self.height)]

        # Roads — bottom row, left column, middle horizontal & vertical
        for x in range(self.width):
            t[0][x] = "ROAD"
            t[5][x] = "ROAD"
        for y in range(self.height):
            t[y][0] = "ROAD"
            t[y][6] = "ROAD"

        # Building clusters (survivors likely here)
        buildings = [
            (2, 2), (2, 3), (3, 2), (3, 3),       # SW cluster
            (8, 8), (8, 9), (9, 8), (9, 9),       # NE cluster
            (2, 9), (2, 10), (3, 9), (3, 10),     # NW cluster
            (9, 2), (10, 2), (10, 3),              # SE cluster
        ]
        for bx, by in buildings:
            if 0 <= bx < self.width and 0 <= by < self.height and t[by][bx] == "OPEN":
                t[by][bx] = "BUILDING"

        # Water hazard (upper right)
        water_cells = [(10, 7), (11, 7), (11, 8)]
        for wx, wy in water_cells:
            if 0 <= wx < self.width and 0 <= wy < self.height:
                t[wy][wx] = "WATER"

        return t

    def _init_heatmap(self):
        """Initialize Bayesian heatmap from terrain priors."""
        priors = {"BUILDING": 0.7, "ROAD": 0.5, "OPEN": 0.3, "WATER": 0.1, "DEBRIS": 0.1}
        hm = np.zeros((self.height, self.width))
        for y in range(self.height):
            for x in range(self.width):
                hm[y][x] = priors.get(self.terrain[y][x], 0.3)
        return hm

    # ── Heatmap update ────────────────────────────────────────────────

    def update_heatmap(self, scan_pos, found_survivors):
        """Bayesian update of heatmap after a scan."""
        x, y = scan_pos
        scan_radius = 1

        if found_survivors:
            for dx in range(-scan_radius, scan_radius + 1):
                for dy in range(-scan_radius, scan_radius + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        boost = 0.9 if (dx == 0 and dy == 0) else 0.6
                        self.heatmap[ny][nx] = min(
                            1.0, self.heatmap[ny][nx] + boost * (1 - self.heatmap[ny][nx])
                        )
        else:
            for dx in range(-scan_radius, scan_radius + 1):
                for dy in range(-scan_radius, scan_radius + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        self.heatmap[ny][nx] = max(0.05, self.heatmap[ny][nx] * 0.5)

    # ── Simulation step ───────────────────────────────────────────────

    def step(self):
        """Advance simulation by one tick."""
        self.mission_step += 1

        # 1. Passive battery drain (1/step for active drones)
        for drone in self.drones.values():
            if drone.status in ("active", "returning") and drone.battery > 0:
                drone.battery -= 1
                if drone.battery <= 0:
                    drone.battery = 0
                    drone.status = "dead"

        # 2. Decay pheromones
        self.pheromone_scanned *= 0.9
        self.pheromone_survivor_nearby *= 0.9
        self.pheromone_danger *= 0.9

        # 3. Step survivors (health drain)
        for survivor in self.survivors:
            survivor.step()

        # 4. Step drones (autonomous behavior)
        for drone in self.drones.values():
            drone.step()

        # 5. Dynamic disasters
        if self.demo_mode:
            self._demo_scripted_events()
        else:
            self._check_aftershock()
            self._check_rising_water()

        # 6. Recompute mesh topology
        self.mesh_topology = compute_mesh_topology(self.drones)

        # 7. Re-apply active blackout zones
        for zone in self.blackout_zones:
            apply_blackout(self.drones, zone["center"], zone["radius"])

        # 8. Record state snapshot
        self.state_history.append(self.get_state())

    def _check_aftershock(self):
        """Random aftershock: ~10% chance per step after step 8."""
        if self.mission_step < 8:
            return
        if self._rng.random() > 0.10:
            return

        # Pick a random area and convert 2-3 OPEN cells to DEBRIS
        cx = self._rng.randint(1, self.width - 2)
        cy = self._rng.randint(1, self.height - 2)
        converted = []

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = cx + dx, cy + dy
                if (0 <= nx < self.width and 0 <= ny < self.height
                        and self.terrain[ny][nx] == "OPEN" and len(converted) < 3):
                    self.terrain[ny][nx] = "DEBRIS"
                    self.pheromone_danger[ny][nx] = 1.0
                    self.heatmap[ny][nx] = max(0.05, self.heatmap[ny][nx] * 0.3)
                    converted.append([nx, ny])

        if converted:
            event = {
                "type": "aftershock",
                "step": self.mission_step,
                "center": [cx, cy],
                "affected_cells": converted,
            }
            self.disaster_events.append(event)

    def _check_rising_water(self):
        """Random rising water: ~7% chance per step after step 12."""
        if self.mission_step < 12:
            return
        if self._rng.random() > 0.07:
            return

        # Find existing water cells and expand one of them
        water_cells = [
            (x, y) for x in range(self.width) for y in range(self.height)
            if self.terrain[y][x] == "WATER"
        ]
        if not water_cells:
            return

        wx, wy = self._rng.choice(water_cells)
        expanded = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = wx + dx, wy + dy
            if (0 <= nx < self.width and 0 <= ny < self.height
                    and self.terrain[ny][nx] in ("OPEN", "ROAD") and len(expanded) < 1):
                self.terrain[ny][nx] = "WATER"
                self.pheromone_danger[ny][nx] = 1.0
                expanded.append([nx, ny])

                # Kill survivors in flooded cells
                for agent in self.grid.get_cell_list_contents([(nx, ny)]):
                    if isinstance(agent, SurvivorAgent) and agent.alive:
                        agent.alive = False
                        agent.health = 0

        if expanded:
            event = {
                "type": "rising_water",
                "step": self.mission_step,
                "source": [wx, wy],
                "flooded_cells": expanded,
            }
            self.disaster_events.append(event)

    # ── Demo scripted events ─────────────────────────────────────────

    def _demo_scripted_events(self):
        """Deterministic demo events at specific steps."""
        step = self.mission_step

        # Step 6: Aftershock near (5, 4)
        if step == 6:
            cx, cy = 5, 4
            converted = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    nx, ny = cx + dx, cy + dy
                    if (0 <= nx < self.width and 0 <= ny < self.height
                            and self.terrain[ny][nx] == "OPEN" and len(converted) < 3):
                        self.terrain[ny][nx] = "DEBRIS"
                        self.pheromone_danger[ny][nx] = 1.0
                        self.heatmap[ny][nx] = max(0.05, self.heatmap[ny][nx] * 0.3)
                        converted.append([nx, ny])
            if converted:
                self.disaster_events.append({
                    "type": "aftershock",
                    "step": step,
                    "center": [cx, cy],
                    "affected_cells": converted,
                })

        # Step 10: Blackout at (8, 8) radius 3
        elif step == 10:
            self.trigger_blackout(8, 8, 3)

        # Step 15: Blackout clears
        elif step == 15:
            if self.blackout_zones:
                self.blackout_zones.clear()
                # Restore connectivity for all drones
                for drone in self.drones.values():
                    drone.connected = True
                self.disaster_events.append({
                    "type": "blackout_cleared",
                    "step": step,
                    "message": "Communication blackout has lifted. All drones reconnected.",
                })

        # Step 18: Rising water near (10, 7)
        elif step == 18:
            wx, wy = 10, 7
            expanded = []
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = wx + dx, wy + dy
                if (0 <= nx < self.width and 0 <= ny < self.height
                        and self.terrain[ny][nx] in ("OPEN", "ROAD") and len(expanded) < 1):
                    self.terrain[ny][nx] = "WATER"
                    self.pheromone_danger[ny][nx] = 1.0
                    expanded.append([nx, ny])
                    # Kill survivors in flooded cells
                    for agent in self.grid.get_cell_list_contents([(nx, ny)]):
                        if isinstance(agent, SurvivorAgent) and agent.alive:
                            agent.alive = False
                            agent.health = 0
            if expanded:
                self.disaster_events.append({
                    "type": "rising_water",
                    "step": step,
                    "source": [wx, wy],
                    "flooded_cells": expanded,
                })

    # ── Digital twin / mission simulation ─────────────────────────────

    def simulate_mission(self, drone_id, target_x, target_y):
        """Predict cost and feasibility of sending a drone to a target."""
        drone = self.drones.get(drone_id)
        if not drone:
            return {"success": False, "reason": "drone not found"}
        if drone.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {drone.status}"}

        dist_to_target = manhattan_distance(drone.pos, (target_x, target_y))
        dist_to_base = manhattan_distance((target_x, target_y), (0, 0))

        move_cost = 2 * dist_to_target
        scan_cost = 3
        return_cost = 2 * dist_to_base
        passive_cost = dist_to_target  # 1 per step to get there

        arrival_battery = drone.battery - move_cost - passive_cost
        post_scan_battery = arrival_battery - scan_cost
        return_battery = post_scan_battery - return_cost - dist_to_base

        return {
            "success": True,
            "drone_id": drone_id,
            "current_battery": drone.battery,
            "distance_to_target": dist_to_target,
            "distance_to_base_from_target": dist_to_base,
            "move_cost": move_cost,
            "arrival_battery": max(0, arrival_battery),
            "post_scan_battery": max(0, post_scan_battery),
            "return_battery": return_battery,
            "return_feasible": return_battery >= 0,
            "survivor_probability": round(float(self.heatmap[target_y][target_x]), 2),
            "terrain": self.terrain[target_y][target_x],
        }

    # ── Swarm coordination ────────────────────────────────────────────

    def coordinate_swarm(self, assignments=None):
        """Divide grid into sectors and assign drones.
        If assignments provided: {drone_id: [x, y, w, h]}
        Otherwise: auto-divide grid among active drones.
        """
        active = [d for d in self.drones.values() if d.status == "active"]

        if assignments:
            for drone_id, sector in assignments.items():
                if drone_id in self.drones:
                    self.drones[drone_id].assigned_sector = tuple(sector)
            return {"success": True, "assignments": assignments}

        # Auto-divide: split grid into quadrants
        if len(active) == 0:
            return {"success": False, "reason": "no active drones"}

        half_w = self.width // 2
        half_h = self.height // 2
        sectors = [
            (0, 0, half_w, half_h),           # SW
            (half_w, 0, half_w, half_h),      # SE
            (0, half_h, half_w, half_h),      # NW
            (half_w, half_h, half_w, half_h), # NE
        ]

        result = {}
        for i, drone in enumerate(active):
            sector = sectors[i % len(sectors)]
            drone.assigned_sector = sector
            result[drone.drone_id] = list(sector)

        return {"success": True, "assignments": result}

    # ── Blackout ──────────────────────────────────────────────────────

    def trigger_blackout(self, zone_x, zone_y, radius):
        """Trigger a communication blackout zone."""
        zone = {"center": (zone_x, zone_y), "radius": radius}
        self.blackout_zones.append(zone)
        affected = apply_blackout(self.drones, (zone_x, zone_y), radius)

        event = {
            "type": "blackout",
            "step": self.mission_step,
            "center": [zone_x, zone_y],
            "radius": radius,
            "affected_drones": affected,
        }
        self.disaster_events.append(event)
        return event

    # ── State serialization ───────────────────────────────────────────

    def get_state(self):
        """Full JSON-serializable state snapshot."""
        # Only include found or rescued survivors (fog of war)
        known_survivors = []
        for s in self.survivors:
            if s.found or s.rescued:
                known_survivors.append({
                    "survivor_id": s.unique_id,
                    "position": list(s.pos) if s.pos else None,
                    "severity": s.severity,
                    "health": round(s.health, 2),
                    "found": s.found,
                    "rescued": s.rescued,
                    "alive": s.alive,
                })

        # Stats
        total_survivors = len(self.survivors)
        found_count = sum(1 for s in self.survivors if s.found)
        alive_count = sum(1 for s in self.survivors if s.alive)
        rescued_count = sum(1 for s in self.survivors if s.rescued)
        active_drones = sum(1 for d in self.drones.values() if d.status == "active")

        return {
            "mission_step": self.mission_step,
            "terrain": self.terrain,
            "drones": {did: d.to_dict() for did, d in self.drones.items()},
            "survivors": known_survivors,
            "heatmap": self.heatmap.tolist(),
            "pheromones": {
                "scanned": self.pheromone_scanned.tolist(),
                "survivor_nearby": self.pheromone_survivor_nearby.tolist(),
                "danger": self.pheromone_danger.tolist(),
            },
            "scanned_cells": [list(c) for c in self.scanned_cells],
            "mesh_topology": {
                k: v for k, v in self.mesh_topology.items()
            },
            "disaster_events": self.disaster_events,
            "blackout_zones": [
                {"center": list(z["center"]), "radius": z["radius"]}
                for z in self.blackout_zones
            ],
            "stats": {
                "total_survivors": total_survivors,
                "found": found_count,
                "alive": alive_count,
                "rescued": rescued_count,
                "active_drones": active_drones,
                "total_drones": len(self.drones),
                "cells_scanned": len(self.scanned_cells),
                "total_cells": self.width * self.height,
                "coverage_pct": round(len(self.scanned_cells) / (self.width * self.height) * 100, 1),
            },
        }

    def get_priority_map(self):
        """Return heatmap combined with pheromone data for LLM decision-making."""
        priority = np.copy(self.heatmap)
        # Boost areas with survivor pheromone, penalize scanned/danger
        priority += 0.3 * self.pheromone_survivor_nearby
        priority -= 0.2 * self.pheromone_scanned
        priority -= 0.5 * self.pheromone_danger
        priority = np.clip(priority, 0.0, 1.0)
        return priority.tolist()
