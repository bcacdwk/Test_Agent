"""MFCMU correction store (blueprint v2 2.6, decision 11; WP5.7): ``<state_dir>/corrections/<alias>.json``, atomic
writes, readers, pruning, alias safety, corrupt files, the freshness query state by state, and agreement with rule
R-CORR-01's plan-phase verdict on the same records."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from b1500_test_agent.archive import CorrectionStore, CorrectionStoreError, add_record, freshness, records_for
from b1500_test_agent.archive.corrections import MAX_RECORDS_PER_KIND, freshness_for
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.policy import CorrectionPolicy, Policy
from b1500_test_agent.models.station import CorrectionFreshness, CorrectionRecord
from b1500_test_agent.paths import ENV_DATA_DIR
from tests.unit.rules_factory import T0, ZERO_SHA, engine
from tests.unit.test_rules_builtin import cmu, corr

IDN = "Keysight Technologies,B1500A,SIM1,A.06"
OTHER = "d" * 64
POLICY = CorrectionPolicy()


def record(kind: str, freqs: tuple[float, ...] = (1e3, 1e5, 1e6), *, age_h: float = 1.0, run: str = "00cd",
           **changes: Any) -> CorrectionRecord:
    return corr(kind, freqs, age_h=age_h).model_copy(update={"run_id": f"S20261117T053012Z-{run}", **changes})


def query(records: list[CorrectionRecord], **kw: Any) -> CorrectionFreshness:
    kw.setdefault("require", ["phase", "open", "short"])
    kw.setdefault("max_age_h", 8.0)
    kw.setdefault("now", T0)
    return freshness("CMU1", records, **kw)


# -- Store -----------------------------------------------------------------------------------------------------------


def test_records_are_stored_as_a_json_list_oldest_first(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    assert store.records("CMU1") == [] and store.aliases() == [] and store.all() == {}
    newer, older = record("open", age_h=1.0, run="0002"), record("phase", age_h=3.0, run="0001")
    store.add("CMU1", newer)
    stored = store.add("CMU1", older)
    assert stored == [older, newer] and store.records("CMU1") == [older, newer]
    path = tmp_path / "corrections" / "CMU1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and [d["run_id"] for d in data] == [older.run_id, newer.run_id]
    assert sorted(p.name for p in path.parent.iterdir()) == ["CMU1.json"]  # atomic write leaves no temp file
    assert store.aliases() == ["CMU1"] and store.all() == {"CMU1": [older, newer]}


def test_each_kind_keeps_its_newest_records(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    for i in range(MAX_RECORDS_PER_KIND + 5):
        store.add("CMU1", record("open", age_h=100.0 - i, run=f"{i:04x}"))
    store.add("CMU1", record("phase", age_h=200.0, run="ffff"))
    stored = store.records("CMU1")
    opens = [r for r in stored if r.kind == "open"]
    assert len(opens) == MAX_RECORDS_PER_KIND and opens[0].run_id.endswith(f"{5:04x}")
    assert [r.kind for r in stored].count("phase") == 1


@pytest.mark.parametrize("alias", ["../CMU1", "CMU1/x", "", "1CMU", "C" * 33, "CMU 1", "CMU1.json"])
def test_aliases_cannot_escape_the_store(tmp_path: Path, alias: str) -> None:
    store = CorrectionStore(tmp_path)
    with pytest.raises(InvalidInputError):
        store.add(alias, record("phase"))
    with pytest.raises(InvalidInputError):
        store.records(alias)
    assert not (tmp_path / "corrections").exists()


@pytest.mark.parametrize("content", ["not json", '{"kind": "open"}', '[{"kind": "open"}]', "[1]"])
def test_a_corrupt_store_file_is_an_error_never_no_records(tmp_path: Path, content: str) -> None:
    store = CorrectionStore(tmp_path)
    store.path("CMU1").parent.mkdir(parents=True)
    store.path("CMU1").write_text(content, encoding="utf-8")
    with pytest.raises(CorrectionStoreError, match="CMU1.json") as info:
        store.records("CMU1")
    assert info.value.code == "invalid_input"
    with pytest.raises(CorrectionStoreError):
        store.add("CMU1", record("phase"))
    assert store.clear("CMU1") == 0 and store.records("CMU1") == []


def test_clear_removes_the_records(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path)
    store.add("CMU1", record("phase"))
    store.add("CMU1", record("open"))
    assert store.clear("CMU1") == 2 and store.records("CMU1") == [] and store.clear("CMU1") == 0


def test_module_functions_default_to_the_configured_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    assert records_for("CMU1") == []
    add_record("CMU1", record("phase"))
    assert (tmp_path / "state" / "corrections" / "CMU1.json").is_file()
    assert records_for("CMU1") == [record("phase")]
    assert records_for("CMU1", state_dir=tmp_path / "elsewhere") == []
    result = freshness_for("CMU1", POLICY, now=T0)
    assert [c.state for c in result.checks] == ["fresh", "missing", "missing"] and not result.fresh


# -- Freshness -------------------------------------------------------------------------------------------------------


def test_fresh_when_every_required_kind_passes() -> None:
    result = query([record("phase"), record("open"), record("short")], freqs_hz=[1e6, 1e3],
                   pin_map_sha=ZERO_SHA, station_sha=ZERO_SHA, idn=IDN)
    assert result.fresh and result.failing() == [] and result.freqs_hz == [1e3, 1e6]
    assert [(c.kind, c.state, c.age_h) for c in result.checks] == [("phase", "fresh", 1.0), ("open", "fresh", 1.0),
                                                                    ("short", "fresh", 1.0)]
    assert result.cmu == "CMU1" and result.checked_at == T0 and result.max_age_h == 8.0


@pytest.mark.parametrize(("records", "kw", "state", "extra"), [
    ([], {}, "missing", {"run_id": None}),
    ([record("open", station_sha=OTHER)], {"station_sha": ZERO_SHA}, "other_setup", {"run_id": None}),
    ([record("open", pin_map_sha=OTHER)], {"pin_map_sha": ZERO_SHA}, "other_setup", {"run_id": None}),
    ([record("open", idn="Other,B1500A,X,A.05")], {"idn": IDN}, "other_instrument", {"run_id": None}),
    ([record("open", age_h=9.0, run="0001"), record("open", age_h=12.0, run="0002")], {}, "stale",
     {"run_id": "S20261117T053012Z-0001", "age_h": 9.0}),
    ([record("open", (1e3, 1e5), run="0001"), record("open", (1e3,), age_h=4.0, run="0002")], {"freqs_hz": [1e6]},
     "uncovered", {"run_id": "S20261117T053012Z-0001", "missing_hz": [1e6]}),
    ([record("open", (1e3,), age_h=2.0, run="0001"), record("open", (1e6,), age_h=1.0, run="0002")],
     {"freqs_hz": [1e3, 1e6]}, "uncovered", {"run_id": "S20261117T053012Z-0002", "missing_hz": [1e3]}),
    ([record("open", age_h=3.0, run="0001"), record("open", (1e3,), age_h=1.0, run="0002")], {"freqs_hz": [1e6]},
     "fresh", {"run_id": "S20261117T053012Z-0001", "age_h": 3.0}),
])
def test_each_freshness_state(records: list[CorrectionRecord], kw: dict[str, Any], state: str,
                              extra: dict[str, Any]) -> None:
    check = query(records, require=["open"], **kw).checks[0]
    assert check.kind == "open" and check.state == state
    for name, value in extra.items():
        assert getattr(check, name) == value, name


def test_checks_run_in_rule_order() -> None:
    # another landing beats age: an old record of another pin map is "other_setup", not "stale"
    old_other = record("open", age_h=30.0, pin_map_sha=OTHER)
    assert query([old_other], require=["open"], pin_map_sha=ZERO_SHA).checks[0].state == "other_setup"
    assert query([old_other], require=["open"]).checks[0].state == "stale"  # pin map not asked
    # setup before instrument
    both = record("open", station_sha=OTHER, idn="Other")
    assert query([both], require=["open"], station_sha=ZERO_SHA, idn=IDN).checks[0].state == "other_setup"


def test_phase_compensation_covers_every_frequency() -> None:
    result = query([record("phase")], require=["phase"], freqs_hz=[1e3, 5e6])
    assert result.fresh and result.checks[0].missing_hz == []


def test_policy_can_add_load_and_duplicates_count_once() -> None:
    records = [record("phase"), record("open"), record("short")]
    with_load = query(records, require=["phase", "open", "short", "load", "open"])
    assert [c.kind for c in with_load.checks] == ["phase", "open", "short", "load"]
    assert [c.kind for c in with_load.failing()] == ["load"] and not with_load.fresh


def test_a_future_record_is_fresh_like_the_rule() -> None:
    assert query([record("open", age_h=-0.5)], require=["open"]).fresh


def test_freshness_rejects_inconsistent_answers() -> None:
    result = query([], require=["open"])
    with pytest.raises(ValueError, match="fresh"):
        CorrectionFreshness.model_validate({**result.model_dump(), "fresh": True})


# -- Agreement with R-CORR-01 ----------------------------------------------------------------------------------------

SCENARIOS: list[tuple[str, list[CorrectionRecord], Policy | None]] = [
    ("complete", [corr("phase"), corr("open"), corr("short")], None),
    ("none", [], None),
    ("short-missing", [corr("phase"), corr("open")], None),
    ("stale-open", [corr("phase"), corr("open", age_h=9.0), corr("short")], None),
    ("one-stale-one-fresh", [corr("phase"), corr("open", age_h=9.0), corr("open"), corr("short")], None),
    ("not-covering", [corr("phase"), corr("open", (1e3, 1e5)), corr("short")], None),
    ("other-station", [corr("phase"), corr("open"), corr("short", station_sha=OTHER)], None),
    ("load-required", [corr("phase"), corr("open"), corr("short")],
     Policy(corrections={"require": ["phase", "open", "short", "load"]})),
    ("load-present", [corr("phase"), corr("open"), corr("short"), corr("load")],
     Policy(corrections={"require": ["phase", "open", "short", "load"]})),
    ("longer-age", [corr("phase"), corr("open", age_h=9.0), corr("short")], Policy(corrections={"max_age_h": 10})),
]


@pytest.mark.parametrize(("name", "records", "policy"), SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_freshness_agrees_with_r_corr_01(name: str, records: list[CorrectionRecord], policy: Policy | None) -> None:
    kw: dict[str, Any] = {"corrections": {"CMU1": records}}
    if policy is not None:
        kw["cfg_policy"] = policy
    cfg, ctx = cmu(**kw)
    findings = [f for f in engine(cfg).evaluate(ctx, "plan").findings if f.rule_id == "R-CORR-01"]
    plan = ctx.plan
    freqs = [float(q.value) for q in plan.resolved_params.values() if q.unit == "Hz"]  # type: ignore[arg-type]
    result = freshness("CMU1", records, require=ctx.policy.corrections.require,
                       max_age_h=ctx.policy.corrections.max_age_h, now=plan.created_at, freqs_hz=freqs,
                       pin_map_sha=plan.hashes["pin_map"], station_sha=plan.hashes["station"])
    assert result.fresh == (not any(f.severity == "block" for f in findings)), (name, findings, result)
    assert {c.kind for c in result.failing()} == {f.subject.split(".", 1)[1] for f in findings}, name
    assert ctx.plan.created_at - timedelta(hours=1) == corr("phase").ts
