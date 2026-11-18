"""Manual catalog, synonyms, manuals folder and PDF location (blueprint 5.2, WP5.8)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from b1500_test_agent.manuals.catalog import (
    ENV_MANUALS_DIR,
    ManualError,
    ManualPaths,
    build_digest,
    load_catalog,
    load_synonyms,
    locate_pdfs,
    resolve_manuals_dir,
)
from b1500_test_agent.models.manuals import ManualCatalog
from b1500_test_agent.models.station import Settings
from tests.fixtures.manuals.make_fixture import FIXTURE_DIR, PDF_NAME, fixture_pdf

pytestmark = pytest.mark.manuals

REPO = Path(__file__).resolve().parents[2]
REFERENCES = REPO / "references" / "manuals"
IDS = ["PG", "EX", "UG", "WG", "WG5", "CC", "AC", "SEL", "DS", "AN-REL", "AN-CHAR", "AN-TUT", "AN-NVM", "AN-RTN",
       "AN-CV", "AN-FIV"]


def test_committed_catalog_lists_the_sixteen_manuals() -> None:
    catalog = load_catalog(REFERENCES / "catalog.yaml")
    assert catalog.ids == IDS
    assert catalog.total_pages == 2315
    wg, wg5 = catalog.get("WG"), catalog.get("WG5")
    assert wg is not None and wg5 is not None
    assert wg.file == "lwp/matlab_B1500/9018-01706.pdf" and wg.edition.startswith("Edition 8") and wg.pages == 160
    assert wg5.edition.startswith("Edition 5") and wg5.pages == 164
    assert {d.id: d.pages for d in catalog.docs if d.id in ("PG", "EX", "UG", "CC", "AC", "SEL", "DS")} == {
        "PG": 617, "EX": 700, "UG": 160, "CC": 122, "AC": 24, "SEL": 32, "DS": 17}
    boosted = {d.id for d in catalog.docs if d.priority > 1.0}
    assert boosted == {"PG", "WG", "SEL", "CC"} and wg5.priority < 1.0
    assert {d.language for d in catalog.docs if d.id.startswith("AN-") and d.id != "AN-NVM"} == {"zh"}
    for symbol in ("µ", "Ω", "±", "≤", "≥", "×", "°"):
        assert symbol in catalog.symbols.values()
    for doc in catalog.docs:
        assert re.compile(doc.label_rule).groups >= 1
        assert unicodedata.is_normalized("NFC", doc.file)
        for rel in doc.extracts:
            assert (REFERENCES / rel).is_file(), f"{doc.id}: extract {rel} missing"


def test_committed_synonyms_parse() -> None:
    synonyms = load_synonyms(REFERENCES / "synonyms.yaml").synonyms
    assert {"selector", "duty", "开路"} <= set(synonyms)
    assert "ERSSP" in synonyms["selector"] and "open" in synonyms["开路"]


def _catalog(**changes: object) -> dict[str, object]:
    data = yaml.safe_load((FIXTURE_DIR / "catalog.yaml").read_text(encoding="utf-8"))
    data["docs"][0].update(changes)
    return data


@pytest.mark.parametrize(("change", "message"), [
    ({"label_rule": "Fixture Guide"}, "capture group"),
    ({"label_rule": "(unclosed"}, "not a valid regular expression"),
    ({"file": "/abs/fixture.pdf"}, "relative POSIX path"),
    ({"file": "../up/fixture.pdf"}, "relative POSIX path"),
    ({"file": "fixture.txt"}, "String should match pattern"),
    ({"id": "pg"}, "String should match pattern"),
    ({"extracts": ["C:/x.md"]}, "relative POSIX path"),
    ({"priority": 5}, "less than or equal"),
])
def test_catalog_rejects_bad_documents(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        ManualCatalog.model_validate(_catalog(**change))


def test_catalog_rejects_duplicates_and_bad_symbols() -> None:
    data = _catalog()
    data["docs"].append(dict(data["docs"][0]))  # type: ignore[attr-defined]
    with pytest.raises(ValidationError, match="duplicate document ids"):
        ManualCatalog.model_validate(data)
    data = _catalog()
    data["symbols"] = {"0057": "W"}
    with pytest.raises(ValidationError, match="private-use"):
        ManualCatalog.model_validate(data)


def test_load_errors_are_manual_errors(tmp_path: Path) -> None:
    with pytest.raises(ManualError, match="no manual catalog"):
        load_catalog(tmp_path / "catalog.yaml")
    (tmp_path / "catalog.yaml").write_text("docs: [", encoding="utf-8")
    with pytest.raises(ManualError, match="not readable UTF-8 YAML"):
        load_catalog(tmp_path / "catalog.yaml")
    (tmp_path / "catalog.yaml").write_text("docs: []\n", encoding="utf-8")
    with pytest.raises(ManualError, match="is invalid: docs"):
        load_catalog(tmp_path / "catalog.yaml")
    assert load_synonyms(tmp_path / "none.yaml").synonyms == {}
    (tmp_path / "syn.yaml").write_text("synonyms: {a: b}\n", encoding="utf-8")
    with pytest.raises(ManualError, match="synonyms"):
        load_synonyms(tmp_path / "syn.yaml")


def test_build_digest_tracks_what_changes_the_corpus() -> None:
    base = ManualCatalog.model_validate(_catalog())
    assert build_digest(base) == build_digest(ManualCatalog.model_validate(_catalog(title="Renamed", priority=2)))
    assert build_digest(base) != build_digest(ManualCatalog.model_validate(_catalog(label_rule=r"^(\d+)$")))
    assert build_digest(base) != build_digest(ManualCatalog.model_validate(_catalog(pages=3)))
    data = _catalog()
    data["symbols"] = {"F057": "Ohm"}
    assert build_digest(base) != build_digest(ManualCatalog.model_validate(data))


def test_settings_manuals_dir_defaults_to_the_clone_parent() -> None:
    assert Settings().manuals_dir == ".."
    assert Settings.model_validate({"manuals_dir": "D:/manuals"}).manuals_dir == "D:/manuals"
    with pytest.raises(ValidationError):
        Settings.model_validate({"manuals_dir": ""})


def test_resolve_manuals_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "clone"
    repo.mkdir()
    assert resolve_manuals_dir("..", repo, {}) == (tmp_path.resolve(), "settings.manuals_dir")
    assert resolve_manuals_dir("pdfs", repo, {}) == ((repo / "pdfs").resolve(), "settings.manuals_dir")
    absolute = tmp_path / "elsewhere"
    assert resolve_manuals_dir("..", repo, {ENV_MANUALS_DIR: str(absolute)}) == (absolute.resolve(),
                                                                                  ENV_MANUALS_DIR)
    monkeypatch.chdir(repo)
    assert resolve_manuals_dir("..", repo, {ENV_MANUALS_DIR: "rel"})[0] == (repo / "rel").resolve()
    assert resolve_manuals_dir("..", repo, {ENV_MANUALS_DIR: ""})[1] == "settings.manuals_dir"
    paths = ManualPaths.for_repo(repo, "..", {})
    assert paths.catalog == repo / "references" / "manuals" / "catalog.yaml"
    assert paths.pages == repo / "references" / "manuals" / "corpus" / "pages.jsonl.gz"
    assert paths.display(repo / "references" / "manuals") == "references/manuals"
    assert paths.display_pdf(tmp_path / "Demo" / "a.pdf") == "Demo/a.pdf"


def test_locate_pdfs_by_path_by_sha_and_reports_mismatch_and_missing(tmp_path: Path) -> None:
    catalog = load_catalog(FIXTURE_DIR / "catalog.yaml")
    folder = tmp_path / "manuals"
    folder.mkdir()
    assert locate_pdfs(catalog, folder)["FX"].state == "missing"
    assert locate_pdfs(catalog, tmp_path / "nowhere")["FX"].state == "missing"
    (folder / PDF_NAME).write_bytes(fixture_pdf())
    (folder / "extra.pdf").write_bytes(b"%PDF extra")  # extra files never matter
    found = locate_pdfs(catalog, folder)["FX"]
    assert (found.state, found.how, found.path) == ("ok", "catalog path", folder / PDF_NAME)
    (folder / PDF_NAME).write_bytes(fixture_pdf() + b"\n")
    assert locate_pdfs(catalog, folder)["FX"].state == "mismatch"
    hidden = folder / ".hidden"
    hidden.mkdir()
    (hidden / "copy.pdf").write_bytes(fixture_pdf())
    assert locate_pdfs(catalog, folder)["FX"].state == "mismatch"  # hidden folders are not walked
    sub = folder / "sub"
    sub.mkdir()
    (sub / "copy.pdf").write_bytes(fixture_pdf())
    moved = locate_pdfs(catalog, folder)["FX"]
    assert (moved.state, moved.how, moved.path) == ("ok", "found by size and sha256", sub / "copy.pdf")
    assert locate_pdfs(catalog, folder, skip=sub)["FX"].state == "mismatch"  # the clone itself is skipped


def test_locate_tries_the_other_unicode_normalisation(tmp_path: Path) -> None:
    data = _catalog(file="Demo/表征 1μs é.pdf")
    catalog = ManualCatalog.model_validate(data)
    (tmp_path / "Demo").mkdir()
    (tmp_path / "Demo" / unicodedata.normalize("NFD", "表征 1μs é.pdf")).write_bytes(fixture_pdf())
    assert locate_pdfs(catalog, tmp_path)["FX"].state == "ok"
