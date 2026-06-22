# HSPICE Integration Notes

HSPICE is not part of the initial implementation, but the repository reserves space for simulation-assisted analysis.

Future workflow:

1. Extract device parameters from measured IV/CV data.
2. Generate a simple SPICE netlist.
3. Run HSPICE or a compatible simulator when available.
4. Parse simulated curves.
5. Compare measured and simulated data.
6. Feed mismatch back into measurement planning.

Keep simulator invocation optional and external to core instrument safety logic.
