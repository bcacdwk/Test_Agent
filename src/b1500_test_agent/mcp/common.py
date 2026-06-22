"""Shared helpers for the fake B1500A MCP tools."""

from collections.abc import Callable


def _fake_response(atom: str, flex_basis: list[str], **payload: object) -> dict:
    """Build a standard fake MCP response."""
    return {
        "atom": atom,
        "fake": True,
        "hardware_touched": False,
        "basis": flex_basis,
        **payload,
    }


def _parse_channels(channels: str) -> list[int]:
    """Parse a comma-separated channel list for fake channel-control tools."""
    if not channels.strip():
        return []
    return [int(part.strip()) for part in channels.split(",") if part.strip()]


# ---------------------------------------------------------------------------
# Flow helpers
#
# A_flow_* and B_flow_* tools compose only same-class atoms into ordered,
# serial operations.
# These helpers call the fake atom Python functions as subcommands and record
# every invocation verbatim so the flow response is audit-friendly. They never
# call cross-class atoms and never run anything concurrently.
# ---------------------------------------------------------------------------


def _atom_step(records: list[dict], atom: Callable[..., dict], /, **inputs: object) -> dict:
    """Invoke one fake atom subcommand and append an ordered audit record.

    Flows call atoms in series through this helper; real transport must stay
    serial because of the B1500A one-response query buffer and EasyEXPERT's
    single remote connection. The atom's returned data is preserved under
    ``result``.
    """
    result = atom(**inputs)
    records.append(
        {
            "atom": getattr(atom, "__name__", str(atom)),
            "inputs": dict(inputs),
            "status": "ok",
            "result": result,
        }
    )
    return result


def _atom_skip(records: list[dict], atom_name: str, reason: str, **inputs: object) -> None:
    """Record an atom that was intentionally not called (gate or opt-out).

    Skipped atoms stay in ``atom_results`` for audit but are excluded from
    ``atoms_called`` because they were never invoked.
    """
    records.append(
        {
            "atom": atom_name,
            "inputs": dict(inputs),
            "status": "skipped",
            "reason": reason,
            "result": None,
        }
    )


def _flow_response(
    flow: str,
    category: str,
    interface: str,
    subject: str,
    atom_results: list[dict],
    purpose: str,
    *,
    destructive: bool = False,
    consumptive: bool = False,
    ok: bool = True,
    partial: bool = False,
    warnings: list[str] | None = None,
    **extra: object,
) -> dict:
    """Build the standard fake A_flow response envelope.

    ``atoms_called`` is derived from atoms actually invoked (status ``ok``),
    preserving order and the duplicates produced by bounded loops. Flows remain
    fake and orchestration-only: they aggregate atom data without claiming any
    real hardware effect.
    """
    return {
        "flow": flow,
        "flow_class": "A",
        "category": category,
        "interface": interface,
        "subject": subject,
        "fake": True,
        "hardware_touched": False,
        "ok": ok,
        "partial": partial,
        "destructive": destructive,
        "consumptive": consumptive,
        "atoms_called": [record["atom"] for record in atom_results if record["status"] == "ok"],
        "atom_results": atom_results,
        "warnings": list(warnings or []),
        "purpose": purpose,
        **extra,
    }
