"""Shared Pydantic models (leaf package: imports only pydantic, the standard library and its own modules).

``common`` (base model, vocabularies, ``ResultEnvelope``, config-file records) · ``station`` (settings, station
profile, pin maps, sim scenarios, live state) · ``policy`` (policy, DUT profiles, hard-limit ceiling) · ``recipe`` ·
``plan`` (request, record, binding, envelope, rule reports) · ``run`` (cleanup, fault, manifest, summary) ·
``analysis`` · ``measurement`` · ``audit`` (audit event line) · ``sim`` (simulator device parameters, faults) ·
``results`` (service/tool result models).
"""
