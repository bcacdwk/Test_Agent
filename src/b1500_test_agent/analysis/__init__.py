"""Analysis of archived runs: datasets, quality, extraction methods and plots (blueprint 2.8).

Ad-hoc use from agent scripts in ``work/``::

    from b1500_test_agent.analysis import load_run, assess_quality, vth_linear_extrapolation, work_dir_for
    d = load_run("S20261117T063012Z-7f3a")
    report = assess_quality(d)
    vth = vth_linear_extrapolation(d)          # value=None with outcome "refused"/"failed" and an error message
    out_dir = work_dir_for(d.run_id)           # never write into the run folder

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
from b1500_test_agent.analysis.errors import MethodNotImplementedError, RunFormatError, RunNotFoundError
from b1500_test_agent.analysis.mosfet import gm, local_derivative, vth_linear_extrapolation
from b1500_test_agent.analysis.quality import MIN_SNR, assess_quality, noise_sigma, signal_to_noise
from b1500_test_agent.analysis.registry import ANALYSIS_METHODS, AnalysisMethod, run_method

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
    "RunData",
    "RunFormatError",
    "RunNotFoundError",
    "assess_quality",
    "column_unit",
    "find_run",
    "gm",
    "load_manifest",
    "load_run",
    "local_derivative",
    "measured_columns",
    "noise_sigma",
    "read_table",
    "run_method",
    "run_relpath",
    "signal_to_noise",
    "source_columns",
    "status_column",
    "trust_levels",
    "validate_table",
    "value_column",
    "vth_linear_extrapolation",
    "with_trust",
    "work_dir_for",
    "write_table",
]
