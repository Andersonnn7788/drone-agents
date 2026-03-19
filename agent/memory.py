"""Cross-mission memory persistence — lessons learned from past missions."""

import json
import os
from pathlib import Path

LESSONS_FILE = Path("logs/lessons_learned.json")
MAX_LESSONS = 15


def load_lessons() -> list[dict]:
    """Read lessons from disk."""
    if not LESSONS_FILE.exists():
        return []
    try:
        with open(LESSONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_lessons(lessons: list[dict]):
    """Write lessons to disk, trimming to MAX_LESSONS."""
    os.makedirs(LESSONS_FILE.parent, exist_ok=True)
    trimmed = lessons[-MAX_LESSONS:]
    with open(LESSONS_FILE, "w") as f:
        json.dump(trimmed, f, indent=2, default=str)


def add_lessons(new_lessons: list[dict], mission_num: int, score: dict):
    """Append new lessons with metadata and save."""
    existing = load_lessons()
    for lesson in new_lessons:
        lesson["mission_num"] = mission_num
        lesson["mission_score"] = score.get("total", 0)
        lesson["mission_grade"] = score.get("grade", "?")
    existing.extend(new_lessons)
    save_lessons(existing)


def format_lessons_for_prompt(lessons: list[dict]) -> str:
    """Format lessons as a numbered list for system prompt injection."""
    if not lessons:
        return ""
    lines = []
    for i, lesson in enumerate(lessons, 1):
        text = lesson.get("lesson", "")
        evidence = lesson.get("evidence", "")
        priority = lesson.get("priority", "medium")
        mission = lesson.get("mission_num", "?")
        grade = lesson.get("mission_grade", "?")
        lines.append(
            f"{i}. [{priority.upper()}] (Mission #{mission}, Grade {grade}) {text}"
        )
        if evidence:
            lines.append(f"   Evidence: {evidence}")
    return "\n".join(lines)


def get_mission_count() -> int:
    """Count completed missions based on unique mission numbers in lessons."""
    lessons = load_lessons()
    if not lessons:
        return 0
    mission_nums = {l.get("mission_num", 0) for l in lessons}
    return max(mission_nums) if mission_nums else 0
