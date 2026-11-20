"""Analysis of archived runs: datasets, quality, extraction methods and plots (blueprint 2.8).

Ad-hoc use from agent scripts in ``work/``::

    from b1500_test_agent.analysis import load_run, assess_quality, vth_linear_extrapolation, plot_iv, work_dir_for
    d = load_run("S20261117T063012Z-7f3a")
    report = assess_quality(d)
    vth = vth_linear_extrapolation(d)          # value=None with outcome "refused"/"failed" and an error message
    pngs = plot_iv(d, scale="log")             # PNGs under work/<run_id>/plots/
    pngs = plot_timeseries(d, log_time=True)   # time-series runs (t_s, cycle or step on x)
    lives = weibull_fit([load_run(r) for r in tddb_run_ids])   # Weibull beta/eta over TDDB runs (library only)
    out_dir = work_dir_for(d.run_id)           # never write into the run folder

Methods (registry ``ANALYSIS_METHODS``, tagged with recipe families, ``methods_for(family)``; definitions in the
``mosfet.py``, ``mosfet_family.py``, ``resistor.py``, ``diode.py``, ``leakage.py``, ``fefet.py``, ``plots.py`` and
``reliability.py`` docstrings): ``quality_report``, ``vth_linear_extrapolation``, ``vth_constant_current``,
``vth_max_gm``, ``subthreshold_swing``, ``gm_max``, ``ion_ioff``, ``output_metrics``, ``dibl``, ``body_effect``,
``resistance``, ``diode_fit``, ``forward_voltage``, ``leakage_at``, ``memory_window``, ``plot_iv``,
``plot_timeseries``, ``sampling_summary``, ``time_to_breakdown``; library helper over a run list: ``weibull_fit``.
The run-table contract (``data.csv`` or ``data.npz`` +
``preview.csv``, columns) is defined in ``dataset.py``.

Errors: exceptions mean the call cannot be served (``RunNotFoundError``, ``RunFormatError``, ``InvalidInputError``,
``MethodNotImplementedError``); data that do not allow a trustworthy value give an ``ExtractionResult`` with
``outcome`` ``refused`` (untrusted data without ``force``) or ``failed``.
"""

from b1500_test_agent.analysis.dataset import (
    CSV_MAX_ROWS,
    DATA_FILE,
    INDEX_FILE,
    MANIFEST_FILE,
    NPZ_FILE,
    PREVIEW_FILE,
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
    read_table_excerpt,
    run_relpath,
    run_table_path,
    source_columns,
    status_column,
    trust_levels,
    validate_table,
    value_column,
    with_trust,
    work_dir_for,
    write_run_table,
    write_table,
)
from b1500_test_agent.analysis.diode import diode_fit, forward_voltage
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
from b1500_test_agent.analysis.mosfet_family import body_effect, dibl
from b1500_test_agent.analysis.plots import PlotSet, plot_iv, render_iv
from b1500_test_agent.analysis.quality import MIN_SNR, assess_quality, noise_sigma, signal_to_noise
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS, AnalysisMethod, methods_for, run_method
from b1500_test_agent.analysis.reliability import (
    fit_stretched_exponential,
    plot_timeseries,
    render_timeseries,
    sampling_summary,
    time_to_breakdown,
    weibull_fit,
)
from b1500_test_agent.analysis.resistor import resistance

__all__ = [
    "ANALYSIS_METHODS",
    "CSV_MAX_ROWS",
    "DATA_FILE",
    "INDEX_FILE",
    "MANIFEST_FILE",
    "MIN_SNR",
    "NPZ_FILE",
    "PREVIEW_FILE",
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
    "body_effect",
    "column_unit",
    "dibl",
    "diode_fit",
    "find_run",
    "fit_stretched_exponential",
    "forward_voltage",
    "gm",
    "gm_max",
    "ion_ioff",
    "leakage_at",
    "load_manifest",
    "load_run",
    "local_derivative",
    "measured_columns",
    "memory_window",
    "methods_for",
    "noise_sigma",
    "output_metrics",
    "plot_iv",
    "plot_timeseries",
    "read_table",
    "read_table_excerpt",
    "render_iv",
    "render_timeseries",
    "resistance",
    "run_method",
    "run_relpath",
    "run_table_path",
    "sampling_summary",
    "signal_to_noise",
    "source_columns",
    "status_column",
    "subthreshold_swing",
    "time_to_breakdown",
    "trust_levels",
    "validate_table",
    "value_column",
    "vth_constant_current",
    "vth_linear_extrapolation",
    "vth_max_gm",
    "weibull_fit",
    "with_trust",
    "work_dir_for",
    "write_run_table",
    "write_table",
]
