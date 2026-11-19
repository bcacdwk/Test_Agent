"""Repository-relative runtime paths (owner decision D1, blueprint 1, 2.7, 4.1).

Everything lives in the clone: ``config/local/`` (human-owned live config), ``data/runs/`` (run archive),
``data/state/`` (plans, locks, fault latch, simulator state) and ``work/`` (agent scratch). The repository root is
``$B1500_HOME`` or, by default, derived from the package location (``src/b1500_test_agent/`` → two levels up, as
installed by ``uv sync`` in editable mode).

Environment overrides, **for tests and the M3 acceptance runner only** (never needed on the lab PC):

- ``B1500_CONFIG_DIR``: a directory searched before ``config/local/`` for every config file (same layout).
- ``B1500_DATA_DIR``: replaces ``data_root``, so ``runs/`` and ``state/`` move with it.

Windows-safe: ``pathlib`` only; nothing here touches the file system except existence checks.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import computed_field

from b1500_test_agent.errors import InvalidConfigError
from b1500_test_agent.models.common import ConfigProblem, StrictModel
from b1500_test_agent.models.station import PathSettings

ENV_HOME = "B1500_HOME"
ENV_CONFIG_DIR = "B1500_CONFIG_DIR"
ENV_DATA_DIR = "B1500_DATA_DIR"

_PACKAGE_DIR = Path(__file__).resolve().parent


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _absolute(value: str | Path, base: Path) -> Path:
    """``value`` as an absolute path; relative values resolve against ``base``."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def find_repo_root(environ: Mapping[str, str] | None = None) -> Path:
    """The repository root: ``$B1500_HOME`` or two levels above the package directory.

    Raises ``InvalidConfigError`` when ``$B1500_HOME`` is not a directory or the package is not inside a clone
    (e.g. a non-editable install); set ``B1500_HOME`` then.
    """
    home = _env(environ).get(ENV_HOME)
    if home:
        root = _absolute(home, Path.cwd())
        if not root.is_dir():
            raise InvalidConfigError([ConfigProblem(message=f"{ENV_HOME}={home} is not a directory.")])
        return root
    root = _PACKAGE_DIR.parents[1]
    if not (root / "pyproject.toml").is_file():
        raise InvalidConfigError(
            [
                ConfigProblem(
                    message=f"Cannot locate the repository from the package location {_PACKAGE_DIR}; "
                    f"set {ENV_HOME} to the clone's root directory."
                )
            ]
        )
    return root


class Paths(StrictModel):
    """Effective runtime paths. Build with ``Paths.from_env()``; ``with_settings()`` applies ``settings.paths``."""

    repo_root: Path
    config_dir: Path
    local_config_dir: Path
    override_config_dir: Path | None = None
    data_root: Path
    work_dir: Path
    data_root_from_env: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state_dir(self) -> Path:
        """``<data_root>/state``: plans, locks, fault latch, in-flight marker, simulator state, audit."""
        return self.data_root / "state"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def runs_dir(self) -> Path:
        """``<data_root>/runs``: the run archive and ``index.jsonl``."""
        return self.data_root / "runs"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recipes_dir(self) -> Path:
        """``<repo>/recipes``: recipe registry source YAML."""
        return self.repo_root / "recipes"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, *, repo_root: Path | None = None) -> Paths:
        """Default paths for ``repo_root`` (or the located repository) with the environment overrides applied."""
        env = _env(environ)
        root = find_repo_root(env) if repo_root is None else _absolute(repo_root, Path.cwd())
        cwd = Path.cwd()
        override = env.get(ENV_CONFIG_DIR) or None
        data_dir = env.get(ENV_DATA_DIR) or None
        defaults = PathSettings()
        return cls(
            repo_root=root,
            config_dir=root / "config",
            local_config_dir=root / "config" / "local",
            override_config_dir=_absolute(override, cwd) if override else None,
            data_root=_absolute(data_dir, cwd) if data_dir else _absolute(defaults.data_root, root),
            work_dir=_absolute(defaults.work_dir, root),
            data_root_from_env=data_dir is not None,
        )

    def with_settings(self, settings: PathSettings) -> Paths:
        """Apply ``settings.paths`` (relative to the repository root); ``B1500_DATA_DIR`` still wins."""
        data_root = self.data_root if self.data_root_from_env else _absolute(settings.data_root, self.repo_root)
        work_dir = _absolute(settings.work_dir, self.repo_root)
        return self.model_copy(update={"data_root": data_root, "work_dir": work_dir})

    def display(self, path: Path) -> str:
        """``path`` relative to the repository root with POSIX separators when inside it, else absolute (resolved
        once: on Windows ``resolve`` opens the file to ask for its final name)."""
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.repo_root).as_posix()
        except ValueError:
            return resolved.as_posix()

    def report(self) -> dict[str, str]:
        """The effective directories for ``b1500 config check`` and ``station_status``."""
        report = {
            "repo_root": self.repo_root.as_posix(),
            "local_config_dir": self.display(self.local_config_dir),
            "data_root": self.display(self.data_root),
            "runs_dir": self.display(self.runs_dir),
            "state_dir": self.display(self.state_dir),
            "work_dir": self.display(self.work_dir),
        }
        if self.override_config_dir is not None:
            report["override_config_dir"] = f"{self.override_config_dir.as_posix()} (${ENV_CONFIG_DIR}; tests/M3 only)"
        if self.data_root_from_env:
            report["data_root"] += f" (${ENV_DATA_DIR}; tests/M3 only)"
        return report
