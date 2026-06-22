"""Session lifecycle and execution locking for a B1500A instance."""

from dataclasses import dataclass, field
from threading import RLock

from b1500_test_agent.instruments.b1500.transport import B1500Transport


@dataclass
class B1500Session:
    """Stateful session wrapper around a B1500A transport."""

    transport: B1500Transport
    lock: RLock = field(default_factory=RLock)
    connected: bool = False

    def identify(self) -> str:
        """Return instrument identity using `*IDN?`."""
        with self.lock:
            return self.transport.query("*IDN?")

    def safe_shutdown(self) -> None:
        """Best-effort safe shutdown sequence."""
        with self.lock:
            self.transport.write("DZ")
            self.transport.write("CL")
