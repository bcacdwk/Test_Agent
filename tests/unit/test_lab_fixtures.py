"""The lab fixtures (``tests/fixtures/lab/``, blueprint v2 4.4, 10.2 row 6.2; guardrail 10.0.8) are well formed,
anonymized and traceable to the read-only lab code.

Always: the three FLEX transcripts parse (every command has a mnemonic of the manual's command summary and names the
lwp file and line that sends it) and the Id-Vg fixture holds one 61-point curve whose header names only the
instrument model and firmware. With the lab code present (developer Mac: ``<manuals dir>/lwp/matlab_B1500``,
``B1500_MANUALS_DIR`` or the repository's parent; skipped elsewhere): every cited line really sends that command and
the data rows are exactly those of one ``IdVg_test_*.csv`` of the lab.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from b1500_test_agent.transport.sim import flex as simflex
from tests.unit.lab_fixtures import (
    LAB_DIR,
    READ,
    REAL_IDVG,
    SEQUENCES,
    LabSequence,
    LabStep,
    load_sequence,
    lwp_dir,
    real_idvg,
    real_idvg_header,
)

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "references" / "manuals" / "structured" / "b1500a-command-summary.yaml"


def manual_mnemonics() -> set[str]:
    data = yaml.safe_load(SUMMARY.read_text(encoding="utf-8"))
    names = {record["command"] for record in data["commands"]}
    for group in data["grouped_command_index"]:
        names.update(group["commands"])
    return names


def test_the_lab_folder_holds_exactly_the_planned_files() -> None:
    """Only the transcripts and the one Id-Vg curve; the second lwp data sample (``wave_sample.csv``) is WP10.4's."""
    assert sorted(p.name for p in LAB_DIR.iterdir()) == sorted([*(f"{n}.txt" for n in SEQUENCES), "idvg_real.csv"])


@pytest.mark.parametrize("name", SEQUENCES)
def test_transcript_parses_and_every_command_is_a_manual_mnemonic(name: str) -> None:
    sequence = load_sequence(name)
    assert sequence.source.startswith("lwp/matlab_B1500/") and sequence.configuration
    assert any("code-derived command list" in note for note in sequence.notes)
    known = manual_mnemonics()
    for step in sequence.steps:
        assert step.file.endswith(".m") and step.line_numbers(), step
        if step.command == READ:
            continue
        parsed = simflex.parse_command(step.command)
        assert parsed.mnemonic == step.mnemonic and parsed.mnemonic in known, step
        assert step.command == step.command.strip() and ";" not in step.command  # one command per line


def test_the_transcripts_hold_the_lab_pitfalls_the_kernel_designs_out() -> None:
    """Blueprint v2 1.1 pitfalls, as the lab code shows them: ``*RST`` before every setup, ``ERSSP`` without
    ``ERMOD 1``, ``ERRX?`` checked for ``+0,`` only, no ``CL`` after the SPGU, the 100 mA drain compliance."""
    idvg, ivt, spgu = (load_sequence(n) for n in SEQUENCES)
    for sequence in (idvg, ivt):
        assert "*RST" in [s.mnemonic for s in sequence.steps]
        errx = next(s for s in sequence.steps if s.mnemonic == "ERRX?")
        assert "'+0,'" in errx.remark
    mnemonics = [s.mnemonic for s in idvg.steps]
    assert mnemonics.index("ERSSP") < mnemonics.index("*RST") and "ERMOD" not in mnemonics
    assert "DV 4,0,0.1,0.1" in idvg.writes()  # drain at 0.1 V with 100 mA compliance
    assert [s.mnemonic for s in spgu.steps][-1] == "SPP" and "CL" not in [s.mnemonic for s in spgu.steps]
    assert any("no CL follows" in note for note in spgu.notes)


def test_the_real_curve_is_one_anonymized_61_point_id_vg() -> None:
    header = real_idvg_header()
    assert header[-1] == "InstrumentID: B1500A,A.06.02.2023.0401"  # IDN model + firmware only
    text = REAL_IDVG.read_text(encoding="utf-8")
    assert "Agilent" not in text and "Keysight" not in text and not re.search(r"20\d\d-\d\d-\d\d|\d{8}_\d{6}", text)
    table = real_idvg()
    assert list(table.columns) == ["V_G", "I_D", "I_G", "V_D", "V_S"] and len(table) == 61
    assert table["V_G"].iloc[0] == -2 and table["V_G"].iloc[-1] == 2
    assert set(table["V_D"]) == {0.1} and set(table["V_S"]) == {0}
    assert table["I_D"].iloc[-1] == pytest.approx(4.1855e-7)  # on current at Vg 2 V
    assert table["I_D"][table["V_G"] <= -0.9].abs().max() < 2.5e-12  # off state at the pA floor


# -- provenance against the lab code (developer Mac only) -------------------------------------------------------------

LWP = lwp_dir()
needs_lwp = pytest.mark.skipif(not LWP.is_dir(), reason=f"lab code not present at {LWP}")


def cited_text(sequence: LabSequence, step: LabStep) -> str:
    """The lines of the lwp file ``step`` cites (file names are relative to ``lwp/matlab_B1500``)."""
    lines = (LWP / step.file).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[n - 1] for n in step.line_numbers())


@needs_lwp
@pytest.mark.parametrize("name", SEQUENCES)
def test_every_cited_line_sends_that_command(name: str) -> None:
    sequence = load_sequence(name)
    for step in sequence.steps:
        text = cited_text(sequence, step)
        assert not text.lstrip().startswith("%"), (step, text)  # never a commented-out line
        if step.command == READ:
            assert "fgetl" in text, (step, text)
        elif step.is_query:
            assert "query(" in text and step.mnemonic in text, (step, text)
        else:
            assert "fprintf(" in text and step.mnemonic in text, (step, text)


@needs_lwp
def test_the_curve_rows_are_those_of_one_lab_file() -> None:
    rows = REAL_IDVG.read_text(encoding="utf-8").splitlines()
    data = [line for line in rows if not line.startswith("%")]
    matches = []
    for path in sorted(LWP.glob("IdVg_test_*.csv")):
        lab = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("%")]
        if lab == data:
            matches.append(path.name)
    assert len(matches) == 1
