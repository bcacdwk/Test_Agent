"""Configuration loading, per-file resolution, digests and rule R-CFG-01 (blueprint 4.1, 4.2, 2.9).

Every config item resolves on its own, first match wins:

1. ``$B1500_CONFIG_DIR/<file>.yaml`` (tests and the M3 runner only; source ``override``)
2. ``config/local/<file>.yaml`` (human-owned live config, gitignored; source ``local``)
3. ``config/<file>.example.yaml`` (committed examples; source ``example``). Simulator scenarios and fault profiles
   are committed as ``config/sim/{scenarios,faults}/<name>.yaml`` (no ``.example`` suffix).

Items: ``settings``, ``station``, ``policy`` (required), ``pinmaps/<name>``, ``duts/<name>``, and for the simulator
``sim/scenarios/<settings.sim.scenario>`` plus its ``sim/faults/<name>``. Each used file is recorded with its path
and the sha256 of its raw bytes (for plan hashes and run manifests).

R-CFG-01 (any violation → ``invalid_config``, reported as structured ``ConfigProblem``s, never a traceback):
files parse and validate; an example file can never select ``backend: visa``; ``visa`` requires
``config/local/{settings,station,policy}.yaml`` (no example, no ``$B1500_CONFIG_DIR`` file, and
``$B1500_CONFIG_DIR`` must be unset) and sees only ``config/local/`` pin maps and DUT profiles; ``policy.hard_limits``
above the code ceiling (42 V / 0.1 A) does not validate; the station's switches must be wired to channels of
fitting module types (schema), and every pin-map switch target (``SEL1.OUT1``) must name a declared switch and one
of its outputs (blueprint v2 2.3). Channel and MFCMU-side targets without a fitting module stay warnings: the
plan-phase rule R-PIN-01 blocks the plans that use them.

``ConfigLoader.get()`` re-reads the raw bytes on every call (cheap: a few small files) and re-parses only when a
digest or the set of files changed (the "digest cache" of blueprint 2.9).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.models.common import (
    Backend,
    ConfigFile,
    ConfigProblem,
    ConfigReport,
    ConfigSource,
    StrictModel,
)
from b1500_test_agent.models.policy import DutProfile, Policy
from b1500_test_agent.models.sim import SimFaultProfile
from b1500_test_agent.models.station import (
    PinMap,
    Settings,
    SimScenario,
    StationProfile,
    cmu_side,
    switch_target,
)
from b1500_test_agent.paths import ENV_CONFIG_DIR, Paths

CORE_ITEMS: tuple[str, ...] = ("settings", "station", "policy")
"""Required config items; with ``backend: visa`` each must come from ``config/local/``."""

COLLECTIONS: tuple[str, ...] = ("pinmaps", "duts", "sim/scenarios", "sim/faults")
"""Directories of named config files (file name without suffix = name)."""

_SIM_COLLECTIONS = frozenset({"sim/scenarios", "sim/faults"})
_EXAMPLE_SUFFIX = ".example.yaml"
_LOCAL_SUFFIX = ".yaml"

ModelT = TypeVar("ModelT", bound=BaseModel)


# -- YAML ------------------------------------------------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys (a repeated limit must never silently win)."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in seen
            seen.add(key)
        except TypeError:  # unhashable key: construct_mapping reports it
            continue
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, f"found duplicate key {key!r}", key_node.start_mark
            )
    return loader.construct_mapping(node, deep=True)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def load_yaml(raw: bytes) -> Any:
    """Parse UTF-8 (optionally BOM-prefixed) YAML with the safe loader, rejecting duplicate keys."""
    return yaml.load(raw.decode("utf-8-sig"), Loader=_UniqueKeyLoader)  # a SafeLoader subclass


# -- Discovery -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Found:
    """One config file found on disk (before parsing)."""

    key: str
    name: str
    path: Path
    source: ConfigSource
    raw: bytes
    sha256: str


def _layers(paths: Paths) -> list[tuple[ConfigSource, Path]]:
    layers: list[tuple[ConfigSource, Path]] = []
    if paths.override_config_dir is not None:
        layers.append(("override", paths.override_config_dir))
    layers.append(("local", paths.local_config_dir))
    layers.append(("example", paths.config_dir))
    return layers


def _suffix(source: ConfigSource, collection: str | None) -> str:
    if source == "example" and collection not in _SIM_COLLECTIONS:
        return _EXAMPLE_SUFFIX
    return _LOCAL_SUFFIX


def _read(key: str, name: str, path: Path, source: ConfigSource) -> _Found:
    raw = path.read_bytes()
    return _Found(key, name, path, source, raw, hashlib.sha256(raw).hexdigest())


def _scan(paths: Paths) -> list[_Found]:
    """Every candidate config file in every layer, in resolution order (override, local, example)."""
    found: list[_Found] = []
    for source, base in _layers(paths):
        if not base.is_dir():
            continue
        for item in CORE_ITEMS:
            path = base / f"{item}{_suffix(source, None)}"
            if path.is_file():
                found.append(_read(item, item, path, source))
        for collection in COLLECTIONS:
            directory = base.joinpath(*collection.split("/"))
            if not directory.is_dir():
                continue
            suffix = _suffix(source, collection)
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.name.endswith(suffix):
                    name = path.name[: -len(suffix)]
                    found.append(_read(f"{collection}/{name}", name, path, source))
    return found


def _resolve(found: list[_Found]) -> dict[str, _Found]:
    """First match per key (``found`` is in layer order)."""
    resolved: dict[str, _Found] = {}
    for item in found:
        resolved.setdefault(item.key, item)
    return resolved


def _tried(paths: Paths, key: str, collection: str | None) -> str:
    rel = key.split("/")
    tried = []
    for source, base in _layers(paths):
        path = base.joinpath(*rel[:-1], rel[-1] + _suffix(source, collection))
        tried.append(paths.display(path))
    return ", ".join(tried)


def _fingerprint(paths: Paths, found: list[_Found]) -> str:
    lines = [f"layers\t{[(s, b.as_posix()) for s, b in _layers(paths)]}"]
    lines += [f"{f.source}\t{f.key}\t{f.path.as_posix()}\t{f.sha256}" for f in found]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# -- Bundle ----------------------------------------------------------------------------------------------------------


class ConfigBundle(StrictModel):
    """A validated configuration: the parsed items, the files used (path + sha256) and the effective paths.

    ``files`` is keyed by config item (``settings``, ``pinmaps/mosfet-4t`` ...). ``digest`` covers every used file,
    so any edit gives a new digest.
    """

    paths: Paths
    settings: Settings
    station: StationProfile
    policy: Policy
    pin_maps: dict[str, PinMap]
    dut_profiles: dict[str, DutProfile]
    sim_scenario: SimScenario | None
    sim_faults: SimFaultProfile | None = None
    files: dict[str, ConfigFile]
    backend_reason: str
    warnings: list[str]
    digest: str

    @property
    def backend(self) -> Backend:
        """The backend selected by the settings (already checked against R-CFG-01)."""
        return self.settings.backend

    def sha256(self, key: str) -> str:
        """Digest of the file used for config item ``key``; raises ``KeyError`` for an unknown item."""
        return self.files[key].sha256

    def report(self) -> ConfigReport:
        """The ``ok`` config report of this bundle."""
        return ConfigReport(
            ok=True,
            backend=self.backend,
            backend_reason=self.backend_reason,
            files=list(self.files.values()),
            warnings=list(self.warnings),
            paths=self.paths.report(),
            digest=self.digest,
        )


@dataclass
class _Build:
    """Outcome of one load: the bundle (``None`` when invalid) and the report (always)."""

    bundle: ConfigBundle | None
    report: ConfigReport


class _Builder:
    """Parses and checks one scan of the config files (rule R-CFG-01)."""

    def __init__(self, paths: Paths, found: list[_Found]) -> None:
        self.paths = paths
        self.resolved = _resolve(found)
        self.problems: list[ConfigProblem] = []
        self.warnings: list[str] = []
        self.used: dict[str, _Found] = {}
        self.sim_faults: SimFaultProfile | None = None

    def problem(self, file: str | None, message: str, location: str | None = None) -> None:
        self.problems.append(ConfigProblem(file=file, location=location, message=message))

    def parse(self, found: _Found, model: type[ModelT], *, named: bool = False) -> ModelT | None:
        self.used[found.key] = found
        where = self.paths.display(found.path)
        if found.source != "example" and found.path.name.endswith(_EXAMPLE_SUFFIX):
            self.problem(where, f"Rename it to {found.path.name[: -len(_EXAMPLE_SUFFIX)]}.yaml: the .example suffix "
                         "is only for committed examples.")
            return None
        try:
            data = load_yaml(found.raw)
        except (yaml.YAMLError, UnicodeDecodeError) as exc:
            self.problem(where, f"Not valid UTF-8 YAML: {exc}")
            return None
        if not isinstance(data, dict):
            self.problem(where, "The top level must be a mapping.")
            return None
        if named:
            if "name" in data and data["name"] != found.name:
                self.problem(where, f"name {data['name']!r} differs from the file name {found.name!r}.", "name")
                return None
            data = {**data, "name": found.name}
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            for err in exc.errors(include_url=False, include_input=False):
                location = ".".join(str(part) for part in err["loc"]) or None
                self.problem(where, err["msg"], location)
            return None

    def core(self, item: str, model: type[ModelT]) -> ModelT | None:
        found = self.resolved.get(item)
        if found is None:
            self.problem(item, f"No {item} file found; looked for {_tried(self.paths, item, None)}.")
            return None
        return self.parse(found, model)

    def backend_check(self, settings: Settings) -> str:
        found = self.resolved["settings"]
        where = self.paths.display(found.path)
        if settings.backend == "sim":
            if found.source == "example":
                return (f"sim: {where} is the committed example (no config/local/settings.yaml); "
                        "examples always run the simulator")
            if found.source == "override":
                return f"sim: selected by {where} (${ENV_CONFIG_DIR}, tests and M3 only)"
            return f"sim: selected by {where}"
        if found.source == "example":
            self.problem(where, "An example file can never select backend visa; copy it to "
                         "config/local/settings.yaml and edit it there.", "backend")
        if self.paths.override_config_dir is not None:
            self.problem(None, f"${ENV_CONFIG_DIR} is set: it is for tests and the M3 runner (simulator) only; "
                         "unset it to use backend visa.")
        for item in CORE_ITEMS:
            used = self.resolved.get(item)
            if used is None or used.source == "local" or used is found and found.source == "example":
                continue
            self.problem(self.paths.display(used.path),
                         f"Backend visa requires config/local/{item}.yaml (resolved to the {used.source} file).")
        return f"visa: selected by {where}; settings, station and policy must all be config/local files"

    def collection(self, prefix: str, model: type[ModelT], backend: Backend | None) -> dict[str, ModelT]:
        items: dict[str, ModelT] = {}
        skipped = 0
        for key, found in sorted(self.resolved.items()):
            if not key.startswith(f"{prefix}/"):
                continue
            if backend == "visa" and found.source != "local":
                skipped += 1
                continue
            parsed = self.parse(found, model, named=True)
            if parsed is not None:
                items[found.name] = parsed
        if skipped:
            self.warnings.append(f"{skipped} {prefix} file(s) outside config/local/ ignored: backend visa uses "
                                 "config/local/ only.")
        return items

    def scenario(self, settings: Settings) -> SimScenario | None:
        key = f"sim/scenarios/{settings.sim.scenario}"
        found = self.resolved.get(key)
        if found is None:
            self.problem("settings", f"Sim scenario {settings.sim.scenario!r} not found; looked for "
                         f"{_tried(self.paths, key, 'sim/scenarios')}.", "sim.scenario")
            return None
        scenario = self.parse(found, SimScenario, named=True)
        if scenario is not None and scenario.faults is not None:
            fault_key = f"sim/faults/{scenario.faults}"
            fault = self.resolved.get(fault_key)
            if fault is None:
                self.problem(self.paths.display(found.path), f"Fault profile {scenario.faults!r} not found; looked "
                             f"for {_tried(self.paths, fault_key, 'sim/faults')}.", "faults")
            else:
                self.sim_faults = self.parse(fault, SimFaultProfile, named=True)
        return scenario

    def cross_checks(self, station: StationProfile, pin_maps: Mapping[str, PinMap],
                     scenario: SimScenario | None) -> None:
        """Pin-map switch targets must resolve in the station (problem); the rest are non-blocking hints, the
        plan-phase rules (R-PIN-01, R-INV-01, R-ROUTE-01) make the binding decisions."""
        for name, pin_map in pin_maps.items():
            where = self.paths.display(self.resolved[f"pinmaps/{name}"].path)
            for terminal, target in pin_map.terminals.items():
                problem = station.target_problem(target)
                ref = switch_target(target)
                side = cmu_side(target)
                if problem is not None:
                    self.problem(where, f"{terminal} -> {target}: {problem}.", f"terminals.{terminal}")
                elif ref is not None:
                    switch = station.switch(ref[0])
                    if switch is not None and switch.present is False:
                        self.warnings.append(f"pin map {name}: {terminal} -> {target} goes through switch "
                                             f"{switch.id}, which the station declares absent.")
                elif target == "GNDU" and not station.mainframe.gndu:
                    self.warnings.append(f"pin map {name}: {terminal} uses the GNDU, which the station lacks.")
                elif side is not None:
                    module = station.module_for_channel(side[0])
                    if module is None or module.type != "MFCMU":
                        found = "no module" if module is None else f"a {module.type}"
                        self.warnings.append(f"pin map {name}: {terminal} -> {target} needs an MFCMU in slot "
                                             f"{side[0]}; the station profile has {found} there.")
                elif isinstance(target, int) and station.module_for_channel(target) is None:
                    self.warnings.append(f"pin map {name}: {terminal} -> channel {target} has no module in the "
                                         "station profile.")
        if scenario is not None:
            simulated = {(s.slot, s.model) for s in scenario.slots}
            profile = {(m.slot, m.model) for m in station.modules}
            if simulated != profile:
                self.warnings.append(f"sim scenario {scenario.name}: simulated modules differ from the station "
                                     "profile (rule R-INV-01 will block affected plans).")

    def build(self) -> _Build:
        settings = self.core("settings", Settings)
        station = self.core("station", StationProfile)
        policy = self.core("policy", Policy)
        backend: Backend | None = None
        reason = ""
        paths = self.paths
        if settings is not None:
            backend = settings.backend
            reason = self.backend_check(settings)
            paths = self.paths.with_settings(settings.paths)
        pin_maps = self.collection("pinmaps", PinMap, backend)
        dut_profiles = self.collection("duts", DutProfile, backend)
        scenario = self.scenario(settings) if settings is not None and backend == "sim" else None
        if station is not None:
            self.cross_checks(station, pin_maps, scenario)
        files = {
            key: ConfigFile(key=key, path=paths.display(f.path), source=f.source, sha256=f.sha256)
            for key, f in self.used.items()
        }
        digest = hashlib.sha256(
            "\n".join(f"{k}\t{f.source}\t{f.sha256}" for k, f in sorted(files.items())).encode("utf-8")
        ).hexdigest()
        if self.problems or settings is None or station is None or policy is None:
            report = ConfigReport(
                ok=False,
                error_code="invalid_config",
                backend=backend,
                backend_reason=reason,
                files=list(files.values()),
                problems=self.problems,
                warnings=self.warnings,
                paths=paths.report(),
            )
            return _Build(None, report)
        bundle = ConfigBundle(
            paths=paths,
            settings=settings,
            station=station,
            policy=policy,
            pin_maps=pin_maps,
            dut_profiles=dut_profiles,
            sim_scenario=scenario,
            sim_faults=self.sim_faults,
            files=files,
            backend_reason=reason,
            warnings=self.warnings,
            digest=digest,
        )
        return _Build(bundle, bundle.report())


# -- Loader ----------------------------------------------------------------------------------------------------------


class ConfigLoader:
    """Digest-cached configuration loader; one per process (service, CLI).

    ``paths`` defaults to ``Paths.from_env(environ)``, evaluated on every call so a bad ``$B1500_HOME`` is reported
    as ``invalid_config`` rather than raised at construction.
    """

    def __init__(self, paths: Paths | None = None, *, environ: Mapping[str, str] | None = None) -> None:
        self._paths = paths
        self._environ = environ
        self._fingerprint: str | None = None
        self._last: _Build | None = None

    def _load(self) -> _Build:
        try:
            paths = self._paths if self._paths is not None else Paths.from_env(self._environ)
        except InvalidConfigError as exc:
            self._fingerprint, self._last = None, None
            return _Build(None, ConfigReport(ok=False, error_code="invalid_config", problems=list(exc.problems)))
        try:
            found = _scan(paths)
        except OSError as exc:
            self._fingerprint, self._last = None, None
            problem = ConfigProblem(file=getattr(exc, "filename", None), message=f"Cannot read config: {exc}")
            return _Build(None, ConfigReport(ok=False, error_code="invalid_config", problems=[problem]))
        fingerprint = _fingerprint(paths, found)
        if self._last is None or fingerprint != self._fingerprint:
            self._last = _Builder(paths, found).build()
            self._fingerprint = fingerprint
        return self._last

    def get(self) -> ConfigBundle:
        """The current valid bundle; raises ``InvalidConfigError`` (code ``invalid_config``) otherwise."""
        build = self._load()
        if build.bundle is None:
            raise InvalidConfigError(build.report.problems)
        return build.bundle

    def check(self) -> ConfigReport:
        """The current config report; never raises."""
        return self._load().report


def load_config(paths: Paths | None = None) -> ConfigBundle:
    """Load and validate the configuration once; raises ``InvalidConfigError``."""
    return ConfigLoader(paths).get()


def check_config(paths: Paths | None = None) -> ConfigReport:
    """Check the configuration once; never raises."""
    return ConfigLoader(paths).check()
