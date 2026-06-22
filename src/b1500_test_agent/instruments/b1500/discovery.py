"""Module discovery helpers for the B1500A."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleInventoryEntry:
    """One installed module entry discovered from the instrument."""

    slot: int
    module_type: str
    channels: tuple[int, ...]
    alias: str | None = None


def parse_unt_response(response: str) -> list[ModuleInventoryEntry]:
    """Parse an `UNT?` response.

    TODO: Implement from the programming guide and validated hardware output.
    """
    _ = response
    return []
