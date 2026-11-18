"""MFCMU operations (blueprint v2 2.5).

``CmuOps`` is a mixin of ``B1500Driver``. WP6.1 adds the correction-state queries that the bring-up probe and rule
R-CORR-01's pre-execute check read (``CORRST?`` per data-correction function, ``ADJ? ch,0`` for the last phase
compensation result); the guarded AC/DC setup (``OutputGuard.check_ac``), the measurements and the correction
measurements arrive with the CMU work packages (M8). Queries need no guard.
"""

from __future__ import annotations

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.discovery import parse_adj, parse_corrst
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.station import CmuCorrectionLive, CorrectionFunction


class CmuOps(DriverBase):
    """MFCMU queries (A group of the CMU family)."""

    def correction_enabled(self, ch: int, corr: CorrectionFunction) -> bool:
        """``CORRST? ch,corr`` -> whether the open, short or load correction function is ON (PG PDF 388)."""
        return parse_corrst(self._query(flex.corrst_q(ch, corr)))

    def phase_compensation_result(self, ch: int) -> int:
        """``ADJ? ch,0`` -> the result of the last phase compensation without measuring (PG PDF 355-356): 0
        completed, 1 failed, 2 aborted, 3 not performed (``flex.ADJ_RESULTS``). Never sends mode 1, which measures
        for about 30 s and resets the MFCMU."""
        return parse_adj(self._query(flex.adj_q(ch, flex.ADJ_READ_LAST)))

    def correction_state(self, ch: int) -> CmuCorrectionLive:
        """``CORRST?`` for open, short and load, then ``ADJ? ch,0``: the live correction state of one MFCMU
        (``phase`` = the last phase compensation completed)."""
        corr_state = {corr: self.correction_enabled(ch, corr) for corr in flex.CORRECTION_CODES}
        return CmuCorrectionLive(corr_state=corr_state, phase=self.phase_compensation_result(ch) == 0)
