"""Shared state between the agent runner and the API bridge.

Kept in a separate module to avoid Python's __main__ double-import problem
(running `python -m agent.runner` creates a separate module namespace from
`from agent.runner import ...`).
"""

import threading

_start_event: threading.Event | None = None
_mission_complete: bool = False


def get_start_trigger() -> threading.Event | None:
    return _start_event


def set_start_trigger(event: threading.Event):
    global _start_event
    _start_event = event


def is_mission_complete() -> bool:
    return _mission_complete


def set_mission_complete(value: bool = True):
    global _mission_complete
    _mission_complete = value
