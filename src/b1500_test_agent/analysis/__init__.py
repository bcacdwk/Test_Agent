"""Analysis of archived runs: datasets, quality, extraction methods and plots (blueprint 2.8).

Ad-hoc use from agent scripts in ``work/``::

    from b1500_test_agent.analysis import load_run, assess_quality, vth_linear_extrapolation, plot_iv, work_dir_for
    d = load_run("S20261117T063012Z-7f3a")
    report = assess_quality(d)
    vth = vth_linear_extrapolation(d)          # value=None with outcome "refused"/"failed" and an error message
    pngs = plot_iv(d, scale="log")             # PNGs under work/<run_id>/plots/
    pngs = plot_timeseries(d, log_time=True)   # time-series runs (t_s, cycle or step on x)
    lives = weibull_fit([load_run(r) for r in tddb_run_ids])   # Weibull beta/eta over TDDB runs (library only)
    bti = bti_power_law(load_run(bti_run_id))  # stress-measure runs: dVth = A t^n (+ recovery)
    mw = memory_window_pulse(load_run(pr_run_id))  # program/read runs: Vth(erase) - Vth(program)
    rtn = rtn_levels(load_run(rtn_run_id))     # RTN record: tau_c, tau_e, dI/I (noise.py)
    lfn = psd_welch(load_run(lfn_run_id))      # PSD fit: gamma, S/I^2 (+ plot_psd(d) -> work/<run_id>/plots/)
    f, s, nper = welch_psd(d.table["drain_I"], dt=1e-7)   # raw Welch PSD for own plots (spectrum.py)
    ekv = compact_model_fit(d)                 # EKV vth, n, beta, theta (+ lambda, rs); level 1 with model="level1"
    files = write_spice_files(export_spice_netlist(d), run_id=d.run_id)   # .lib + .sp under work/<run_id>/spice/
    mw_n = endurance_curve(load_run(endurance_run_id))  # endurance checkpoints: MW per cumulative cycle count
    pund = pund_polarization(load_run(pund_run_id))  # FeCap PUND: Pr, Ps, Ec (+ plot_pund(d))
    out_dir = work_dir_for(d.run_id)           # never write into the run folder

Methods (registry ``ANALYSIS_METHODS``, tagged with recipe families, ``methods_for(family)``; definitions in the
``mosfet.py``, ``mosfet_family.py``, ``resistor.py``, ``diode.py``, ``leakage.py``, ``fefet.py``, ``plots.py``,
``reliability.py``, ``stress.py``, ``nvm.py`` and ``noise.py`` docstrings): ``quality_report``,
``vth_linear_extrapolation``, ``vth_constant_current``, ``vth_max_gm``, ``subthreshold_swing``, ``gm_max``,
``ion_ioff``, ``output_metrics``, ``dibl``, ``body_effect``, ``resistance``, ``diode_fit``, ``forward_voltage``,
``leakage_at``, ``memory_window``, ``plot_iv``, ``plot_timeseries``, ``sampling_summary``, ``time_to_breakdown``,
``bti_power_law``, ``degradation_vs_time``, ``silc``, the C-V methods of ``cv.py`` (``cv_cox``, ``cv_flatband``,
``cv_doping_profile``, ``cv_vth``, ``cv_hysteresis``, ``impedance_convert``, ``plot_cv``; ``convert_table`` converts a
whole run), the C-V variants of ``cv_variants.py`` (``cf_dispersion``, ``ct_recovery``, ``cv_ac_dependence``,
``cv_butterfly``, the two-run ``cv_pulsed_vs_dc``), ``memory_window_pulse``, ``switching_kinetics_fit``,
``endurance_summary``, ``retention_fit`` (``nvm.py``, the NLS core in ``nls.py``), ``pund_polarization`` and
``plot_pund`` (``pund.py``), the compact models
``compact_model_fit``, ``model_compare`` and ``export_spice_netlist`` (``model.py``, ``spice.py``), the noise methods
``it_statistics``, ``psd_welch``, ``rtn_levels`` and ``plot_psd`` (``noise.py``; Welch PSD and fit in ``spectrum.py``);
library helpers: ``weibull_fit`` (over a run list), ``endurance_curve`` (MW per endurance checkpoint).
The run-table contract (``data.csv`` or ``data.npz`` +
``preview.csv``, columns) is defined in ``dataset.py``.

Errors: exceptions mean the call cannot be served (``RunNotFoundError``, ``RunFormatError``, ``InvalidInputError``,
``MethodNotImplementedError``); data that do not allow a trustworthy value give an ``ExtractionResult`` with
``outcome`` ``refused`` (untrusted data without ``force``) or ``failed``.
"""

from b1500_test_agent.analysis.cv import (
    convert_table,
    cv_cox,
    cv_doping_profile,
    cv_flatband,
    cv_hysteresis,
    cv_vth,
    impedance_convert,
    plot_cv,
)
from b1500_test_agent.analysis.cv_variants import (
    cf_dispersion,
    ct_recovery,
    cv_ac_dependence,
    cv_butterfly,
    cv_pulsed_vs_dc,
)
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
from b1500_test_agent.analysis.dit import dit_conductance, dit_high_low, high_low_profile
from b1500_test_agent.analysis.errors import MethodNotImplementedError, RunFormatError, RunNotFoundError
from b1500_test_agent.analysis.fefet import memory_window
from b1500_test_agent.analysis.leakage import leakage_at
from b1500_test_agent.analysis.model import CompactModel, compact_model_fit, export_spice_netlist, model_compare
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
from b1500_test_agent.analysis.noise import it_statistics, plot_psd, psd_welch, rtn_levels, two_level
from b1500_test_agent.analysis.nvm import (
    endurance_curve,
    endurance_summary,
    memory_window_pulse,
    pulse_reads,
    retention_fit,
    switching_kinetics_fit,
)
from b1500_test_agent.analysis.plots import PlotSet, plot_iv, render_iv
from b1500_test_agent.analysis.pund import plot_pund, pund_polarization, render_pund
from b1500_test_agent.analysis.qscv import quasi_static_role, render_qscv
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
from b1500_test_agent.analysis.spectrum import fit_psd, log_bins, welch_psd
from b1500_test_agent.analysis.spice import SpiceExport, write_spice_files
from b1500_test_agent.analysis.stress import bti_power_law, degradation_vs_time, fast_bti_shift, silc, stress_reads

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
    "CompactModel",
    "MethodNotImplementedError",
    "PlotSet",
    "RunData",
    "RunFormatError",
    "RunNotFoundError",
    "SpiceExport",
    "assess_quality",
    "body_effect",
    "bti_power_law",
    "cf_dispersion",
    "column_unit",
    "compact_model_fit",
    "convert_table",
    "ct_recovery",
    "cv_ac_dependence",
    "cv_butterfly",
    "cv_cox",
    "cv_doping_profile",
    "cv_flatband",
    "cv_hysteresis",
    "cv_pulsed_vs_dc",
    "cv_vth",
    "degradation_vs_time",
    "dibl",
    "diode_fit",
    "dit_conductance",
    "dit_high_low",
    "endurance_curve",
    "endurance_summary",
    "export_spice_netlist",
    "fast_bti_shift",
    "find_run",
    "fit_psd",
    "fit_stretched_exponential",
    "forward_voltage",
    "gm",
    "gm_max",
    "high_low_profile",
    "impedance_convert",
    "ion_ioff",
    "it_statistics",
    "leakage_at",
    "load_manifest",
    "load_run",
    "local_derivative",
    "log_bins",
    "measured_columns",
    "memory_window",
    "memory_window_pulse",
    "methods_for",
    "model_compare",
    "noise_sigma",
    "output_metrics",
    "plot_cv",
    "plot_iv",
    "plot_psd",
    "plot_pund",
    "plot_timeseries",
    "psd_welch",
    "pulse_reads",
    "pund_polarization",
    "quasi_static_role",
    "read_table",
    "read_table_excerpt",
    "render_iv",
    "render_pund",
    "render_qscv",
    "render_timeseries",
    "resistance",
    "retention_fit",
    "rtn_levels",
    "run_method",
    "run_relpath",
    "run_table_path",
    "sampling_summary",
    "signal_to_noise",
    "silc",
    "source_columns",
    "status_column",
    "stress_reads",
    "subthreshold_swing",
    "switching_kinetics_fit",
    "time_to_breakdown",
    "trust_levels",
    "two_level",
    "validate_table",
    "value_column",
    "vth_constant_current",
    "vth_linear_extrapolation",
    "vth_max_gm",
    "weibull_fit",
    "welch_psd",
    "with_trust",
    "work_dir_for",
    "write_run_table",
    "write_spice_files",
    "write_table",
]
