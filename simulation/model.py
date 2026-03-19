"""DisasterModel — Mesa 3 simulation: grid, terrain, heatmap, pheromones, disasters."""

import os

import mesa
import numpy as np
import random

from .agents import DroneAgent, SurvivorAgent
from .mesh_network import compute_mesh_topology, apply_blackout, manhattan_distance

BASE_POS = (6, 5)  # Center of the 12x12 grid


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
        self.warning_events = []       # List of warning dicts
        self.pending_disasters = []    # Scheduled disasters to fire next step

        # Scoring engine
        self.mission_score = 0
        self.rescue_events = []  # {survivor_id, severity, health_at_rescue, step, points, drone_id}
        self.deaths_while_active = 0  # survivors who died while drones were active

        # Create drones at base
        drone_names = ["drone_alpha", "drone_bravo", "drone_charlie", "drone_delta", "drone_echo"]
        self.drones = {}
        for name in drone_names[:num_drones]:
            drone = DroneAgent(self, name)
            self.drones[name] = drone
            self.grid.place_agent(drone, BASE_POS)
            drone.pos = BASE_POS  # Explicit set for Mesa 3 compatibility

        # Create survivors
        if demo_mode:
            self._place_demo_survivors(num_survivors)
        else:
            self._place_random_survivors(num_survivors)

        # Initial mesh computation
        self.mesh_topology = compute_mesh_topology(self.drones, BASE_POS)

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
            if self.terrain[y][x] not in ("WATER",) and (x, y) != BASE_POS
        ]
        positions = self._rng.sample(passable, min(num_survivors, len(passable)))
        for pos, severity in zip(positions, severities):
            survivor = SurvivorAgent(self, severity)
            self.survivors.append(survivor)
            self.grid.place_agent(survivor, pos)

    def _place_demo_survivors(self, num_survivors):
        """Place survivors in 3 waves for staggered discovery during demo.
        Wave 1 (steps 2-3): near base. Wave 2 (steps 5-7): mid-distance.
        Wave 3 (steps 9-11): far, post-blackout drama."""
        self.survivors = []
        demo_placements = [
            # Wave 1: Near base, found early — shows scan-rescue loop
            ((4, 4), "CRITICAL"),     # SW buildings, ~3 cells from base

            # Wave 2: Mid-distance, around aftershock/blackout events
            ((9, 3), "MODERATE"),     # SE buildings, ~6 from base
            ((2, 9), "CRITICAL"),     # NW buildings, ~8 from base — urgent triage

            # Wave 3: Far, post-blackout + rising water drama
            ((9, 9), "MODERATE"),     # NE buildings — inside blackout zone (center 8,8 r=3)
            ((8, 9), "STABLE"),       # NE buildings — inside blackout zone (Manhattan from (8,8)=1)
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

        # 5a. Process pending disasters (fire scheduled ones)
        self._process_pending_disasters()

        # 5b. Dynamic disasters (schedule new ones + emit warnings)
        if self.demo_mode:
            self._demo_scripted_events()
        else:
            self._check_aftershock()
            self._check_rising_water()

        # 6. Recompute mesh topology
        self.mesh_topology = compute_mesh_topology(self.drones, BASE_POS)

        # 7. Re-apply active blackout zones
        for zone in self.blackout_zones:
            apply_blackout(self.drones, zone["center"], zone["radius"])

        # 8. Record state snapshot
        self.state_history.append(self.get_state())

    def _process_pending_disasters(self):
        """Fire any scheduled disasters whose fire_at_step has arrived."""
        remaining = []
        for pending in self.pending_disasters:
            if pending["fire_at_step"] > self.mission_step:
                remaining.append(pending)
                continue

            if pending["type"] == "aftershock":
                cx, cy = pending["center"]
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
                        "step": self.mission_step,
                        "center": [cx, cy],
                        "affected_cells": converted,
                    })

            elif pending["type"] == "rising_water":
                wx, wy = pending["center"]
                expanded = []
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = wx + dx, wy + dy
                    if (0 <= nx < self.width and 0 <= ny < self.height
                            and self.terrain[ny][nx] in ("OPEN", "ROAD") and len(expanded) < 1):
                        self.terrain[ny][nx] = "WATER"
                        self.pheromone_danger[ny][nx] = 1.0
                        expanded.append([nx, ny])
                        for agent in self.grid.get_cell_list_contents([(nx, ny)]):
                            if isinstance(agent, SurvivorAgent) and agent.alive:
                                agent.alive = False
                                agent.health = 0
                if expanded:
                    self.disaster_events.append({
                        "type": "rising_water",
                        "step": self.mission_step,
                        "source": [wx, wy],
                        "flooded_cells": expanded,
                    })

            elif pending["type"] == "blackout":
                self.trigger_blackout(*pending["center"], pending["radius"])

            # Mark corresponding warning as resolved
            for w in self.warning_events:
                if (w.get("pending_id") == id(pending) and not w.get("resolved")):
                    w["resolved"] = True

        self.pending_disasters = remaining

    def _check_aftershock(self):
        """Random aftershock: ~10% chance per step after step 8. Schedules for next step."""
        if self.mission_step < 8:
            return
        if self._rng.random() > 0.10:
            return

        cx = self._rng.randint(1, self.width - 2)
        cy = self._rng.randint(1, self.height - 2)

        pending = {
            "type": "aftershock",
            "fire_at_step": self.mission_step + 1,
            "center": (cx, cy),
        }
        self.pending_disasters.append(pending)
        self.warning_events.append({
            "type": "aftershock_warning",
            "step": self.mission_step,
            "estimated_center": [cx, cy],
            "message": "Seismic activity detected — aftershock imminent!",
            "resolved": False,
            "pending_id": id(pending),
        })

    def _check_rising_water(self):
        """Random rising water: ~7% chance per step after step 12. Schedules for next step."""
        if self.mission_step < 12:
            return
        if self._rng.random() > 0.07:
            return

        water_cells = [
            (x, y) for x in range(self.width) for y in range(self.height)
            if self.terrain[y][x] == "WATER"
        ]
        if not water_cells:
            return

        wx, wy = self._rng.choice(water_cells)

        pending = {
            "type": "rising_water",
            "fire_at_step": self.mission_step + 1,
            "center": (wx, wy),
        }
        self.pending_disasters.append(pending)
        self.warning_events.append({
            "type": "rising_water_warning",
            "step": self.mission_step,
            "estimated_center": [wx, wy],
            "message": "Water levels rising — flooding imminent!",
            "resolved": False,
            "pending_id": id(pending),
        })

    # ── Demo scripted events ─────────────────────────────────────────

    def _demo_scripted_events(self):
        """Deterministic demo events at specific steps.
        Warnings fire 1 step before; _process_pending_disasters() fires the actual event.
        """
        step = self.mission_step

        # Step 1: Emit aftershock warning for (5,4), schedule aftershock for step 2
        if step == 1:
            pending = {
                "type": "aftershock",
                "fire_at_step": 2,
                "center": (5, 4),
            }
            self.pending_disasters.append(pending)
            self.warning_events.append({
                "type": "aftershock_warning",
                "step": step,
                "estimated_center": [5, 4],
                "message": "Seismic activity detected — aftershock imminent near (5,4)!",
                "resolved": False,
                "pending_id": id(pending),
            })

        # Step 2: _process_pending_disasters() fires the aftershock (handled above)

        # Step 3: Emit blackout warning for (8,8) r=3, schedule blackout for step 4
        elif step == 3:
            pending = {
                "type": "blackout",
                "fire_at_step": 4,
                "center": (8, 8),
                "radius": 3,
            }
            self.pending_disasters.append(pending)
            self.warning_events.append({
                "type": "blackout_warning",
                "step": step,
                "estimated_center": [8, 8],
                "message": "Communication interference building — blackout imminent at (8,8) r=3!",
                "resolved": False,
                "pending_id": id(pending),
            })

        # Step 4: _process_pending_disasters() fires the blackout

        # Step 6: Blackout clears + emit rising water warning for (10,7)
        elif step == 6:
            if self.blackout_zones:
                self.blackout_zones.clear()
                for drone in self.drones.values():
                    drone.connected = True
                self.disaster_events.append({
                    "type": "blackout_cleared",
                    "step": step,
                    "message": "Communication blackout has lifted. All drones reconnected.",
                })

            pending = {
                "type": "rising_water",
                "fire_at_step": 7,
                "center": (10, 7),
            }
            self.pending_disasters.append(pending)
            self.warning_events.append({
                "type": "rising_water_warning",
                "step": step,
                "estimated_center": [10, 7],
                "message": "Water levels rising — flooding imminent near (10,7)!",
                "resolved": False,
                "pending_id": id(pending),
            })

        # Step 7: _process_pending_disasters() fires the rising water

    # ── Digital twin / mission simulation ─────────────────────────────

    def simulate_mission(self, drone_id, target_x, target_y):
        """Predict cost and feasibility of sending a drone to a target."""
        drone = self.drones.get(drone_id)
        if not drone:
            return {"success": False, "reason": "drone not found"}
        if drone.status in ("dead", "relay"):
            return {"success": False, "reason": f"drone is {drone.status}"}

        dist_to_target = manhattan_distance(drone.pos, (target_x, target_y))
        dist_to_base = manhattan_distance((target_x, target_y), BASE_POS)

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
        # Recompute mesh so SSE always pushes fresh topology
        self.mesh_topology = compute_mesh_topology(self.drones, BASE_POS)
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
            "base_position": list(BASE_POS),
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
            "warning_events": [
                {k: v for k, v in w.items() if k != "pending_id"}
                for w in self.warning_events
            ],
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
            "score": self.compute_score(),
        }

    # ── Scoring engine ──────────────────────────────────────────────

    def record_rescue(self, drone_id, survivor_id, severity, health):
        """Record a rescue event and update the mission score."""
        base_points = {"CRITICAL": 100, "MODERATE": 70, "STABLE": 50}.get(severity, 50)
        health_bonus = round(health * 50)
        max_steps = int(os.environ.get("MAX_MISSION_STEPS", "50"))
        speed_bonus = 20 if self.mission_step < max_steps / 2 else 0
        points = base_points + health_bonus + speed_bonus

        event = {
            "survivor_id": survivor_id,
            "severity": severity,
            "health_at_rescue": round(health, 2),
            "step": self.mission_step,
            "points": points,
            "drone_id": drone_id,
        }
        self.rescue_events.append(event)
        self.mission_score += points

    def compute_score(self):
        """Compute full mission score breakdown."""
        rescue_points = sum(e["points"] for e in self.rescue_events)
        speed_bonus = sum(
            20 for e in self.rescue_events
            if e["step"] < int(os.environ.get("MAX_MISSION_STEPS", "50")) / 2
        )

        coverage_pct = len(self.scanned_cells) / (self.width * self.height) * 100
        coverage_bonus = min(200, round(coverage_pct * 2))

        # Death penalty: survivors who died while active drones exist
        active_drones = sum(1 for d in self.drones.values() if d.status == "active")
        deaths = sum(
            1 for s in self.survivors
            if not s.alive and not s.rescued and active_drones > 0
        )
        death_penalty = deaths * 30

        # Efficiency bonus: remaining battery across active drones
        remaining_battery = sum(d.battery for d in self.drones.values() if d.status == "active")
        efficiency_bonus = round(remaining_battery / 10)

        total = rescue_points + coverage_bonus + efficiency_bonus - death_penalty

        if total >= 500:
            grade = "A"
        elif total >= 350:
            grade = "B"
        elif total >= 200:
            grade = "C"
        elif total >= 100:
            grade = "D"
        else:
            grade = "F"

        return {
            "total": total,
            "grade": grade,
            "rescue_points": rescue_points,
            "speed_bonus": speed_bonus,
            "coverage_bonus": coverage_bonus,
            "death_penalty": death_penalty,
            "efficiency_bonus": efficiency_bonus,
            "rescues": len(self.rescue_events),
            "rescue_events": self.rescue_events,
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
