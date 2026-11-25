"""Analysis method registry (blueprint 2.8 ``ANALYSIS_METHODS``) and the uniform runner used by ``analyze_run``.

``run_method(name, data, options, criteria=...)`` returns ``list[ExtractionResult]`` (extraction methods), a
``QualityReport`` (``quality_report``) or a ``PlotSet`` (``plot_iv``: PNG bytes the caller stores through the archive
as ``plots/<name>-<n>.png``). It raises ``InvalidInputError`` for an unknown method, an unknown or invalid
option, or a method that does not apply to the run's recipe/kind; every registered method is implemented (the v1
"declared only" state went with WP11.2). Refusals on untrusted data are results (``outcome``
``refused``), not exceptions. ``options`` come from JSON (``analyze_run`` ``options{}`` or a recipe's
``analysis_defaults``); the trust policy is not an option: the caller passes the recipe's ``QualityCriteria`` as
``criteria``, so only ``force`` (flagged) can override a refusal.

Every method carries ``families`` (blueprint v2 2.10): the recipe families (``smu cmu spgu wgfmu nvm reliability
system``, ``Recipe.family``) whose runs it serves; ``methods_for(family)`` lists them. A method applicable (by
``recipes``/``kinds``) to a runnable recipe lists that recipe's family (a registry test checks it).

Two-run methods (blueprint v2 2.9 ``analyze_run`` ``options.reference_run``; WP7.3): a method whose function takes the
keyword ``reference`` (a ``RunData``) is offered the option ``reference_run`` (a run id) instead; ``run`` loads that
run with ``load_reference`` (the service passes one that only accepts finished runs of its data root) or, without one,
``load_run`` from the data root that holds ``data`` (the ``runs/`` folder above its run folder), and passes it as
``reference``. A missing or unknown ``reference_run`` is ``InvalidInputError``.

File methods (output ``files``, WP7.7): ``export_spice_netlist`` returns a ``SpiceExport`` (text files plus results)
that the server stores under the run folder's ``analysis/`` (``RunFolder.add_export``), like the PNGs of a
``PlotSet``.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any, Literal, get_args

from pydantic import ValidationError

from b1500_test_agent.analysis.charge_pumping import charge_pumping
from b1500_test_agent.analysis.cv import (
    cv_cox,
    cv_doping_profile,
    cv_flatband,
    cv_hysteresis,
    cv_vth,
    impedance_convert,
    plot_cv_method,
)
from b1500_test_agent.analysis.cv_variants import (
    cf_dispersion,
    ct_recovery,
    cv_ac_dependence,
    cv_butterfly,
    cv_pulsed_vs_dc,
)
from b1500_test_agent.analysis.dataset import RunData, load_run
from b1500_test_agent.analysis.diode import diode_fit, forward_voltage
from b1500_test_agent.analysis.dit import dit_conductance, dit_high_low
from b1500_test_agent.analysis.fefet import memory_window
from b1500_test_agent.analysis.floor import zero_floor
from b1500_test_agent.analysis.leakage import leakage_at
from b1500_test_agent.analysis.model import compact_model_fit, export_spice_netlist, model_compare
from b1500_test_agent.analysis.mosfet import (
    gm_max,
    ion_ioff,
    output_metrics,
    subthreshold_swing,
    vth_constant_current,
    vth_linear_extrapolation,
    vth_max_gm,
)
from b1500_test_agent.analysis.mosfet_family import body_effect, dibl
from b1500_test_agent.analysis.noise import it_statistics, plot_psd_method, psd_welch, rtn_levels
from b1500_test_agent.analysis.nvm import endurance_summary, memory_window_pulse, retention_fit, switching_kinetics_fit
from b1500_test_agent.analysis.plots import PlotSet, plot_iv_method
from b1500_test_agent.analysis.pulse import breakdown_voltage, pulse_plateau, pulsed_vs_dc, vth_search_value
from b1500_test_agent.analysis.pund import plot_pund_method, pund_polarization
from b1500_test_agent.analysis.quality import assess_quality
from b1500_test_agent.analysis.reliability import plot_timeseries_method, sampling_summary, time_to_breakdown
from b1500_test_agent.analysis.resistor import kelvin_resistance, resistance
from b1500_test_agent.analysis.spice import SpiceExport
from b1500_test_agent.analysis.stress import bti_power_law, degradation_vs_time, fast_bti_shift, silc
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import ExtractionResult, QualityReport, TrustPolicy
from b1500_test_agent.models.recipe import RecipeFamily

Milestone = Literal["M1", "M2", "M5", "M6", "M7", "M8", "M9", "M10", "M11"]
FAMILIES: tuple[RecipeFamily, ...] = get_args(RecipeFamily)
MethodOutput = Literal["quality_report", "extraction", "plots", "files"]
MethodResult = list[ExtractionResult] | QualityReport | PlotSet | SpiceExport

_RESERVED_ARGS = frozenset({"d", "criteria", "reference"})
REFERENCE_OPTION = "reference_run"
"""Option of a two-run method: the run id of the reference run (blueprint v2 2.9)."""
_RUN_ID = re.compile(r"^[SH]\d{8}T\d{6}Z-[0-9a-f]{4}$")
ReferenceLoader = Callable[[str], RunData]

_WGFMU_TRANSFER = ("wgfmu.pulsed_iv", "wgfmu.fast_iv")
"""WGFMU transfer curves (kind ``wgfmu_waveform``, WP10.4): gate level (programmed) against drain current."""
_TRANSFER = ("mosfet.idvg", "mosfet.idvg_sync", "mosfet.idvg_pulsed", "fefet.dual_sweep_mw", *_WGFMU_TRANSFER,
             "generic.*")
_STAIRCASE = ("smu_staircase",)
_PULSED = ("smu_pulsed",)
_WGFMU = ("wgfmu_waveform",)
_TRANSFER_KINDS = (*_STAIRCASE, *_PULSED, *_WGFMU)
_PULSED_RECIPES = ("mosfet.idvg_pulsed", "mosfet.idvd_pulsed", "basic.pulsed_spot", *_WGFMU_TRANSFER, "generic.*")
_SWEEPS = ("smu_staircase", "smu_stepped")
_SPOT = ("smu_spot",)
_SMU: tuple[RecipeFamily, ...] = ("smu",)
_SMU_NVM: tuple[RecipeFamily, ...] = ("smu", "nvm")
_TRANSFER_FAMILIES: tuple[RecipeFamily, ...] = ("smu", "nvm", "wgfmu")
_SMU_RELIABILITY: tuple[RecipeFamily, ...] = ("smu", "reliability")
_SAMPLING = ("generic.smu_sampling", "mosfet.id_t_sampling", "reliability.tddb_cvs", "generic.*")
_SAMPLING_KINDS = ("smu_sampling",)
_STRESS_KINDS = ("stress_measure",)
_MODEL_RECIPES = ("mosfet.idvg", "mosfet.idvd", "mosfet.idvg_family", "mosfet.idvg_sync", "mosfet.body_effect",
                  "mosfet.idvg_pulsed", "mosfet.idvd_pulsed", "generic.*")
"""Id-Vg and Id-Vd recipes a compact model is fitted to (WP7.7)."""
_MODEL_KINDS = ("smu_staircase", "smu_stepped", "smu_pulsed")
_RELIABILITY: tuple[RecipeFamily, ...] = ("reliability",)
_CMU: tuple[RecipeFamily, ...] = ("cmu",)
_CMU_NVM: tuple[RecipeFamily, ...] = ("cmu", "nvm")
"""Families with ``cmu_measure`` runs: the MFCMU recipes and the FeCap C-V butterfly (``fecap.cv_butterfly``)."""
_CV_KINDS = ("cmu_measure",)
_MOSCAP = ("moscap.cv", "moscap.cv_multi_freq", "moscap.pulsed_cv")
"""The MOS-C DC bias sweeps (C-V, multi-frequency C-V, pulsed C-V); the C-f, C-t and AC-level runs have their own
methods (WP8.4)."""
_QSCV_KINDS = ("smu_qscv",)
"""The SMU quasi-static C-V kind (WP8.5): a capacitance run, plotted with ``plot_cv``."""
_NOT_CMU = ("[!cs]*", "s[!m]*", "smu_[!q]*")
"""Every kind but the MFCMU kinds ``cmu_*`` and the QSCV kind ``smu_qscv`` (``fnmatch``): capacitance runs plot with
``plot_cv``, not ``plot_iv``."""
_NOISE = ("wgfmu.rtn", "wgfmu.lfn", "wgfmu.custom_waveform", "generic.smu_sampling", "mosfet.id_t_sampling",
          "generic.*")
"""Sampled current/voltage records the noise methods read (WP10.5): the WGFMU noise and custom-waveform recipes and
the SMU sampling recipes."""
_NOISE_KINDS = ("wgfmu_waveform", "smu_sampling")
_SYSTEM: tuple[RecipeFamily, ...] = ("system",)
_TABLES: tuple[RecipeFamily, ...] = ("smu", "cmu", "spgu", "wgfmu", "nvm", "reliability", "system")
"""Families whose runs archive a measurement table (``system`` since ``system.zero_check``; self-test and
self-calibration runs still archive none)."""


@dataclass(frozen=True)
class AnalysisMethod:
    """One registered method: ``fn(data, *, criteria=None, **options)``; ``recipes`` are recipe-id patterns
    (``fnmatch``, e.g. ``generic.*``) and ``kinds`` measurement kinds it applies to (``*`` = any); ``families`` the
    recipe families whose runs it serves (at least one)."""

    name: str
    output: MethodOutput
    summary: str
    fn: Callable[..., Any]
    families: tuple[RecipeFamily, ...]
    recipes: tuple[str, ...] = ("*",)
    kinds: tuple[str, ...] = ("*",)
    milestone: Milestone = "M1"

    def __post_init__(self) -> None:
        unknown = sorted(set(self.families) - set(FAMILIES))
        if not self.families or unknown or len(set(self.families)) != len(self.families):
            raise ValueError(f"{self.name}: families must be distinct values of {list(FAMILIES)}; got "
                             f"{list(self.families)}.")

    @property
    def two_run(self) -> bool:
        """True for a two-run method (its function takes ``reference``; option ``reference_run``)."""
        return "reference" in inspect.signature(self.fn).parameters

    @property
    def options(self) -> tuple[str, ...]:
        """Option names ``run`` accepts (keyword parameters of ``fn`` except ``criteria``; ``reference_run`` for a
        two-run method)."""
        parameters = inspect.signature(self.fn).parameters.values()
        names = tuple(p.name for p in parameters if p.kind is p.KEYWORD_ONLY and p.name not in _RESERVED_ARGS)
        return (REFERENCE_OPTION, *names) if self.two_run else names

    def applies_to(self, recipe_id: str, kind: str) -> bool:
        """True when ``recipe_id`` matches one of ``recipes`` and ``kind`` one of ``kinds``."""
        return any(fnmatchcase(recipe_id, p) for p in self.recipes) and any(fnmatchcase(kind, k) for k in self.kinds)

    def run(
        self, data: RunData, options: Mapping[str, Any] | None = None, *, criteria: TrustPolicy | None = None,
        load_reference: ReferenceLoader | None = None,
    ) -> MethodResult:
        """Run the method on ``data`` (see the module docstring for errors, refusals and two-run methods)."""
        opts = dict(options or {})
        unknown = sorted(set(opts) - set(self.options))
        if unknown:
            raise InvalidInputError(f"{self.name} has no option(s) {unknown}; options: {list(self.options)}.")
        recipe_id, kind = data.manifest.recipe_id, data.manifest.plan.kind
        if not self.applies_to(recipe_id, kind):
            raise InvalidInputError(
                f"{self.name} does not apply to run {data.run_id} (recipe {recipe_id}, kind {kind}); it applies to "
                f"recipes {list(self.recipes)} of kinds {list(self.kinds)}."
            )
        if self.two_run:
            opts["reference"] = _reference(self.name, data, opts.pop(REFERENCE_OPTION, None), load_reference)
        try:
            out = self.fn(data, criteria=criteria, **opts)
        except ValidationError as exc:
            raise InvalidInputError(f"Invalid options for {self.name}: {exc}") from exc
        return [out] if isinstance(out, ExtractionResult) else out


def _reference(method: str, data: RunData, run_id: Any, load_reference: ReferenceLoader | None) -> RunData:
    """The reference run of a two-run method (``InvalidInputError`` when missing, malformed or the run itself)."""
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        raise InvalidInputError(f"{method} compares two runs: options.{REFERENCE_OPTION} must be the run id of the "
                                f"reference run (e.g. a DC run of the same device), got {run_id!r}.")
    if run_id == data.run_id:
        raise InvalidInputError(f"{method}: the reference run must be another run than {data.run_id}.")
    if load_reference is not None:
        return load_reference(run_id)
    root = next((p.parent for p in (data.path.parents if data.path is not None else []) if p.name == "runs"), None)
    return load_run(run_id, data_root=root)


def _quality_report(d: RunData, *, criteria: TrustPolicy | None = None) -> QualityReport:
    return assess_quality(d, criteria)


def _method(name: str, output: MethodOutput, fn: Callable[..., Any], summary: str, recipes: tuple[str, ...],
            kinds: tuple[str, ...] = _STAIRCASE, *, families: tuple[RecipeFamily, ...],
            milestone: Milestone = "M2") -> AnalysisMethod:
    return AnalysisMethod(name=name, output=output, summary=summary, fn=fn,
                          families=families, recipes=recipes, kinds=kinds, milestone=milestone)


_METHODS = [
    AnalysisMethod(
        name="quality_report", output="quality_report", fn=_quality_report, families=_TABLES,
        summary="Status-letter counts, trust fractions, noise and SNR per measured column; verdict ok|limited|"
                "untrusted.",
    ),
    AnalysisMethod(
        name="vth_linear_extrapolation", output="extraction", fn=vth_linear_extrapolation,
        families=_TRANSFER_FAMILIES, recipes=_TRANSFER, kinds=_TRANSFER_KINDS,
        summary="Vth = Vg-axis intercept of the tangent at max gm (or a given window) minus Vd/2.",
    ),
    _method("vth_constant_current", "extraction", vth_constant_current,
            "Vth where |Id| first reaches i_crit_a (x w_over_l when given).", _TRANSFER, _TRANSFER_KINDS,
            families=_TRANSFER_FAMILIES),
    _method("vth_max_gm", "extraction", vth_max_gm,
            "Vth at the maximum of dgm/dVg (transconductance change) minus Vd/2.", _TRANSFER, _TRANSFER_KINDS,
            families=_TRANSFER_FAMILIES),
    _method("subthreshold_swing", "extraction", subthreshold_swing,
            "Minimum dVg/dlog10|Id| in mV/dec over fit_points points (or `decades` decades).", _TRANSFER,
            _TRANSFER_KINDS, families=_TRANSFER_FAMILIES),
    _method("gm_max", "extraction", gm_max, "Maximum transconductance and its gate voltage.", _TRANSFER,
            _TRANSFER_KINDS, families=_TRANSFER_FAMILIES),
    _method("ion_ioff", "extraction", ion_ioff, "Ion at v_on, Ioff at v_off (default: sweep ends) and their ratio.",
            _TRANSFER, _TRANSFER_KINDS, families=_TRANSFER_FAMILIES),
    _method("output_metrics", "extraction", output_metrics,
            "Output family per step: Ron at the lowest |Vd|, gds in saturation, saturation onset Vd_sat.",
            ("mosfet.idvd", "mosfet.idvd_pulsed", "generic.*"), (*_SWEEPS, *_PULSED), families=_SMU),
    _method("resistance", "extraction", resistance,
            "Resistance, linearity and offset of an I-V line; classification open|short|in_range.",
            ("basic.contact_resistor", "basic.pulsed_spot", "wgfmu.dc_spot", "generic.*"),
            (*_STAIRCASE, *_SPOT, *_PULSED, *_WGFMU), families=("smu", "wgfmu")),
    _method("kelvin_resistance", "extraction", kelvin_resistance,
            "Four-wire R = slope of sensed V vs forced I, offset voltage, linearity; open|short|in_range.",
            ("resistor.kelvin_4w", "generic.*"), _SPOT, families=_SMU, milestone="M7"),
    _method("zero_floor", "extraction", zero_floor,
            "Zero check: offset and noise floor of every measured current per range; optional pass/fail limits.",
            ("system.zero_check", "generic.*"), _SPOT, families=(*_SYSTEM, *_SMU), milestone="M7"),
    _method("diode_fit", "extraction", diode_fit,
            "Diode ideality n, saturation current Is and series resistance Rs from the forward branch.",
            ("basic.diode_iv", "basic.iv_force_i", "generic.*"), families=_SMU),
    _method("forward_voltage", "extraction", forward_voltage,
            "Diode forward voltage Vf at a current (i_a or the plan parameter i_param; default 1 mA).",
            ("basic.diode_iv", "basic.iv_force_i", "generic.*"), families=_SMU, milestone="M7"),
    _method("dibl", "extraction", dibl,
            "DIBL in mV/V from constant-current Vth of transfer curves at the lowest and highest drain bias.",
            ("mosfet.idvg_family", "generic.*"), ("smu_stepped",), families=_SMU, milestone="M7"),
    _method("body_effect", "extraction", body_effect,
            "Body-effect coefficient dVth/dVsb from constant-current Vth of transfer curves at several body biases.",
            ("mosfet.body_effect", "generic.*"), ("smu_stepped",), families=_SMU, milestone="M7"),
    _method("leakage_at", "extraction", leakage_at, "|I| at bias v against limit_a; classification pass|fail.",
            ("mosfet.gate_leakage", "basic.diode_iv", "generic.*"), families=_SMU),
    _method("memory_window", "extraction", memory_window,
            "FeFET memory window Vth(fwd) - Vth(rev) of a double sweep, per-branch Vth, Ion and Ioff.",
            ("fefet.dual_sweep_mw", "generic.*"), families=_SMU_NVM),
    _method("plot_iv", "plots", plot_iv_method,
            "I-V plots (linear and/or log scale) stored as PNG files under the run folder's plots/.", ("*",),
            _NOT_CMU, families=("smu", "spgu", "wgfmu", "nvm", "reliability", "system")),
    _method("plot_timeseries", "plots", plot_timeseries_method,
            "Measured values against time t_s (else cycle or step), per phase, linear/log; PNGs under plots/.",
            ("*",), ("*",), families=_TABLES, milestone="M5"),
    _method("sampling_summary", "extraction", sampling_summary,
            "Initial/final/mean/std/drift of a sampled column vs t_s; optional stretched-exponential tau, beta.",
            _SAMPLING, _SAMPLING_KINDS, families=_SMU_RELIABILITY, milestone="M7"),
    _method("time_to_breakdown", "extraction", time_to_breakdown,
            "Time to breakdown under constant stress (compliance, current jump or threshold); censored if none.",
            _SAMPLING, _SAMPLING_KINDS, families=_SMU_RELIABILITY, milestone="M7"),
    _method("bti_power_law", "extraction", bti_power_law,
            "BTI threshold shift |dVth| = A t^n over the stress reads (exponent n, A at 1 s); recovered fraction.",
            ("reliability.bti_sms", "igzo.bias_stress", "reliability.hci", "wgfmu.fast_bti", "generic.*"),
            _STRESS_KINDS, families=_RELIABILITY, milestone="M7"),
    _method("fast_bti_shift", "extraction", fast_bti_shift,
            "Fast BTI: dVth per microsecond WGFMU read (own Id-Vg or the reference curve), |dVth| = A t^n, read time "
            "off the stress.",
            ("wgfmu.fast_bti", "generic.*"), _STRESS_KINDS, families=_RELIABILITY, milestone="M10"),
    _method("degradation_vs_time", "extraction", degradation_vs_time,
            "Change of Id, Vth or Ig against stress time: power law b t^m or stretched exponential tau, beta.",
            ("reliability.*", "igzo.bias_stress", "generic.*"), _STRESS_KINDS, families=_RELIABILITY,
            milestone="M7"),
    _method("charge_pumping", "extraction", charge_pumping,
            "Charge pumping: Icp per pulse frequency (base-level plateau), charge per cycle Qcp = dIcp/df and its "
            "linearity; Nit, Dit with the gate area and energy window.",
            ("mosfet.charge_pumping", "generic.*"), ("spgu_pulse",), families=("spgu",), milestone="M9"),
    _method("cv_cox", "extraction", cv_cox,
            "Oxide capacitance: MOS-C accumulation extrapolation 1/C vs 1/Q (C-V or QSCV), or the split C-V plateau "
            "Cox*W*L; EOT.", (*_MOSCAP, "moscap.qscv", "mosfet.cgc_cv"), (*_CV_KINDS, *_QSCV_KINDS), families=_CMU,
            milestone="M8"),
    _method("cv_flatband", "extraction", cv_flatband,
            "MOS-C flatband voltage at the flatband capacitance (Cox, doping, Debye length; needs the gate area).",
            _MOSCAP, _CV_KINDS, families=_CMU, milestone="M8"),
    _method("cv_doping_profile", "extraction", cv_doping_profile,
            "MOS-C substrate doping from the depletion slope of 1/C^2 (needs the gate area); depth window.",
            _MOSCAP, _CV_KINDS, families=_CMU, milestone="M8"),
    _method("cv_vth", "extraction", cv_vth,
            "Threshold voltage: MOS-C from Vfb, Nsub and Cox; split C-V at the onset of the inversion capacitance.",
            (*_MOSCAP, "mosfet.cgc_cv", "mosfet.cgd_cv"), _CV_KINDS, families=_CMU, milestone="M8"),
    _method("cv_hysteresis", "extraction", cv_hysteresis,
            "C-V hysteresis of a double sweep: Vfb(rev) - Vfb(fwd) at the flatband capacitance.",
            _MOSCAP, _CV_KINDS, families=_CMU, milestone="M8"),
    _method("impedance_convert", "extraction", impedance_convert,
            "MFCMU readings in another pair (Cp-G, Cp-D, Cs-Rs, Cs-D, Z-theta) per frequency; series-R removal.",
            ("*",), _CV_KINDS, families=_CMU_NVM, milestone="M8"),
    _method("plot_cv", "plots", plot_cv_method,
            "C-V, C-f, C-t, C-ACV or QSCV plots per frequency and segment, 1/C^2 for a MOS-C; PNGs under plots/.",
            ("*",), (*_CV_KINDS, *_QSCV_KINDS), families=_CMU_NVM, milestone="M8"),
    _method("dit_high_low", "extraction", dit_high_low,
            "Dit over the gap from a QSCV and an HF C-V of one device (options.reference_run, either order): "
            "Dit = (C_LF Cox/(Cox-C_LF) - C_HF Cox/(Cox-C_HF))/(qA), energy by the Berglund integral; midgap, "
            "mean, min, max.", ("moscap.qscv", "moscap.cv"), (*_QSCV_KINDS, *_CV_KINDS), families=_CMU,
            milestone="M8"),
    _method("dit_conductance", "extraction", dit_conductance,
            "Dit(E) by the conductance method over the biases of a multi-frequency C-V: Gp/w continuum fit per bias "
            "(peak inside the band), energy from the HF depletion width; mean, min, max, tau range.",
            ("moscap.cv_multi_freq",), _CV_KINDS, families=_CMU, milestone="M8"),
    _method("cf_dispersion", "extraction", cf_dispersion,
            "C-f at a depletion bias: Gp/w (Nicollian-Goetzberger, Cox from options or geometry), continuum fit -> "
            "Dit, trap time constant, peak frequency; C dispersion.", ("moscap.cf",), _CV_KINDS, families=_CMU,
            milestone="M8"),
    _method("ct_recovery", "extraction", ct_recovery,
            "C-t after a bias step: 1/C^2 relaxation -> recovery time constant (inversion-layer formation), beta, "
            "deep-depletion and equilibrium capacitance.", ("moscap.ct",), _CV_KINDS, families=_CMU, milestone="M8"),
    _method("cv_ac_dependence", "extraction", cv_ac_dependence,
            "C against the oscillator level: small-signal C0 (C = C0 + C'' Vac^2/4), curvature, largest level within "
            "a tolerance.", ("moscap.cv_ac_level",), _CV_KINDS, families=_CMU, milestone="M8"),
    _method("cv_butterfly", "extraction", cv_butterfly,
            "FeCap C-V double sweep: peak voltages of the rising and falling branch -> coercive voltage, imprint, "
            "Ec (film thickness).", ("fecap.cv_butterfly",), _CV_KINDS, families=("nvm",), milestone="M8"),
    _method("cv_pulsed_vs_dc", "extraction", cv_pulsed_vs_dc,
            "Pulsed against a DC C-V reference run (options.reference_run): Vfb difference, Cox ratio, C ratio at the "
            "inversion end (deep depletion).", ("moscap.pulsed_cv",), _CV_KINDS, families=_CMU, milestone="M8"),
    _method("silc", "extraction", silc,
            "Stress-induced leakage: (Ig - Ig0)/Ig0 at v_sense, its power-law exponent, Ig0 and injected charge.",
            ("reliability.silc", "reliability.bti_sms", "reliability.hci", "generic.*"), _STRESS_KINDS,
            families=_RELIABILITY, milestone="M7"),
]

_METHODS += [
    _method("pulsed_vs_dc", "extraction", pulsed_vs_dc,
            "Pulsed minus DC current at v (default: the largest pulsed current) against a DC reference run "
            "(options.reference_run), the ratio and the largest relative difference.", _PULSED_RECIPES,
            (*_PULSED, *_WGFMU), families=("smu", "wgfmu"), milestone="M7"),
    _method("memory_window_pulse", "extraction", memory_window_pulse,
            "Program/read runs: memory window Vth(erase) - Vth(program) of the reads after the pulses (or the read "
            "currents and their ratio for spot reads), per state mean and spread.",
            ("fefet.pulse_write_read", "spgu.program_smu_read", "fefet.fast_program_read", "generic.*"),
            ("pulse_read", "wgfmu_waveform"), families=("nvm",), milestone="M9"),
    _method("switching_kinetics_fit", "extraction", switching_kinetics_fit,
            "Switching kinetics of an amplitude x width grid run: NLS fit tau0, Va, beta (alpha) of "
            "1 - exp(-(w/tau(V))^beta); ISPP runs: v50 and the step slope; reset-read consistency.",
            ("fefet.switching_kinetics", "generic.*"), ("pulse_read",), families=("nvm",), milestone="M9"),
    _method("endurance_summary", "extraction", endurance_summary,
            "Endurance run: memory window per checkpoint cycle count; initial, maximum and final window, wake-up, "
            "fatigue and cycles to failure (window below a criterion).",
            ("fefet.endurance", "generic.*"), ("pulse_read",), families=("nvm",), milestone="M9"),
    _method("pund_polarization", "extraction", pund_polarization,
            "PUND of a ferroelectric capacitor: Pr from the switched charge (P - U, N - D), Ps with the linear "
            "dielectric removed, Vc and Ec from the switching-current peaks, imprint; per read over endurance "
            "checkpoints: Pr initial/max, wake-up, fatigue, cycles to failure.",
            ("fecap.pund", "fecap.endurance_pund", "generic.*"), ("wgfmu_waveform", "pulse_read"),
            families=("nvm",), milestone="M10"),
    _method("plot_pund", "plots", plot_pund_method,
            "PUND plots: currents of P, U, N, D against time, polarization against voltage, Pr against cycles; PNG "
            "under plots/.", ("fecap.pund", "fecap.endurance_pund", "generic.*"), ("wgfmu_waveform", "pulse_read"),
            families=("nvm",), milestone="M10"),
    _method("retention_fit", "extraction", retention_fit,
            "Retention run: Vth of each written state and the memory window versus log10(t), slopes per decade, the "
            "window extrapolated to a target time and the time it reaches a criterion.",
            ("fefet.retention", "generic.*"), ("pulse_read",), families=("nvm",), milestone="M9"),
    _method("pulse_plateau", "extraction", pulse_plateau,
            "Plateau current (or voltage) of a pulse: per-pulse mean with edge trimming (time-resolved data) or the "
            "pulse-end reading, at level v, pulse number or the strongest pulse.", (*_PULSED_RECIPES, "wgfmu.*"),
            (*_PULSED, *_WGFMU), families=("smu", "wgfmu"), milestone="M7"),
    _method("vth_search_value", "extraction", vth_search_value,
            "Threshold voltage of a search run: the gate voltage the instrument found at the critical drain current "
            "(status N), with the reading vs the target.", ("mosfet.vth_search", "generic.*"), ("smu_search",),
            families=_SMU, milestone="M7"),
    _method("breakdown_voltage", "extraction", breakdown_voltage,
            "Breakdown voltage of a linear search (step reaching the current criterion) or quasi-pulsed run "
            "(compliance at the detection); no breakdown: a lower bound.",
            ("basic.breakdown_search", "dielectric.bdv", "generic.*"), ("smu_search",), families=_RELIABILITY,
            milestone="M7"),
    _method("compact_model_fit", "extraction", compact_model_fit,
            "Fit an EKV (vth, n, beta, theta, lambda, rs) or SPICE level-1 (vto, beta, lambda) model to an Id-Vg or "
            "Id-Vd run; standard errors and rms_log/rms_rel of the fit.", _MODEL_RECIPES, _MODEL_KINDS,
            families=_SMU, milestone="M7"),
    _method("model_compare", "extraction", model_compare,
            "Evaluate a compact model (options.params, else fitted to this run) against the run: rms_rel, rms_log "
            "(decades), max_rel, rms_error (A), per curve.", _MODEL_RECIPES, _MODEL_KINDS, families=_SMU,
            milestone="M7"),
    _method("export_spice_netlist", "files", export_spice_netlist,
            "Write the compact model as a SPICE .model card (level 1) or EKV subcircuit (.lib) and a netlist that "
            "reproduces the run's sweep (.sp) under analysis/; ngspice or HSPICE dialect.", _MODEL_RECIPES,
            _MODEL_KINDS, families=_SMU, milestone="M7"),
]

_METHODS += [
    _method("it_statistics", "extraction", it_statistics,
            "Sampled record statistics: mean, std, std/|mean|, relative linear drift, sampling interval; skewness, "
            "kurtosis and a bimodality flag (two-level RTN).", _NOISE, _NOISE_KINDS, families=("smu", "wgfmu"),
            milestone="M10"),
    _method("psd_welch", "extraction", psd_welch,
            "Welch PSD S(f) and S/mean^2 of a sampled record; fit A/f^gamma + white (+ one Lorentzian, model auto): "
            "gamma, normalized 1/f level at 1 Hz and at f_ref, RTN corner; input-referred noise with gm_s.", _NOISE,
            _NOISE_KINDS, families=("smu", "wgfmu"), milestone="M10"),
    _method("rtn_levels", "extraction", rtn_levels,
            "Two-level random telegraph noise: levels by mixture, hysteresis detection with level tracking, dwell "
            "times -> tau_c (capture), tau_e (emission), dI and dI/I; dwell survival fit and checks.", _NOISE,
            _NOISE_KINDS, families=("smu", "wgfmu"), milestone="M10"),
    _method("plot_psd", "plots", plot_psd_method,
            "PSD plot (S and S/mean^2 vs f, log-log): Welch estimate, fitted log bins, model and its parts; PNG "
            "under plots/.", _NOISE, _NOISE_KINDS, families=("smu", "wgfmu"), milestone="M10"),
]

ANALYSIS_METHODS: Mapping[str, AnalysisMethod] = MappingProxyType({m.name: m for m in _METHODS})
"""All analysis methods by name (implemented and declared)."""


def methods_for(family: RecipeFamily) -> list[AnalysisMethod]:
    """The registered methods tagged with ``family``, in registry order."""
    if family not in FAMILIES:
        raise InvalidInputError(f"Unknown recipe family {family!r}; families: {list(FAMILIES)}.")
    return [m for m in ANALYSIS_METHODS.values() if family in m.families]


def run_method(
    name: str, data: RunData, options: Mapping[str, Any] | None = None, *, criteria: TrustPolicy | None = None,
    load_reference: ReferenceLoader | None = None,
) -> MethodResult:
    """Run registered method ``name`` on ``data`` with JSON ``options`` and the recipe's trust ``criteria``
    (``load_reference``: how a two-run method loads ``options.reference_run``)."""
    method = ANALYSIS_METHODS.get(name)
    if method is None:
        raise InvalidInputError(f"Unknown analysis method {name!r}; known: {sorted(ANALYSIS_METHODS)}.")
    return method.run(data, options, criteria=criteria, load_reference=load_reference)
