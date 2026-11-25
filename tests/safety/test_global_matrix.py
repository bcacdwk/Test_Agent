"""The global safety matrix: every registered kind x every fault x every position with the global invariant v2
(WP11.3; blueprint v2 2.6, 4.3, 8.1 ``safety/``).

``test_the_matrix_covers_every_kind_fault_and_position`` enumerates ``default_kinds()`` x (``models.sim.FAULT_KINDS``
+ their recoverable forms + Ctrl-C + a buggy body + a cancel request) x {configure, route, pulse_on, execute,
readback, checkpoint, cleanup}: every cell either runs on at least one body of the kind (``global_matrix.BODIES``: one
per family path, e.g. ``pulse_read`` with an HV-SPGU, an SMU-pulse and a WGFMU source) or carries the written reason
it is genuinely inapplicable (the body never reaches the position, or the fault acts on something the body does not
do).
``test_global_invariant_v2`` runs every row on the real kind with both links spied and asserts, besides the invariant
itself (``assert_global_invariant_v2``):

- the fault was injected (the position was reached), and only expected exceptions left the transaction: the
  package's own errors, a guard refusal, a Ctrl-C, or the test's ``StopBody`` at position ``cleanup``;
- a Ctrl-C leaves as ``KeyboardInterrupt``, a buggy body's request as ``EnvelopeViolation``, and only a cancel
  request ends a run with ``RunCancelled`` (at the body's next boundary);
- the latch follows the fault: always after ``ALWAYS_LATCH`` faults, never after ``NEVER_LATCH`` faults, and any
  other latch only with a real unsafe state left on the simulator or a fault that keeps the cleanup from verifying.

``test_each_body_reaches_exactly_its_positions`` keeps the table honest (positions and features equal a clean run),
and ``test_the_invariant_check_catches`` shows that each clause of the check bites.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from b1500_test_agent.catalog.kinds import default_kinds
from b1500_test_agent.driver.guard import EnvelopeViolation
from b1500_test_agent.errors import B1500Error
from b1500_test_agent.models.sim import FAULT_KINDS
from b1500_test_agent.session.abort import RunCancelled
from b1500_test_agent.transport.sim.state import CommandRecord
from tests.safety import global_matrix as gm
from tests.sim.selector_helpers import selector_states
from tests.visa_loop.cases import recipe_families

FAMILY_MARKS = {"smu": pytest.mark.smu, "cmu": pytest.mark.cmu, "spgu": pytest.mark.spgu, "wgfmu": pytest.mark.wgfmu}


def _marks(name: str) -> list[pytest.MarkDecorator]:
    """The family markers of a body (``-m wgfmu`` selects the WGFMU rows)."""
    families = recipe_families(gm.registry().get(gm.BODY[name].recipe))
    return [FAMILY_MARKS[f] for f in sorted(families) if f in FAMILY_MARKS]


ROWS = [pytest.param(*row, marks=_marks(row[0]), id="-".join(row)) for row in gm.rows()]


def test_the_matrix_covers_every_kind_fault_and_position() -> None:
    kinds = set(default_kinds())
    assert len(kinds) == 14 and set(gm.KINDS) == kinds
    assert {body.kind for body in gm.BODIES} == kinds, "a registered kind has no body in the matrix"
    injected = {"keyboard_interrupt", "envelope_violation", "abort_request"}
    assert set(gm.FAULTS) == set(FAULT_KINDS) | injected | set(gm.RECOVERABLE_FORMS)
    assert all(gm.base_fault(form) in FAULT_KINDS for form in gm.RECOVERABLE_FORMS)
    assert len(gm.FAULTS) == len(set(gm.FAULTS)) == 25 + 6 + 3 and len(gm.POSITIONS) == 7
    table = gm.cells()
    assert set(table) == {(k, f, p) for k in kinds for f in gm.FAULTS for p in gm.POSITIONS}
    for cell, value in table.items():
        assert value, f"{cell}: neither a running body nor a written reason"
        if isinstance(value, str):
            assert all(len(reason.split(": ", 1)[-1]) > 20 for reason in value.split(" | ")), (cell, value)
    running = {(k, f, p) for (k, f, p), v in table.items() if isinstance(v, list)}
    assert {f for _, f, _ in running} == set(gm.FAULTS), "a fault runs nowhere"
    for kind in kinds:
        assert {p for k, _, p in running if k == kind} >= {"configure", "execute", "cleanup"}, kind
    for body in gm.BODIES:
        assert body.features <= set(gm.FEATURES) and body.stop_at in body.positions - {"cleanup"}, body.name
        assert body.positions >= {"configure", "cleanup"}, body.name
    assert len(ROWS) == len(set(gm.rows())) == sum(len(v) for v in table.values() if isinstance(v, list))


def test_every_family_path_of_every_kind_has_a_body() -> None:
    """The bodies of a kind drive every family path its registered recipes drive (``pulse_read``: HV-SPGU + SMU
    read, SMU pulse, WGFMU; ``system``: FLEX self-test and the WGFMU library's)."""
    registry = gm.registry()
    for kind in gm.KINDS:
        reached = set().union(*(recipe_families(registry.get(b.recipe)) for b in gm.BODIES if b.kind == kind))
        needed = set().union(*(recipe_families(registry.get(rid)) for rid in registry.ids()
                               if registry.get(rid).kind == kind))
        assert needed <= reached, f"{kind}: no body drives {sorted(needed - reached)}"


@pytest.mark.parametrize("name", [body.name for body in gm.BODIES])
def test_each_body_reaches_exactly_its_positions(name: str, tmp_path: Path) -> None:
    """A clean run of the body passes exactly its declared positions, does what its features say and leaves the
    instrument safe and verified."""
    h = gm.make_harness(tmp_path, name)
    assert h.execute() is None
    assert set(h.tracker.reached) | {"cleanup"} == gm.BODY[name].positions
    assert gm.observed_features(h) == set(gm.BODY[name].features)
    gm.assert_global_invariant_v2(h, h.tx)
    assert h.tx is not None and h.tx.cleanup is not None and h.tx.cleanup.verified == "sim_state"


@pytest.mark.parametrize(("name", "fault", "position"), ROWS)
def test_global_invariant_v2(name: str, fault: str, position: str, tmp_path: Path) -> None:
    h, raised = gm.run_row(tmp_path, name, fault, position)
    assert position in h.tracker.reached, f"{position} never reached: the fault was not injected"
    if position == "cleanup":
        assert isinstance(raised, gm.StopBody), f"expected the body's stop to leave the transaction, got {raised!r}"
    else:
        assert raised is None or isinstance(raised, (B1500Error, EnvelopeViolation, KeyboardInterrupt)), repr(raised)
        if fault == "keyboard_interrupt":
            assert type(raised) is KeyboardInterrupt
        if fault == "envelope_violation":
            assert isinstance(raised, EnvelopeViolation), repr(raised)
        assert isinstance(raised, RunCancelled) == (fault == "abort_request" and raised is not None), repr(raised)

    gm.assert_global_invariant_v2(h, h.tx)

    assert h.tx is not None and h.tx.cleanup is not None
    latched = h.tx.cleanup.latched_fault
    if fault in gm.ALWAYS_LATCH:
        assert latched, f"{fault}: {gm.ALWAYS_LATCH[fault]}, yet the cleanup verified"
    if fault in gm.NEVER_LATCH:
        assert not latched, f"{fault} latched the station: {h.tx.cleanup}"
    if latched and fault not in gm.VERIFICATION_BLOCKERS:
        unsafe = h.sim.instrument.unsafe_reasons()
        assert unsafe or any(selector_states(h.sim).values()), f"{fault} latched a safe instrument: {h.tx.cleanup}"


# -- the check bites --------------------------------------------------------------------------------------------------


def _foreign(h: gm.GlobalHarness, command: str) -> None:
    """Append a record of ``command`` to the simulator log as if it had reached the instrument."""
    mnemonic, _, rest = command.partition(" ")
    last = h.log[-1]
    h.log.append(CommandRecord(seq=last.seq + 1, ts=last.ts, clock_s=last.clock_s, line=command, command=command,
                               mnemonic=mnemonic, args=rest.split(",") if rest else [], outcome="ok",
                               source=mnemonic in ("DV", "ACV", "SSP")))


def _set_output(h: gm.GlobalHarness, channel: int) -> None:
    h.sim.instrument.state.channels[channel].output_on = True


MUTATIONS: dict[str, tuple[str, Callable[[gm.GlobalHarness], object], str]] = {
    "smu_level_beyond_the_envelope": ("staircase", lambda h: _foreign(h, "DV 4,0,30,1E-6"), "level outside"),
    "smu_on_a_channel_outside_the_plan": ("staircase", lambda h: _foreign(h, "DV 6,0,0.1,1E-6"), "allowlist"),
    "ac_level_beyond_the_envelope": ("cmu_measure", lambda h: _foreign(h, "ACV 7,0.25"), "ACV 7,0.25"),
    "route_outside_the_plan": ("pulse_read_spgu", lambda h: _foreign(h, "ERSSP 1,2"), "route outside the plan"),
    "output_left_on": ("staircase", lambda h: _set_output(h, 4), "output switch on"),
    "selector_left_off_rest": ("spgu_train", lambda h: h.sim.instrument.state.selector_ports.__setitem__(0, 2),
                               "0: 2"),
    "wgfmu_level_beyond_the_envelope": ("waveform", lambda h: h.spy.calls.append(("dc_force_voltage", (201, 9.0))),
                                        "beyond the envelope"),
    "wgfmu_connect_outside_the_plan": ("waveform", lambda h: h.spy.calls.append(("connect", (302,))),
                                       "outside the plan"),
    "raw_block_not_handed_over": ("staircase", lambda h: h.run.raw.pop(), "not handed to the run"),
    "marker_left_behind": ("staircase", lambda h: (h.state_dir / "inflight.json").write_text("{}", encoding="utf-8"),
                           "in-flight marker"),
}
"""A clean run, then one violation planted after the fact: the check must fail on each, for that reason."""


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_the_invariant_check_catches(mutation: str, tmp_path: Path) -> None:
    name, plant, reason = MUTATIONS[mutation]
    h = gm.make_harness(tmp_path, name)
    assert h.execute() is None
    gm.assert_global_invariant_v2(h, h.tx)
    plant(h)
    with pytest.raises(AssertionError, match=re.escape(reason)):
        gm.assert_global_invariant_v2(h, h.tx)
