"""Simulator units (blueprint 4.1): one mixin of ``SimInstrument`` per instrument family, FLEX handlers registered
by mnemonic with ``base.handles``. ``core`` (identity, status, buffer, format, output switches, ``AB``, A/D
converters), ``smu`` (ranging, modes, sources, the measurement engine), ``cmu`` (``CORRST?``, ``ADJ?``), ``spgu``
(the HV-SPGU, WP9.1; output engine in ``spgu_output``) and ``switch`` (``ERMOD?``, ``ERSSP?``); the family work
packages extend ``cmu`` and ``switch``. Units hold no
I/O of their own: they act on the dispatcher's shared state."""
