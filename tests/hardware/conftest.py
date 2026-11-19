"""Gate and fixtures of the hardware suite (blueprint v2 7.1 ``tests/hardware/``; ``support.py`` explains both).

- Every test marked ``hardware`` is skipped, with the gate's reason, unless ``B1500_HW=1`` and the settings select
  backend ``visa``; every ``hardware`` test carries exactly one stage marker (``hw_s0`` ... ``hw_l10``), otherwise
  the run stops with a usage error. The terminal summary says plainly when the suite checked nothing.
- Fixtures (session-wide, built only when a hardware test runs): the service of ``b1500 doctor --probe``
  (``hw_service``), its configuration (``hw_config``; a configuration that does not load fails the tests), one
  read-only probe (``probe_report``), the recipes, the run archive and the WP6.3 record schema.

Tests in this folder without the ``hardware`` marker (``test_suite.py``, ``test_readonly.py``,
``test_record_checks.py``) are ordinary simulator and visa-loop tests that run in CI.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from b1500_test_agent.catalog.registry import RecipeRegistry
from b1500_test_agent.config import ConfigBundle
from b1500_test_agent.models.bringup import ProbeReport
from b1500_test_agent.models.recipe import Recipe
from b1500_test_agent.service import B1500Admin, B1500Service
from tests.hardware import support
from tests.hardware.records import RecordSchema, RunArchive, load_schema

_GATE = pytest.StashKey[support.Gate]()
_SELECTED = pytest.StashKey[int]()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    problems = support.stage_marker_problems(items)
    if problems:
        raise pytest.UsageError("hardware suite:\n" + "\n".join(problems))
    hardware = [item for item in items if item.get_closest_marker(support.HARDWARE_MARKER) is not None]
    if not hardware:
        return
    gate = support.hardware_gate()
    config.stash[_GATE] = gate
    if not gate.enabled:
        skip = pytest.mark.skip(reason=gate.reason)
        for item in hardware:
            item.add_marker(skip)


def pytest_collection_finish(session: pytest.Session) -> None:
    session.config.stash[_SELECTED] = sum(
        1 for item in session.items if item.get_closest_marker(support.HARDWARE_MARKER) is not None)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, exitstatus: int,
                            config: pytest.Config) -> None:
    gate = config.stash.get(_GATE, None)
    selected = config.stash.get(_SELECTED, 0)
    if gate is None or not selected:
        return
    if config.option.collectonly:
        state = "run" if gate.enabled else "skip"
        terminalreporter.write_line(f"hardware suite: {selected} hardware test(s) collected; they {state}: "
                                    f"{gate.reason}")
    elif gate.enabled:
        terminalreporter.write_line(f"hardware suite: {selected} hardware test(s) selected ({gate.reason})")
    else:
        terminalreporter.write_line(f"HARDWARE SUITE NOT RUN: {selected} hardware test(s) skipped, nothing on the "
                                    f"station was checked. {gate.reason}", yellow=True, bold=True)


# -- fixtures (hardware tests only) ------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def hw_service() -> Iterator[B1500Service]:
    """The service of ``b1500 doctor --probe`` on this station (``support.make_service``)."""
    service = support.make_service()
    try:
        yield service
    finally:
        service.close()


@pytest.fixture(scope="session")
def hw_config(hw_service: B1500Service) -> ConfigBundle:
    """The station's configuration; the tests fail (not skip) when it does not load on backend visa."""
    report = hw_service.config.check()
    if not report.ok:
        listed = "; ".join(f"{p.file or 'config'}: {p.message}" for p in report.problems[:5])
        pytest.fail(f"{support.ENV_HW}=1 and backend visa, but the configuration does not load "
                    f"(uv run b1500 config check): {listed}", pytrace=False)
    bundle = hw_service.config.get()
    if bundle.backend != "visa":
        pytest.fail(f"the configuration selects backend {bundle.backend}, not visa", pytrace=False)
    return bundle


@pytest.fixture(scope="session")
def probe_report(hw_service: B1500Service, hw_config: ConfigBundle) -> ProbeReport:
    """One read-only probe of the station (``b1500 doctor --probe``; queries only, record in ``work/bringup/``)."""
    return B1500Admin(hw_service).probe()


@pytest.fixture(scope="session")
def record_schema() -> RecordSchema | None:
    return load_schema()


@pytest.fixture(scope="session")
def recipes(hw_config: ConfigBundle) -> dict[str, Recipe]:
    """The current recipes (``recipes/``), by id."""
    registry = RecipeRegistry.load(hw_config.paths.recipes_dir, repo_root=hw_config.paths.repo_root)
    return {recipe_id: registry.get(recipe_id) for recipe_id in registry.ids()}


@pytest.fixture(scope="session")
def run_archive(hw_config: ConfigBundle) -> RunArchive:
    """The station's run archive (``<data_root>/runs``), read only."""
    return RunArchive(hw_config.paths.data_root)
