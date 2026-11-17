"""Plots of ``plot_iv`` stored through the archive (WP2.2): ``RunFolder.add_plot`` never overwrites and refuses odd
names; ``analysis_payload`` records the stored paths of a ``PlotSet``."""

from __future__ import annotations

from pathlib import Path

import pytest

from b1500_test_agent.analysis.plots import PlotSet, RenderedPlot
from b1500_test_agent.archive.store import RunFolder, analysis_payload
from b1500_test_agent.errors import InvalidInputError

RUN_ID = "S20261117T063012Z-7f3a"


def test_add_plot_numbers_files_and_never_overwrites(tmp_path: Path) -> None:
    folder = RunFolder(tmp_path / "runs", RUN_ID)
    plots = PlotSet(plots=(RenderedPlot("iv-log", b"\x89PNG1"),), x="gate_V", y=("drain_I",), scale="log")
    assert folder.add_plots(plots) == ["plots/iv-log-1.png"]
    assert folder.add_plot("iv-log", b"\x89PNG2") == "plots/iv-log-2.png"
    assert (folder.path / "plots" / "iv-log-1.png").read_bytes() == b"\x89PNG1"
    for bad in ("", "../x", "a/b", "x.png"):
        with pytest.raises(InvalidInputError):
            folder.add_plot(bad, b"")


def test_analysis_payload_records_the_plots() -> None:
    plots = PlotSet(plots=(), x="a_V", y=("a_I",), scale="both", warnings=("1 point(s) not drawn",))
    payload = analysis_payload("plot_iv", {"scale": "both"}, plots, source="analyze_run", plots=["plots/iv-1.png"])
    assert payload["outcome"] == "ok" and payload["plots"] == ["plots/iv-1.png"]
    assert (payload["x"], payload["y"], payload["scale"], payload["warnings"]) == ("a_V", ["a_I"], "both",
                                                                                  ["1 point(s) not drawn"])
