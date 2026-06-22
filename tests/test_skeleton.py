"""Basic skeleton tests."""

from b1500_test_agent.instruments.b1500.session import B1500Session

from tests.mock_b1500 import MockB1500Transport


def test_mock_identify() -> None:
    """The mock transport should support identity queries."""
    session = B1500Session(transport=MockB1500Transport())

    assert "B1500A" in session.identify()
