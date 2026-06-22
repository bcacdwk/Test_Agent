"""FastMCP server entry point.

The server is intentionally not activated in `.codex/config.example.toml`.
Real tools should be registered only after driver safety policies exist.
"""

from fastmcp import FastMCP

mcp = FastMCP(
    name="b1500-test-agent",
    description="Safety-gated B1500A semiconductor test-agent MCP server skeleton.",
)


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
