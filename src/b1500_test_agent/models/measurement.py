"""SMU measurement-setup models shared by recipes, measurement kinds and the driver.

Salvaged from the v0.2 ``schemas/c_flow.py`` (tag ``archive/v0.2-fake-mcp``) and trimmed to fields that map onto
FLEX parameters of the Keysight B1500 Series Programming Guide, Edition 15 ("PG"). PDF page numbers are physical
1-based pages of ``B1500A Programming Guide.pdf``.

These models state intent in physical units. They check only what the command syntax itself allows; module
capabilities (for example no high-resolution ADC on HCSMU/HVSMU/MCSMU), station inventory, policy limits and the
mapping of range values to FLEX range codes belong to ``rules/`` and ``driver/``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

CHANNEL_NUMBERS: frozenset[int] = frozenset(
    [*range(1, 11), *(slot * 100 + sub for slot in range(1, 11) for sub in (1, 2))]
)
"""Valid ``chnum`` values: slot 1-10, or subchannel 1/2 of slot 1-10 as 101, 102 ... 1001, 1002 (PG Table 4-1,
PDF 334)."""


def _check_channel(value: int) -> int:
    if value not in CHANNEL_NUMBERS:
        raise ValueError(f"Channel {value} is not a B1500 channel number (1-10, 101/102 ... 1001/1002).")
    return value


Channel = Annotated[int, AfterValidator(_check_channel)]
"""A ``chnum`` from PG Table 4-1; whether the station has a module there is checked against the inventory."""

SourceQuantity = Literal["V", "I"]
"""What a channel forces (or measures): voltage or current, as in ``OutputGuard.check`` and ``set_range``."""

NonNegative = Annotated[float, Field(ge=0)]

AdcType = Literal["high_speed", "high_resolution"]
"""``AAD``/``AIT`` type 0 and 1 (PG PDF 351, 356); the pulsed-measurement ADC (type 2) is not modelled in v1."""

AdcMode = Literal["auto", "manual", "plc"]
"""``AIT`` modes 0, 1 and 2 (PG PDF 357); mode 3 (measurement time) is not modelled in v1."""

_AIT_N_MAX: dict[tuple[str, str], int] = {
    ("high_speed", "auto"): 1023,
    ("high_speed", "manual"): 1023,
    ("high_speed", "plc"): 100,
    ("high_resolution", "auto"): 127,
    ("high_resolution", "manual"): 127,
    ("high_resolution", "plc"): 100,
}
"""Upper bound of ``AIT`` coefficient N per ADC type and mode (PG Table 4-21, PDF 358-359); the lower bound is 1."""


class _MeasurementModel(BaseModel):
    """Strict, immutable base: unknown fields, non-finite numbers and post-construction edits are rejected."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True, frozen=True)


class Integration(_MeasurementModel):
    """SMU A/D converter type and integration setting, as sent by ``AAD`` and ``AIT`` (PG PDF 351, 356-359).

    ``n`` is the ``AIT`` coefficient: the averaging-sample factor for the high-speed ADC, the integration-time factor
    for the high-resolution ADC (auto: N x initial time; manual: N x 80 us), and the number of power-line cycles in
    ``plc`` mode. The defaults are the instrument's initial settings (high-speed ADC, auto mode, N = 1). Recipe-level
    presets such as ``short|medium|long`` are mapped onto this model by the measurement kind.
    """

    adc: AdcType = "high_speed"
    mode: AdcMode = "auto"
    n: int = Field(default=1, ge=1, le=1023)

    @model_validator(mode="after")
    def _n_within_table_4_21(self) -> Integration:
        limit = _AIT_N_MAX[(self.adc, self.mode)]
        if self.n > limit:
            raise ValueError(f"AIT N for {self.adc} ADC in {self.mode} mode must be 1 to {limit}, got {self.n}.")
        return self


class Ranging(_MeasurementModel):
    """Measurement ranging of one SMU channel, as sent by ``RI``/``RV`` (PG Table 4-3, PDF 337; RI PDF 501, RV PDF 503).

    ``range_value`` is the range in A (``quantity="I"``) or V (``"V"``): the fixed range, or the lowest range used by
    limited auto ranging. It is 0 exactly when ``mode="auto"``. The driver maps it to the FLEX range code and rejects
    ranges the module does not have.
    """

    quantity: SourceQuantity = "I"
    mode: Literal["auto", "limited_auto", "fixed"] = "auto"
    range_value: NonNegative = 0.0

    @model_validator(mode="after")
    def _range_matches_mode(self) -> Ranging:
        if self.mode == "auto" and self.range_value != 0:
            raise ValueError("Auto ranging takes no range_value (use 0).")
        if self.mode != "auto" and self.range_value <= 0:
            raise ValueError(f"{self.mode} ranging needs a positive range_value.")
        return self


class SweepTiming(_MeasurementModel):
    """Staircase-sweep timing, as sent by ``WT hold,delay[,Sdelay[,Tdelay[,Mdelay]]]`` (PG PDF 564-565).

    All values in seconds; unset parameters are 0 on the instrument. WT is not effective for pulsed measurements.
    """

    hold_s: float = Field(default=0.0, ge=0, le=655.35)
    delay_s: float = Field(default=0.0, ge=0, le=65.535)
    step_delay_s: float = Field(default=0.0, ge=0, le=1.0)
    trigger_delay_s: float = Field(default=0.0, ge=0)
    measure_delay_s: float = Field(default=0.0, ge=0, le=65.535)

    @model_validator(mode="after")
    def _trigger_delay_within_delay(self) -> SweepTiming:
        if self.trigger_delay_s > self.delay_s:
            raise ValueError("trigger_delay_s (Tdelay) must not exceed delay_s.")
        return self


class BiasChannel(_MeasurementModel):
    """One constant DC bias held during a sweep, as sent by ``DV``/``DI`` (PG PDF 396, 391).

    ``level`` is in V for a voltage source and in A for a current source; ``compliance`` is the other quantity
    (A for ``source="V"``, V for ``source="I"``). Neither is defaulted, and 0 compliance is not allowed. With
    ``compliance_polarity="auto"`` the instrument uses the polarity of the output and the magnitude of
    ``compliance``, so it must be positive; ``"manual"`` uses the sign of ``compliance``. ``output_range`` and
    ``compliance_range`` are the lowest ranges for limited auto ranging in physical units (0 = auto).
    """

    channel: Channel
    source: SourceQuantity = "V"
    level: float
    compliance: float
    compliance_polarity: Literal["auto", "manual"] = "auto"
    output_range: NonNegative = 0.0
    compliance_range: NonNegative = 0.0

    @model_validator(mode="after")
    def _compliance_is_usable(self) -> BiasChannel:
        if self.compliance == 0:
            raise ValueError("Compliance 0 is not allowed.")
        if self.compliance_polarity == "auto" and self.compliance < 0:
            raise ValueError("With auto compliance polarity give the compliance magnitude (positive).")
        return self
