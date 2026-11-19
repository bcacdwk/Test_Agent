"""Shared Pydantic models (leaf package: imports only pydantic, the standard library and its own modules).

``common`` (base model, vocabularies, ``ResultEnvelope``, config-file records) · ``routing`` (switches, routes) ·
``station`` (settings, station profile with switches, pin maps, correction records, sim scenarios, live state) ·
``policy`` (policy, DUT profiles, hard-limit ceiling) · ``recipe`` · ``plan`` (request, record, binding, envelopes
incl. pulse/AC/waveform, rule reports, run progress) · ``sources`` (pulse trains, WGFMU waveform programs, the
source plan of a kind's program) · ``run`` (cleanup, fault, manifest, summary) ·
``analysis`` · ``measurement`` · ``audit`` (audit event line) · ``sim`` (simulator device parameters, faults) ·
``results`` (service/tool result models) · ``manuals`` (manual catalog, corpus records, ``b1500 manual`` results) ·
``bringup`` (probe, station proposal, config bootstrap) · ``validation`` (bring-up stages, hardware validation
records, ``b1500 bringup status|capture|record`` results).
"""
