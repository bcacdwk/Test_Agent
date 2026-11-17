"""Fixture builders for the analysis tests: manifests, analytic MOSFET curves, tidy tables and run folders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from b1500_test_agent.analysis.dataset import (
    DATA_FILE,
    INDEX_FILE,
    MANIFEST_FILE,
    RunData,
    run_relpath,
    with_trust,
    write_table,
)
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.common import ConfigFile
from b1500_test_agent.models.plan import (
    BoundChannel,
    ChannelBinding,
    ChannelEnvelope,
    CompiledEnvelope,
    Estimate,
    PlanRecord,
    PlanRequest,
    RulesReport,
)
from b1500_test_agent.models.run import ClientInfo, RunManifest

T0 = datetime(2026, 11, 17, 6, 30, 12, tzinfo=UTC)
SHA = "0" * 64
RUN_ID = "S20261117T063012Z-7f3a"
VTH = 0.42
VD = 0.05
BETA = 2.0e-3


def plan_record(*, params: dict[str, Quantity] | None = None, recipe_id: str = "mosfet.idvg",
                kind: str = "smu_staircase") -> PlanRecord:
    resolved = params if params is not None else {
        "vg_start": Quantity(value=-1.0, unit="V"), "vg_stop": Quantity(value=3.0, unit="V"),
        "vg_points": Quantity(value=101), "vd": Quantity(value=VD, unit="V"),
    }  # fmt: skip
    report = RulesReport.from_findings("plan", [], policy_digest=SHA, evaluated_at=T0)
    return PlanRecord(
        plan_id="P-ABCDEFGH23",
        plan_hash="a" * 64,
        request=PlanRequest(recipe_id=recipe_id, pin_map="mosfet-4t", dut_profile="nmos-generic"),
        recipe_id=recipe_id,
        recipe_version=1,
        recipe_sha="b" * 64,
        kind=kind,
        resolved_params=resolved,
        binding=ChannelBinding(pin_map="mosfet-4t", roles={
            "gate": BoundChannel(role="gate", terminal="gate", channel=1, slot=1, module_type="MPSMU"),
            "drain": BoundChannel(role="drain", terminal="drain", channel=3, slot=3, module_type="HRSMU"),
            "source": BoundChannel(role="source", terminal="source", gndu=True),
        }),
        envelope=CompiledEnvelope(channels={1: ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=1e-6),
                                            3: ChannelEnvelope(role="drain", max_abs_v=VD, max_abs_i=1e-3)}),
        estimate=Estimate(points=101, duration_s=2.5),
        flex_preview=[],
        hashes={"station": SHA, "policy": SHA, "pin_map": SHA, "dut_profile": SHA},
        backend="sim",
        rules=report,
        tier=report.tier,
        summary=f"{recipe_id}@1 | gate=SMU1 sweep -1..3 V | drain=SMU3 bias 0.05 V | sim",
        created_at=T0,
        expires_at=T0 + timedelta(hours=24),
    )


def manifest(run_id: str = RUN_ID, *, files: dict[str, str] | None = None, **plan_kwargs: Any) -> RunManifest:
    plan = plan_record(**plan_kwargs)
    return RunManifest(
        run_id=run_id,
        plan=plan,
        plan_hash=plan.plan_hash,
        recipe_id=plan.recipe_id,
        recipe_version=1,
        recipe_sha=plan.recipe_sha,
        recipe_status="sim_validated",
        backend="sim",
        simulated=True,
        hashes=plan.hashes,
        config_files=[ConfigFile(key="policy", path="config/policy.example.yaml", source="example", sha256=SHA)],
        rules=[plan.rules],
        tier=plan.tier,
        client=ClientInfo(adapter="cli"),
        software_version="test",
        started_at=T0,
        finished_at=T0 + timedelta(seconds=3),
        outcome="completed",
        files=files or {},
    )


def linear_region_id(vg: np.ndarray, *, vth: float = VTH, vd: float = VD, beta: float = BETA) -> np.ndarray:
    """Closed-form long-channel drain current at small Vd: 0 below Vth, beta*u^2/2 for 0 < u < Vd (u = Vg - Vth),
    beta*(u - Vd/2)*Vd above (the linear region). Its linear-region Vg-axis intercept is exactly Vth + Vd/2."""
    u = np.asarray(vg, dtype=float) - vth
    return np.where(u <= 0, 0.0, np.where(u < vd, beta * u * u / 2, beta * (u - vd / 2) * vd))


def ekv_like_id(vg: np.ndarray, *, vth: float = VTH, vd: float = VD, beta: float = BETA, n: float = 1.3,
                theta: float = 0.2, phi_t: float = 0.02585) -> np.ndarray:
    """Smooth EKV-style transfer curve (subthreshold to strong inversion) with mobility degradation, so gm has a
    clear peak near threshold, as in the simulator's ``mosfet_ekv`` scenario. Not a closed-form Vth truth."""
    vp = (np.asarray(vg, dtype=float) - vth) / n

    def f(v: np.ndarray) -> np.ndarray:
        return np.logaddexp(0.0, v / (2 * phi_t)) ** 2

    current = 2 * n * beta * phi_t**2 * (f(vp) - f(vp - vd))
    return current / (1 + theta * np.clip(np.asarray(vg, dtype=float) - vth, 0.0, None))


def idvg_table(vg: Sequence[float], drain_i: Sequence[float], *, drain_status: Sequence[str] | None = None,
               gate_i: Sequence[float] | None = None, gate_status: Sequence[str] | None = None,
               segment: Sequence[str] | None = None) -> pd.DataFrame:
    """A tidy Id-Vg table: source ``gate_V``, measured ``gate_I`` and ``drain_I`` with status letters, ``trust``."""
    n = len(vg)
    columns: dict[str, Any] = {"step": np.arange(n)}
    if segment is not None:
        columns["segment"] = list(segment)
    columns["gate_V"] = np.asarray(vg, dtype=float)
    columns["gate_I"] = np.asarray(gate_i if gate_i is not None else np.full(n, 1e-13), dtype=float)
    columns["gate_I_status"] = list(gate_status) if gate_status is not None else ["N"] * n
    columns["drain_I"] = np.asarray(drain_i, dtype=float)
    columns["drain_I_status"] = list(drain_status) if drain_status is not None else ["N"] * n
    return with_trust(pd.DataFrame(columns))


def write_run(data_root: Path, table: pd.DataFrame, run_manifest: RunManifest | None = None, *,
              folder: Path | None = None, with_digest: bool = True) -> Path:
    """Write a run folder like the archive does: ``data.csv`` then ``manifest.json`` (with the data digest)."""
    run_manifest = run_manifest if run_manifest is not None else manifest()
    run_dir = folder if folder is not None else data_root / "runs" / Path(*run_relpath(run_manifest.run_id).parts)
    data_path = write_table(table, run_dir / DATA_FILE)
    if with_digest:
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        run_manifest = run_manifest.model_copy(update={"files": {DATA_FILE: digest}})
    (run_dir / MANIFEST_FILE).write_text(run_manifest.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    return run_dir


def append_index(data_root: Path, run_id: str, path: str) -> None:
    index = data_root / "runs" / INDEX_FILE
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"run_id": run_id, "path": path, "outcome": "completed"}) + "\n")


def iv_table(source: dict[str, Sequence[float]], measured: dict[str, Sequence[float]], *,
             status: dict[str, Sequence[str]] | None = None, segment: Sequence[str] | None = None) -> pd.DataFrame:
    """A tidy table of any shape: ``source`` columns (programmed values), ``measured`` columns with status letters
    (``status`` per measured column, default all ``N``), optional ``segment``; ``trust`` computed."""
    n = len(next(iter(source.values())))
    columns: dict[str, Any] = {"step": np.arange(n)}
    if segment is not None:
        columns["segment"] = list(segment)
    for name, values in source.items():
        columns[name] = np.asarray(values, dtype=float)
    for name, values in measured.items():
        columns[name] = np.asarray(values, dtype=float)
        columns[f"{name}_status"] = list((status or {}).get(name, ["N"] * n))
    return with_trust(pd.DataFrame(columns))


def run_of(table: pd.DataFrame, recipe_id: str, *, kind: str = "smu_staircase",
           params: dict[str, Quantity] | None = None) -> RunData:
    """``RunData`` of ``table`` under a manifest of ``recipe_id``/``kind`` with resolved ``params``."""
    return RunData(manifest(recipe_id=recipe_id, kind=kind, params=params or {}), table)


def subthreshold_id(vg: np.ndarray, *, v0: float = 0.3, i0: float = 1e-7, ss_mv: float = 80.0,
                    i_on: float = 1e-4) -> np.ndarray:
    """Exponential subthreshold current ``i0 * 10**((vg - v0) / ss)`` that saturates smoothly towards ``i_on``
    (harmonic sum), so the steepest slope (the SS truth) is in the exponential part."""
    exp = i0 * 10 ** ((np.asarray(vg, dtype=float) - v0) / (ss_mv / 1000.0))
    return 1.0 / (1.0 / exp + 1.0 / i_on)


def output_family(vd: np.ndarray, vg_levels: Sequence[float], *, vth: float = 0.4, beta: float = 1e-3,
                  lam: float = 0.05) -> pd.DataFrame:
    """Square-law Id-Vd family (triode beta (Vov Vd - Vd^2/2), saturation beta Vov^2/2 (1 + lam (Vd - Vov))) as a
    stepped table: source ``drain_V``/``gate_V``, measured ``drain_I``. Truth: Ron = 1/(beta Vov), gds =
    lam beta Vov^2/2, Vd_sat(gd = 0.1 g0) = 0.9 Vov."""
    rows_vd, rows_vg, rows_id = [], [], []
    for vg in vg_levels:
        vov = vg - vth
        triode = beta * (vov * vd - vd**2 / 2)
        sat = beta * vov**2 / 2 * (1 + lam * (vd - vov))
        rows_vd += list(vd)
        rows_vg += [vg] * len(vd)
        rows_id += list(np.where(vd < vov, triode, sat))
    return iv_table({"drain_V": rows_vd, "gate_V": rows_vg}, {"drain_I": rows_id})
