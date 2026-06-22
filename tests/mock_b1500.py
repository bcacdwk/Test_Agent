"""Mock B1500A transport for tests."""

from b1500_test_agent.instruments.b1500.transport import B1500Transport


class MockB1500Transport(B1500Transport):
    """Small deterministic transport for early unit tests."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def query(self, command: str) -> str:
        """Return canned responses for basic queries."""
        self.commands.append(command)
        if command == "*IDN?":
            return "Keysight Technologies,B1500A,MOCK,0"
        if command == "UNT?":
            return ""
        return ""

    def write(self, command: str) -> None:
        """Record a command."""
        self.commands.append(command)
