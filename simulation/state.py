"""Shared singleton DisasterModel instance for MCP server + API bridge."""

import os

from .model import DisasterModel

_model = None


def _read_env():
    """Read simulation config from environment variables."""
    return {
        "width": int(os.environ.get("GRID_WIDTH", "12")),
        "height": int(os.environ.get("GRID_HEIGHT", "12")),
        "num_drones": int(os.environ.get("NUM_DRONES", "4")),
        "num_survivors": int(os.environ.get("NUM_SURVIVORS", "8")),
        "demo_mode": os.environ.get("DEMO_MODE", "0") == "1",
    }


def get_model():
    """Get or create the shared DisasterModel instance."""
    global _model
    if _model is None:
        cfg = _read_env()
        _model = DisasterModel(
            seed=42,
            width=cfg["width"],
            height=cfg["height"],
            num_drones=cfg["num_drones"],
            num_survivors=cfg["num_survivors"],
            demo_mode=cfg["demo_mode"],
        )
    return _model


def reset_model(seed=42):
    """Reset the simulation with a new model."""
    global _model
    cfg = _read_env()
    _model = DisasterModel(
        seed=seed,
        width=cfg["width"],
        height=cfg["height"],
        num_drones=cfg["num_drones"],
        num_survivors=cfg["num_survivors"],
        demo_mode=cfg["demo_mode"],
    )
    return _model
