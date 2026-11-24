"""``file`` recipe parameters: CSV files the planner reads and hashes into the plan (blueprint v2 2.3, decision 21).

A ``file`` parameter value is ``recipes/waveforms/<name>.csv`` (the committed waveform library next to the recipes)
or ``work/waveforms/<name>.csv`` (the agent's ad-hoc folder under the configured ``paths.work_dir``). The planner
resolves it once at validation (``resolve_param_files``): the path must stay inside its folder after resolving
symbolic links, the file must exist and hold at most ``FILE_PARAM_MAX_BYTES``; its sha256 goes into
``PlanRecord.files`` and therefore into the plan hash. Before every run the executor checks the digest again
(``changed_param_files``), and a kind reads the bytes only through ``read_param_file``, which re-verifies them, so
a run never executes a file other than the one the human validated. A ``work/`` file is always confirmed
(``adhoc_recipe``, R-ALWAYS-01).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import Quantity
from b1500_test_agent.models.plan import ParamFile
from b1500_test_agent.models.recipe import FILE_PARAM_DIRS, FILE_PARAM_MAX_BYTES, Recipe, file_param_origin

LIBRARY_PREFIX = "recipes/waveforms/"
WORK_PREFIX = "work/waveforms/"
WAVEFORMS = "waveforms"


class ParamFileChanged(InvalidInputError):
    """A ``file`` parameter's CSV changed (or vanished) since the plan was validated."""


@dataclass(frozen=True)
class FileRoots:
    """Where the two ``file`` parameter folders live: ``<recipes dir>/waveforms`` and ``<work_dir>/waveforms``."""

    library: Path
    work: Path

    @classmethod
    def of(cls, recipes_dir: Path, work_dir: Path) -> FileRoots:
        return cls(library=Path(recipes_dir) / WAVEFORMS, work=Path(work_dir) / WAVEFORMS)

    def locate(self, value: str) -> Path:
        """The file a well-formed parameter value names (not yet checked for existence or containment)."""
        origin = file_param_origin(value)
        if origin is None:
            raise ValueError(f"{value!r} is not a {' or '.join(f'{p}<name>.csv' for p in FILE_PARAM_DIRS)} path")
        base, prefix = (self.library, LIBRARY_PREFIX) if origin == "library" else (self.work, WORK_PREFIX)
        return base.joinpath(*value[len(prefix):].split("/"))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_param_file(value: str, roots: FileRoots) -> ParamFile:
    """The ``ParamFile`` of one parameter value: sha256 and size, or the ``problem`` that makes it unusable."""
    origin = file_param_origin(value)
    if origin is None:
        raise ValueError(f"{value!r} is not a file parameter path")
    base = roots.library if origin == "library" else roots.work
    path = roots.locate(value)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return ParamFile(path=value, origin=origin, problem=f"{value} does not exist")
    try:
        inside = resolved.is_relative_to(base.resolve())
    except OSError:
        inside = False
    if not inside:
        return ParamFile(path=value, origin=origin, problem=f"{value} resolves outside {base.name}/ (link)")
    if not resolved.is_file():
        return ParamFile(path=value, origin=origin, problem=f"{value} is not a file")
    try:
        size = resolved.stat().st_size
        if size > FILE_PARAM_MAX_BYTES:
            return ParamFile(path=value, origin=origin,
                             problem=f"{value} has {size} bytes, more than {FILE_PARAM_MAX_BYTES}")
        data = resolved.read_bytes()
    except OSError as exc:
        return ParamFile(path=value, origin=origin, problem=f"{value} cannot be read: {exc.strerror or exc}")
    if len(data) > FILE_PARAM_MAX_BYTES:  # grew between stat and read
        return ParamFile(path=value, origin=origin,
                         problem=f"{value} has {len(data)} bytes, more than {FILE_PARAM_MAX_BYTES}")
    return ParamFile(path=value, origin=origin, sha256=_digest(data), size_bytes=len(data))


def resolve_param_files(recipe: Recipe, params: Mapping[str, Quantity], roots: FileRoots) -> dict[str, ParamFile]:
    """``ParamFile`` per well-formed ``file`` parameter of ``recipe`` (malformed values are left to R-PARAM-01)."""
    files: dict[str, ParamFile] = {}
    for name, spec in recipe.params.items():
        quantity = params.get(name)
        if spec.type != "file" or quantity is None or file_param_origin(quantity.value) is None:
            continue
        files[name] = resolve_param_file(str(quantity.value), roots)
    return files


def changed_param_files(files: Mapping[str, ParamFile], roots: FileRoots) -> list[str]:
    """Names of the plan's ``file`` parameters whose CSV no longer has the validated digest (or vanished)."""
    changed = []
    for name, record in sorted(files.items()):
        current = resolve_param_file(record.path, roots)
        if (current.sha256, current.problem) != (record.sha256, record.problem):
            changed.append(name)
    return changed


def read_param_file(record: ParamFile, roots: FileRoots) -> bytes:
    """The validated bytes of a plan's ``file`` parameter; raises ``ParamFileChanged`` when the file is unusable or
    its sha256 differs from the plan's."""
    if record.problem is not None or record.sha256 is None:
        raise ParamFileChanged(f"file parameter {record.path} was not usable at validation: {record.problem}")
    current = resolve_param_file(record.path, roots)
    if current.problem is not None or current.sha256 != record.sha256:
        raise ParamFileChanged(f"{record.path} changed since the plan was validated; validate again")
    data = roots.locate(record.path).resolve(strict=True).read_bytes()
    if _digest(data) != record.sha256:
        raise ParamFileChanged(f"{record.path} changed while being read; validate again")
    return data


@dataclass(frozen=True)
class ParamFiles:
    """The plan's ``file`` parameters and where they live, handed by the planner to a kind that builds its program
    from CSV content (``reads_files = True``, e.g. ``wgfmu_waveform`` builder ``table``): ``read(name)`` returns the
    validated bytes through ``read_param_file`` (sha256 re-verified), so the compiled program, and with it the plan
    hash, always matches the digest in ``PlanRecord.files``."""

    records: Mapping[str, ParamFile]
    roots: FileRoots

    def read(self, name: str) -> bytes:
        """The bytes of ``file`` parameter ``name``.

        Raises:
            ParamFileChanged: If the parameter has no usable file or its content changed since it was hashed.
        """
        record = self.records.get(name)
        if record is None:
            raise ParamFileChanged(f"no file parameter {name!r} was resolved for this plan")
        return read_param_file(record, self.roots)
