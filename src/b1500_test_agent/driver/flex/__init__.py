"""FLEX command builders and constants, the only home of FLEX mnemonics in string literals (blueprint 2.1, 2.5).

One module per instrument family: ``core`` (system queries, output switches, ``FMT``, ``MM``, ``XE``/``AB``/``*RST``)
and ``smu`` (``CMM``, ``AAD``/``AIT``, ``RI``/``RV``, ``WV``/``WT``/``WM``, ``DV``); later work packages add ``cmu``,
``spgu`` and ``switch``. This package re-exports every public builder and constant, so callers import the package
(``from b1500_test_agent.driver import flex``) and write ``flex.dv(...)``. Builders are pure (syntax and domain
checks only, never policy) and return one command per string.
"""

from b1500_test_agent.driver.flex.core import (
    AB,
    CAL_Q,
    ERRX_Q,
    FORMATS,
    IDN_Q,
    LOP_Q,
    LOP_RESPONSE_PREFIX,
    MAX_CHANNELS_CN_CL_DZ,
    MAX_CHANNELS_MM,
    MEASUREMENT_MODES,
    OPC_Q,
    RST,
    STB_Q,
    TST_Q,
    UNT_Q,
    XE,
    cl,
    cn,
    dz,
    fmt,
    mm,
)
from b1500_test_agent.driver.flex.smu import I_RANGE_CODES, V_RANGE_CODES, aad, ait, cmm, dv, ri, rv, wm, wt, wv

__all__ = [
    "AB",
    "CAL_Q",
    "ERRX_Q",
    "FORMATS",
    "IDN_Q",
    "I_RANGE_CODES",
    "LOP_Q",
    "LOP_RESPONSE_PREFIX",
    "MAX_CHANNELS_CN_CL_DZ",
    "MAX_CHANNELS_MM",
    "MEASUREMENT_MODES",
    "OPC_Q",
    "RST",
    "STB_Q",
    "TST_Q",
    "UNT_Q",
    "V_RANGE_CODES",
    "XE",
    "aad",
    "ait",
    "cl",
    "cmm",
    "cn",
    "dv",
    "dz",
    "fmt",
    "mm",
    "ri",
    "rv",
    "wm",
    "wt",
    "wv",
]
