"""SMU module capability definitions."""

from b1500_test_agent.instruments.b1500.safety import Limit


SMU_LIMITS: dict[str, Limit] = {
    "HPSMU": Limit(max_voltage_v=200.0, max_current_a=1.0),
    "MPSMU": Limit(max_voltage_v=100.0, max_current_a=0.1),
    "HRSMU": Limit(max_voltage_v=100.0, max_current_a=0.1),
    "MCSMU": Limit(max_voltage_v=30.0, max_current_a=1.0),
}
