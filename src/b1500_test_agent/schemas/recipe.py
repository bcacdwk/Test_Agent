"""Measurement recipe schemas."""

from pydantic import BaseModel


class MeasurementRecipe(BaseModel):
    """Generic measurement recipe metadata."""

    name: str
    intent: str
    required_capabilities: list[str] = []
    safety_policy: str | None = None
    validated: bool = False
