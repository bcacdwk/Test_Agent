"""Transport abstractions for B1500A communication.

This module intentionally contains no real PyVISA calls yet. The first hardware
implementation should add a small adapter here and keep higher layers transport
agnostic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VisaResourceConfig:
    """Configuration for a VISA resource."""

    gpib_board: int = 0
    gpib_address: int = 17
    timeout_ms: int = 600_000
    read_termination: str = "\r\n"
    write_termination: str = "\r\n"
    visa_backend: str = ""

    @property
    def resource_name(self) -> str:
        """Return the VISA resource string for the configured GPIB address."""
        return f"GPIB{self.gpib_board}::{self.gpib_address}::INSTR"


class TransportNotImplementedError(NotImplementedError):
    """Raised when real hardware transport is requested before implementation."""


class B1500Transport:
    """Interface for B1500A transport adapters."""

    def query(self, command: str) -> str:
        """Send a query command and return its response."""
        raise TransportNotImplementedError("Real B1500A transport is not implemented yet.")

    def write(self, command: str) -> None:
        """Send a write command."""
        raise TransportNotImplementedError("Real B1500A transport is not implemented yet.")
