"""Cleanup step 4 v2 on the hardware path (blueprint v2 2.6; WP8.1): ``DCV ch,0`` and ``ACV ch,0`` for the MFCMUs the
driver drove (when ``LOP?`` still shows them on), then ``DZ``; a failure of the MFCMU part never skips ``DZ`` and
fails the step, so the retry repeats both; a driver that drove no MFCMU sends exactly the v1 sequence."""

from __future__ import annotations

from b1500_test_agent.driver.b1500 import B1500Driver, CmuSignal
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.session.transaction import run_cleanup
from tests.unit.driver_helpers import ReadTimeout, SpyTransport

CMU = 7
ENVELOPE = CompiledEnvelope(channels={CMU: ChannelEnvelope(
    role="a", max_abs_v=2.0, max_abs_i=1e-3, function="cmu_high",
    ac=AcEnvelope(max_vrms=0.05, max_dc_v=2.0, f_min_hz=1e3, f_max_hz=1e6))})
LOP_CMU_ON = "LOP00,00,00,00,00,00,40,00,00,00"
LOP_OFF = "LOP00,00,00,00,00,00,00,00,00,00"
NO_ERROR = '0,"No Error."'


class HwSpy(SpyTransport):
    backend = "visa"


class Events:
    def __init__(self) -> None:
        self.steps: list[tuple[str, bool, str]] = []

    def __call__(self, ev: str, data: dict[str, object] | None = None, *, error: str | None = None) -> None:
        if ev == "cleanup_step" and data:
            self.steps.append((str(data["step"]), bool(data["ok"]), str(data["detail"])))


def driven(spy: HwSpy) -> B1500Driver:
    driver = B1500Driver(spy, OutputGuard(ENVELOPE))  # type: ignore[arg-type]
    driver.apply_cmu_signal(CMU, CmuSignal(freq_hz=1e5, ac_vrms=0.03, dc_v=1.0))
    spy.sent.clear()
    return driver


def test_the_mfcmu_is_zeroed_before_dz() -> None:
    spy = HwSpy(answers={"LOP?": [LOP_CMU_ON, LOP_OFF], "ERRX?": NO_ERROR})
    events = Events()
    report = run_cleanup(driven(spy), always_abort=False, emit=events).report
    assert spy.sent == ["LOP?", "DCV 7,0", "ACV 7,0", "DZ", "CL", "ERRX?", "LOP?"]
    assert report.verified == "lop"
    assert events.steps[0] == ("zero", True, "all channels; MFCMU 7 DC 0 V, AC 0 V")


def test_a_failing_mfcmu_zero_still_sends_dz_and_retries() -> None:
    lop = [ReadTimeout("LOP? timed out"), LOP_OFF, LOP_CMU_ON, LOP_OFF]  # zero 1, verify 1, zero 2, verify 2
    spy = HwSpy(answers={"LOP?": lop, "ERRX?": NO_ERROR})
    events = Events()
    report = run_cleanup(driven(spy), always_abort=False, emit=events).report
    assert spy.sent[:5] == ["LOP?", "DZ", "CL", "ERRX?", "LOP?"]  # attempt 1: the MFCMU part failed, DZ went out
    assert spy.sent[5:] == ["LOP?", "DCV 7,0", "ACV 7,0", "DZ", "CL", "ERRX?", "LOP?"]  # attempt 2 repeats both
    assert events.steps[0][:2] == ("zero", False) and "LOP? timed out" in events.steps[0][2]
    assert ("device_clear", True) in [(s, ok) for s, ok, _ in events.steps]
    assert report.verified == "lop"


def test_without_an_mfcmu_the_cleanup_is_unchanged() -> None:
    spy = HwSpy(answers={"LOP?": LOP_OFF, "ERRX?": NO_ERROR})
    run_cleanup(B1500Driver(spy), always_abort=False, emit=Events())  # type: ignore[arg-type]
    assert spy.sent == ["DZ", "CL", "ERRX?", "LOP?"]
