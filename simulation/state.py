"""Shared singleton DisasterModel instance for MCP server + API bridge."""

from .model import DisasterModel

_model = None


def get_model():
    """Get or create the shared DisasterModel instance."""
    global _model
    if _model is None:
        _model = DisasterModel()
    return _model


def reset_model(seed=42):
    """Reset the simulation with a new model."""
    global _model
    _model = DisasterModel(seed=seed)
    return _model
