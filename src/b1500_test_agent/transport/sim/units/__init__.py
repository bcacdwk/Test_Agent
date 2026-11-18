"""Simulator units (blueprint 4.1): one mixin of ``SimInstrument`` per instrument family, FLEX handlers registered
by mnemonic with ``base.handles``. ``core`` (identity, status, buffer, format, output switches, ``AB``, A/D
converters) and ``smu`` (ranging, modes, sources, the measurement engine); later work packages add ``cmu``,
``spgu`` and ``switch``. Units hold no I/O of their own: they act on the dispatcher's shared state."""
