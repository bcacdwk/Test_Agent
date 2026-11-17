"""Buggy bodies never get a source command outside the envelope to the instrument (blueprint 3, 8.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.driver.guard import EnvelopeViolation
from tests.safety.helpers import DRAIN, ENVELOPE, GATE, assert_global_invariant, make_harness


def test_buggy_body_requesting_50_v_never_reaches_the_simulator(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    with pytest.raises(EnvelopeViolation) as caught, h.transaction() as tx:
        tx.driver.enable([GATE, DRAIN])
        tx.driver.force_v(DRAIN, 0.1, icomp=1e-3)
        tx.driver.force_v(GATE, 50.0, icomp=1e-6)
    assert caught.value.reason == "level_exceeds_envelope" and caught.value.limit == ENVELOPE.channels[GATE].max_abs_v
    assert_global_invariant(h)
    sources = [r for r in h.log if r.source]
    assert [r.command for r in sources] == ["DV 3,0,0.1,0.001"]
    assert not any(e.ev == "write" and e.cmd and "50" in e.cmd for e in h.events())
    violation = next(e for e in h.events() if e.ev == "envelope_violation")
    assert violation.data == {"reason": "level_exceeds_envelope", "channel": GATE, "quantity": "V", "level": 50.0,
                              "compliance": 1e-6, "limit": 2.0}
    assert tx.cleanup is not None and tx.cleanup.verified == "sim_state"


def test_buggy_sweep_beyond_the_envelope_is_refused_before_any_write(tmp_path: Path) -> None:
    from b1500_test_agent.driver.b1500 import StaircaseSetup

    h = make_harness(tmp_path)
    with pytest.raises(EnvelopeViolation), h.transaction() as tx:
        tx.driver.enable([GATE, DRAIN])
        tx.driver.staircase_v(StaircaseSetup(channel=GATE, start=0.0, stop=50.0, points=11, icomp=1e-6,
                                             measure=(DRAIN,)))
    assert_global_invariant(h)
    assert not any(r.mnemonic in {"MM", "WV", "WT", "WM"} for r in h.log)


def test_channel_outside_the_allowlist_is_never_connected(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    with pytest.raises(EnvelopeViolation) as caught, h.transaction() as tx:
        tx.driver.enable([GATE, 2])
    assert caught.value.reason == "channel_not_allowed"
    assert_global_invariant(h)
    assert not any(r.mnemonic == "CN" for r in h.log)


def test_transaction_without_envelope_has_no_guard(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    with pytest.raises(EnvelopeViolation) as caught, h.transaction(envelope=None) as tx:
        tx.driver.force_v(GATE, 0.1, icomp=1e-6)
    assert caught.value.reason == "no_guard"
    assert_global_invariant(h)
    assert not any(r.source for r in h.log)
