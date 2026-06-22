"""Typed FLEX command construction helpers."""

from dataclasses import dataclass, field


class UnsafeCommandError(ValueError):
    """Raised when a command sequence violates safety constraints."""


@dataclass
class FlexCommandBuilder:
    """Build FLEX command sequences with central safety checks."""

    commands: list[str] = field(default_factory=list)

    def add(self, command: str) -> "FlexCommandBuilder":
        """Add a single FLEX command after local validation."""
        normalized = command.strip()
        if not normalized:
            raise UnsafeCommandError("Empty FLEX commands are not allowed.")
        if ";" in normalized and normalized.split(";", 1)[0].upper() in {"*RST", "AB"}:
            raise UnsafeCommandError("*RST and AB must not be combined with other commands.")
        self.commands.append(normalized)
        return self

    def reset(self) -> "FlexCommandBuilder":
        """Append an instrument reset command."""
        return self.add("*RST")

    def enable_channels(self, channels: list[int]) -> "FlexCommandBuilder":
        """Append a channel enable command."""
        return self.add("CN " + ",".join(str(channel) for channel in channels))

    def zero_and_disable(self) -> "FlexCommandBuilder":
        """Append the standard safe cleanup sequence."""
        self.add("DZ")
        self.add("CL")
        return self

    def build(self) -> list[str]:
        """Return the command sequence."""
        return list(self.commands)
