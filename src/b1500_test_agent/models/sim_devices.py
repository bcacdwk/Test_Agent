"""Simulator device-model parameters added in v2 (blueprint 4.2): truth parameters of ``moscap``, ``capacitor``,
``fixture``, ``dielectric``, ``fecap`` and ``noise``, and the parameter groups that extend v1 models (FeFET pulse
switching, retention and endurance; the dynamic ``mosfet``).

``models/sim.py`` registers them in ``DEVICE_PARAMS``/``DEVICE_TERMINALS``; this module imports only ``models``.
Units follow the device literature: areas in µm², thicknesses in nm, doping in cm⁻³, interface-trap density in
cm⁻²·eV⁻¹, polarization in µC/cm², fields in MV/cm; currents, voltages, capacitances and times in SI units. Every
model is deterministic; the only randomness (``dielectric`` Weibull draw, ``noise`` series) is seeded.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from b1500_test_agent.models.analysis import PositiveFloat
from b1500_test_agent.models.common import StrictModel

# -- parameter groups shared with v1 models --------------------------------------------------------------------------


class EnduranceParams(StrictModel):
    """Wake-up and fatigue of a ferroelectric versus bipolar switching cycles ``N`` (FeFET, FeCap).

    The switchable polarization is scaled by ``s(N) = (1 - wake_frac·exp(-N/wake_cycles)) /
    (1 + (N/fatigue_cycles)^fatigue_exp)`` (the fatigue factor is 1 while ``fatigue_cycles`` is 0). With both effects
    off (the defaults) the model keeps no cycle count.
    """

    wake_frac: float = Field(default=0.0, ge=0.0, le=0.95)
    wake_cycles: PositiveFloat = 1.0e3
    fatigue_cycles: float = Field(default=0.0, ge=0.0, le=1.0e15)
    fatigue_exp: float = Field(default=0.5, gt=0.0, le=5.0)


class FerroKineticsParams(EnduranceParams):
    """FeFET pulse switching (nucleation-limited switching, NLS), retention and endurance (blueprint 4.2).

    A gate pulse of amplitude ``V`` and width ``w`` switches the fraction ``S = 1 - exp(-(w/τ(V))^beta_sw)`` of the
    way to the quasi-static (DC loop) target, with ``τ(V) = tau0_s·exp((va_v/|V|)^alpha)`` (Tagantsev et al., Phys.
    Rev. B 66, 214109, 2002; field form of Merz's law). Retention: after the last switching event the polarization
    decays as ``P_w·(1 - retention_rate·log10(1 + t/retention_t0_s))``; 0 turns retention loss off.
    """

    tau0_s: PositiveFloat = 1.0e-10
    va_v: PositiveFloat = 12.0
    alpha: float = Field(default=2.0, ge=0.5, le=5.0)
    beta_sw: float = Field(default=1.0, ge=0.2, le=5.0)
    retention_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    retention_t0_s: PositiveFloat = 1.0


class MosfetDynamicsParams(StrictModel):
    """Physics the v2 ``mosfet`` model adds to ``mosfet_ekv`` (every effect is off at its default).

    - **Geometry** (gate capacitances for split C-V): ``w_um``, ``l_um``, ``tox_nm`` (all or none), relative oxide
      permittivity ``eps_ox``, substrate doping ``nsub_cm3`` and gate-overlap capacitance per edge ``cov_f_per_m``
      (F per metre of width). The flatband voltage follows from ``vth0`` (``Vth = Vfb + 2φB + γ·sqrt(2φB)``).
    - **Self-heating**: temperature rise ``ΔT = rth_k_per_w·|Id·Vds|`` reached with time constant ``tau_th_s``;
      ``Vth`` moves by ``-vth_tc_v_per_k·ΔT`` (towards zero), ``β`` scales by ``(T/T0)^-mobility_t_exp``.
    - **BTI** (reaction-diffusion power law, Kaczer et al., IRPS 2008): under gate overdrive ``V = |Vgs| >
      bti_v_min`` the threshold magnitude grows as ``ΔVth = bti_a·V^bti_gamma·t^bti_n``; without stress it recovers as
      ``ΔVth0·(1 - bti_recovery·log10(1 + t/bti_recovery_t0_s))``.
    - **HCI** (Takeda/Hu power law): with the channel on and ``Vds`` in the drain direction, ``β`` degrades by
      ``ΔId/Id0 = -hci_b·(|Vds|/hci_vd_ref_v)^hci_vd_exp·t^hci_m`` (permanent).
    - **IGZO bias-stress drift** (stretched exponential, Libsch & Kanicki, APL 62, 1286, 1993): under gate bias ``V``
      the threshold approaches ``igzo_dvth_per_v·V`` as ``ΔV∞·(1 - exp(-(t/igzo_tau_s)^igzo_beta))`` and recovers with
      ``igzo_recovery_tau_s`` (default: ``igzo_tau_s``) when the bias is lowered.
    - **DC sweeps as stress** (``sweep_stress``, v2.1 debug case ``example-igzo-vth-drift``): each step of a DC
      staircase or spot measurement also ages the device (BTI, HCI, IGZO drift) for the step's duration at its
      applied voltages, so a repeated Id-Vg is itself a bias stress; off (default), a DC measurement is a quasi-static
      read that never ages the device (the fitted stress-measure and sampling scenarios assume short reads).
    - **Charge pumping** (Groeseneken et al., IEEE TED 31, 42, 1984; needs the geometry): a gate pulse train that
      swings the surface from accumulation to inversion pumps the recombination current ``Icp = q·f·A·dit_cm2_ev·ΔE``
      out of the interface traps (mean density ``dit_cm2_ev``, capture cross section ``cp_sigma_cm2``); the energy
      window ``ΔE`` follows from the emission-limited levels of the falling and rising edges, and the base and top
      levels must pass the flatband and threshold voltages (smoothed over ``cp_edge_v``).
    """

    w_um: PositiveFloat | None = None
    l_um: PositiveFloat | None = None
    tox_nm: float | None = Field(default=None, gt=0.3, le=1000.0)
    eps_ox: float = Field(default=3.9, gt=1.0, le=100.0)
    nsub_cm3: float = Field(default=1.0e17, ge=1.0e13, le=1.0e20)
    ni_cm3: float = Field(default=1.0e10, gt=0.0, le=1.0e13)
    cov_f_per_m: float = Field(default=0.0, ge=0.0, le=1.0e-6)
    rth_k_per_w: float = Field(default=0.0, ge=0.0, le=1.0e7)
    tau_th_s: float = Field(default=1.0e-3, ge=0.0, le=1.0e3)
    vth_tc_v_per_k: float = Field(default=1.0e-3, ge=0.0, le=0.1)
    mobility_t_exp: float = Field(default=1.5, ge=0.0, le=5.0)
    bti_a: float = Field(default=0.0, ge=0.0, le=10.0)
    bti_gamma: float = Field(default=3.0, ge=0.0, le=10.0)
    bti_n: float = Field(default=0.16, gt=0.0, le=1.0)
    bti_v_min: float = Field(default=0.0, ge=0.0, le=50.0)
    bti_recovery: float = Field(default=0.0, ge=0.0, le=1.0)
    bti_recovery_t0_s: PositiveFloat = 1.0e-6
    hci_b: float = Field(default=0.0, ge=0.0, le=10.0)
    hci_m: float = Field(default=0.5, gt=0.0, le=1.0)
    hci_vd_ref_v: PositiveFloat = 1.0
    hci_vd_exp: float = Field(default=4.0, ge=0.0, le=20.0)
    igzo_dvth_per_v: float = Field(default=0.0, ge=-1.0, le=1.0)
    igzo_tau_s: PositiveFloat = 1.0e3
    igzo_beta: float = Field(default=0.5, gt=0.0, le=1.0)
    igzo_recovery_tau_s: PositiveFloat | None = None
    sweep_stress: bool = False
    dit_cm2_ev: float = Field(default=0.0, ge=0.0, le=1.0e14)
    cp_sigma_cm2: float = Field(default=1.0e-16, gt=0.0, le=1.0e-12)
    cp_edge_v: float = Field(default=0.1, gt=0.0, le=2.0)

    @model_validator(mode="after")
    def _geometry_complete(self) -> MosfetDynamicsParams:
        given = [self.w_um is not None, self.l_um is not None, self.tox_nm is not None]
        if any(given) and not all(given):
            raise ValueError("w_um, l_um and tox_nm are given together (gate capacitances need all three).")
        if self.dit_cm2_ev > 0.0 and not all(given):
            raise ValueError("charge pumping (dit_cm2_ev > 0) needs the geometry w_um, l_um and tox_nm.")
        return self


# -- v2 device models ------------------------------------------------------------------------------------------------


class MoscapParams(StrictModel):
    """``moscap``: 1-D MOS capacitor (gate on oxide on a uniformly doped substrate), terminals ``gate``/``bulk``.

    Oxide capacitance ``Cox = ε0·eps_ox/tox`` per area; flatband voltage ``Vfb = phi_ms_v - q·qf_cm2/Cox -
    Q_it(ψs=0)/Cox`` (``qf_cm2``: fixed oxide charge, positive charges per cm²); interface traps ``Dit(E) = dit_cm2_ev
    + dit_edge_cm2_ev·(cosh(E/dit_width_ev) - 1)`` around midgap (neutral level at midgap) with capture cross
    section ``dit_sigma_cm2``; minority carriers follow AC below ``f_inv_hz`` (LF C-V) and form the inversion layer
    with time constant ``tau_inv_s`` (deep depletion when swept faster); ``rs_ohm`` in series, ``leak_s`` gate
    leakage conductance; border traps give a C-V hysteresis: their charge shifts ``Vfb`` by up to ``hysteresis_v``,
    charged at gate biases beyond ``+hysteresis_vc_v`` (inversion side of a p substrate) and discharged beyond
    ``-hysteresis_vc_v``.
    """

    substrate: Literal["p", "n"] = "p"
    area_um2: PositiveFloat = 1.0e4
    tox_nm: float = Field(default=10.0, gt=0.3, le=1000.0)
    eps_ox: float = Field(default=3.9, gt=1.0, le=100.0)
    eps_s: float = Field(default=11.7, gt=1.0, le=50.0)
    nsub_cm3: float = Field(default=1.0e17, ge=1.0e13, le=1.0e20)
    ni_cm3: float = Field(default=1.0e10, gt=0.0, le=1.0e13)
    temperature_k: float = Field(default=300.0, gt=0.0, le=600.0)
    phi_ms_v: float = Field(default=0.0, ge=-3.0, le=3.0)
    qf_cm2: float = Field(default=0.0, ge=-1.0e14, le=1.0e14)
    dit_cm2_ev: float = Field(default=0.0, ge=0.0, le=1.0e14)
    dit_edge_cm2_ev: float = Field(default=0.0, ge=0.0, le=1.0e14)
    dit_width_ev: float = Field(default=0.1, gt=0.0, le=1.0)
    dit_sigma_cm2: float = Field(default=1.0e-16, gt=0.0, le=1.0e-10)
    v_thermal_cm_s: PositiveFloat = 1.0e7
    f_inv_hz: PositiveFloat = 10.0
    tau_inv_s: PositiveFloat = 1.0
    rs_ohm: float = Field(default=0.0, ge=0.0, le=1.0e6)
    leak_s: float = Field(default=0.0, ge=0.0, le=1.0)
    hysteresis_v: float = Field(default=0.0, ge=0.0, le=5.0)
    hysteresis_vc_v: PositiveFloat = 2.0
    hysteresis_width_v: PositiveFloat = 0.1


class CapacitorParams(StrictModel):
    """``capacitor``: ``c_f`` in parallel with ``g_s``, both in series with ``esr_ohm`` (terminals ``a``/``b``).

    The CMU reference standard of blueprint 4.2 (``capacitor_100p``: ``c_f = 100e-12``)."""

    c_f: float = Field(gt=0.0, le=1.0e-3)
    g_s: float = Field(default=0.0, ge=0.0, le=1.0)
    esr_ohm: float = Field(default=0.0, ge=0.0, le=1.0e6)


class FixtureParams(StrictModel):
    """``fixture``: parasitics of the CMU cables, prober and fixture (terminals ``high``/``low``, wired to the CMU).

    Measured impedance ``Zm = Zs + 1/(Yo + 1/Zdut)`` with the open admittance ``Yo = 1/r_open_ohm + jω·c_open_f``
    and the short impedance ``Zs = r_short_ohm + jω·l_short_h``, rotated by the phase error ``phase_deg_per_mhz·f``
    until phase compensation (``ADJ``). Open and short corrections remove ``Yo`` and ``Zs`` (Keysight Impedance
    Measurement Handbook, 6th ed., section 4). The defaults are blueprint 4.2 values; the real station's parasitics
    and phase error are measured at bring-up (blueprint 7.6 item 7). TODO(verify) at M12.
    """

    c_open_f: float = Field(default=0.3e-12, ge=0.0, le=1.0e-9)
    r_open_ohm: PositiveFloat = 1.0e9
    r_short_ohm: float = Field(default=0.5, ge=0.0, le=1.0e3)
    l_short_h: float = Field(default=50.0e-9, ge=0.0, le=1.0e-3)
    phase_deg_per_mhz: float = Field(default=1.0, ge=-90.0, le=90.0)


class DielectricParams(StrictModel):
    """``dielectric``: gate-oxide or MIM test structure (terminals ``top``/``bottom``) with leakage and breakdown.

    Leakage ``I = sgn(V)·A·fn_a_a_v2·E²·exp(-fn_b_v_cm/E) + leak_s·V + silc_s·D·V`` with ``E = |V|/tox`` in V/cm
    (Fowler-Nordheim tunnelling, Lenzlinger & Snow, J. Appl. Phys. 40, 278, 1969); geometric capacitance
    ``ε0·eps_r·A/tox``. Breakdown: instantly at ``|V| ≥ ebd_mv_cm·tox`` (BDV); under lower stress when the
    accumulated damage ``D = ∫dt/t_bd(V)`` reaches 1, with the seeded Weibull life ``t_bd(V) = η(V)·W^(1/β)``,
    ``η(V) = tbd_eta_s·exp(-tbd_gamma_per_v·(|V| - tbd_v_ref))`` (E model) and ``W`` the unit-exponential draw of the
    current ``site`` (seed ``seed``); afterwards an ohmic path ``r_bd_ohm``. ``silc_s`` is the stress-induced leakage
    conductance at ``D = 1``.
    """

    area_um2: PositiveFloat = 1.0e4
    tox_nm: float = Field(default=5.0, gt=0.3, le=1000.0)
    eps_r: float = Field(default=3.9, gt=1.0, le=1000.0)
    fn_a_a_v2: float = Field(default=1.25e-6, ge=0.0, le=1.0)
    fn_b_v_cm: float = Field(default=2.5e8, gt=0.0, le=1.0e10)
    leak_s: float = Field(default=0.0, ge=0.0, le=1.0)
    silc_s: float = Field(default=0.0, ge=0.0, le=1.0)
    ebd_mv_cm: float = Field(default=12.0, gt=0.0, le=100.0)
    tbd_eta_s: PositiveFloat = 1.0e4
    tbd_v_ref: float = Field(default=5.0, gt=0.0, le=1.0e3)
    tbd_gamma_per_v: float = Field(default=8.0, ge=0.0, le=100.0)
    weibull_beta: float = Field(default=1.5, gt=0.1, le=20.0)
    seed: int = Field(default=0, ge=0)
    site: int = Field(default=0, ge=0)
    r_bd_ohm: float = Field(default=1.0e3, gt=0.0, le=1.0e9)


class FecapParams(EnduranceParams):
    """``fecap``: ferroelectric capacitor (terminals ``top``/``bottom``), Preisach-lite polarization + dielectric.

    Polarization branches (Miller et al., J. Appl. Phys. 68, 6463, 1990): ascending ``P+(E) = Ps·tanh((E -
    Ec)/2δ)``, descending ``P-(E) = Ps·tanh((E + Ec)/2δ)``, ``δ = Ec/ln((1 + Pr/Ps)/(1 - Pr/Ps))``, so the saturated
    loop has remanence ``±Pr`` and coercive field ``±Ec``; between the branches the state is kept (flat minor loops).
    Current ``I = A·dP/dt + C·dV/dt + leak_s·V`` with ``C = ε0·eps_r·A/t``; small-signal capacitance adds the
    reversible part ``k_rev·A·dP±/dV`` of the branch last travelled (C-V butterfly peaks at ``±Vc``).
    ``p_init`` is the initial polarization as a fraction of ``Ps``.
    """

    area_um2: PositiveFloat = 1.0e4
    thickness_nm: float = Field(default=10.0, gt=0.3, le=1.0e4)
    pr_uc_cm2: float = Field(default=20.0, gt=0.0, le=200.0)
    ps_uc_cm2: float = Field(default=25.0, gt=0.0, le=200.0)
    ec_mv_cm: float = Field(default=1.0, gt=0.0, le=100.0)
    eps_r: float = Field(default=30.0, gt=1.0, le=1.0e4)
    k_rev: float = Field(default=0.05, ge=0.0, le=1.0)
    leak_s: float = Field(default=0.0, ge=0.0, le=1.0)
    p_init: float = Field(default=0.0, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _pr_below_ps(self) -> FecapParams:
        if self.pr_uc_cm2 >= self.ps_uc_cm2:
            raise ValueError("pr_uc_cm2 must be below ps_uc_cm2.")
        return self


class NoiseParams(StrictModel):
    """``noise``: current noise attached to terminal ``terminal`` of device ``attach`` (no terminals of its own;
    wire it as ``{}``).

    Sampled series (``NoiseSource.sample``): white noise of rms ``white_frac`` × the measurement range (per-range
    rms); 1/f^γ noise with one-sided PSD ``flicker_k·I²/f^flicker_gamma`` (Hooge form); random telegraph noise, a
    two-state Markov trap (mean time to capture ``rtn_tau_c_s``, to emission ``rtn_tau_e_s``) lowering the current by
    ``rtn_delta_rel·I`` while occupied (Kirton & Uren, Adv. Phys. 38, 367, 1989). ``seed`` makes it deterministic.
    """

    attach: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
    terminal: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    white_frac: float = Field(default=0.0, ge=0.0, le=1.0)
    flicker_k: float = Field(default=0.0, ge=0.0, le=1.0)
    flicker_gamma: float = Field(default=1.0, ge=0.3, le=2.5)
    rtn_tau_c_s: PositiveFloat | None = None
    rtn_tau_e_s: PositiveFloat | None = None
    rtn_delta_rel: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _rtn_complete(self) -> NoiseParams:
        taus = (self.rtn_tau_c_s is None, self.rtn_tau_e_s is None)
        if taus[0] != taus[1]:
            raise ValueError("rtn_tau_c_s and rtn_tau_e_s are given together.")
        if self.rtn_delta_rel > 0 and taus[0]:
            raise ValueError("rtn_delta_rel needs rtn_tau_c_s and rtn_tau_e_s.")
        return self
