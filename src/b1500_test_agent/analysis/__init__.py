"""Analysis of archived runs: datasets, quality, extraction methods and plots (blueprint 2.8).

Ad-hoc use from agent scripts in ``work/``::

    from b1500_test_agent.analysis import load_run, assess_quality, vth_linear_extrapolation, plot_iv, work_dir_for
    d = load_run("S20261117T063012Z-7f3a")
    report = assess_quality(d)
    vth = vth_linear_extrapolation(d)          # value=None with outcome "refused"/"failed" and an error message
    pngs = plot_iv(d, scale="log")             # PNGs under work/<run_id>/plots/
    out_dir = work_dir_for(d.run_id)           # never write into the run folder

Methods (registry ``ANALYSIS_METHODS``; definitions in the ``mosfet.py``, ``resistor.py``, ``diode.py``,
``leakage.py``, ``fefet.py`` and ``plots.py`` docstrings): ``quality_report``, ``vth_linear_extrapolation``,
``vth_constant_current``, ``vth_max_gm``, ``subthreshold_swing``, ``gm_max``, ``ion_ioff``, ``output_metrics``,
``resistance``, ``diode_fit``, ``leakage_at``, ``memory_window``, ``plot_iv``.

Errors: exceptions mean the call cannot be served (``RunNotFoundError``, ``RunFormatError``, ``InvalidInputError``,
``MethodNotImplementedError``); data that do not allow a trustworthy value give an ``ExtractionResult`` with
``outcome`` ``refused`` (untrusted data without ``force``) or ``failed``.
"""

from b1500_test_agent.analysis.dataset import (
    DATA_FILE,
    INDEX_FILE,
    MANIFEST_FILE,
    SEGMENT,
    SEGMENTS,
    STATUS_SUFFIX,
    STEP,
    TRUST,
    TRUST_LEVELS,
    RunData,
    column_unit,
    find_run,
    load_manifest,
    load_run,
    measured_columns,
    read_table,
    run_relpath,
    source_columns,
    status_column,
    trust_levels,
    validate_table,
    value_column,
    with_trust,
    work_dir_for,
    write_table,
)
from b1500_test_agent.analysis.diode import diode_fit
from b1500_test_agent.analysis.errors import MethodNotImplementedError, RunFormatError, RunNotFoundError
from b1500_test_agent.analysis.fefet import memory_window
from b1500_test_agent.analysis.leakage import leakage_at
from b1500_test_agent.analysis.mosfet import (
    gm,
    gm_max,
    ion_ioff,
    local_derivative,
    output_metrics,
    subthreshold_swing,
    vth_constant_current,
    vth_linear_extrapolation,
    vth_max_gm,
)
from b1500_test_agent.analysis.plots import PlotSet, plot_iv, render_iv
from b1500_test_agent.analysis.quality import MIN_SNR, assess_quality, noise_sigma, signal_to_noise
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS, AnalysisMethod, run_method
from b1500_test_agent.analysis.resistor import resistance

__all__ = [
    "ANALYSIS_METHODS",
    "DATA_FILE",
    "INDEX_FILE",
    "MANIFEST_FILE",
    "MIN_SNR",
    "SEGMENT",
    "SEGMENTS",
    "STATUS_SUFFIX",
    "STEP",
    "TRUST",
    "TRUST_LEVELS",
    "AnalysisMethod",
    "MethodNotImplementedError",
    "PlotSet",
    "RunData",
    "RunFormatError",
    "RunNotFoundError",
    "assess_quality",
    "column_unit",
    "diode_fit",
    "find_run",
    "gm",
    "gm_max",
    "ion_ioff",
    "leakage_at",
    "load_manifest",
    "load_run",
    "local_derivative",
    "measured_columns",
    "memory_window",
    "noise_sigma",
    "output_metrics",
    "plot_iv",
    "read_table",
    "render_iv",
    "resistance",
    "run_method",
    "run_relpath",
    "signal_to_noise",
    "source_columns",
    "status_column",
    "subthreshold_swing",
    "trust_levels",
    "validate_table",
    "value_column",
    "vth_constant_current",
    "vth_linear_extrapolation",
    "vth_max_gm",
    "with_trust",
    "work_dir_for",
    "write_table",
]
