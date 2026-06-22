"""Measurement request schemas."""

from pydantic import BaseModel


class MeasurementRequest(BaseModel):
    """User intent after conversion to a structured request."""

    goal: str
    device_type: str | None = None
    recipe_name: str | None = None
    dry_run: bool = True
