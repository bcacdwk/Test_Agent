"""Measurement result schemas."""

from pydantic import BaseModel


class MeasurementResult(BaseModel):
    """Generic measurement result metadata."""

    run_id: str
    status: str
    warnings: list[str] = []
    artifacts: list[str] = []
