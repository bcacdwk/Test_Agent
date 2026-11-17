---
id: visa-no-connection
title: No VISA connection to the B1500A
maturity: seed
sources: [config/settings.example.yaml (visa block), transport/visa.py, blueprint 9.7 ATV-2 and ATV-3]
---

# No VISA connection

## Symptom

- Tool results with status `error` and `transport_error`: "Cannot load VISA library", "pyvisa is not installed",
  "`<action>` on GPIB0::17::INSTR failed: ...", or a timeout.
- `station_status` shows no identity or module list on backend `visa`.

On backend `sim` there is no VISA: a `transport_error` there comes from a simulated fault profile (for example a
disconnect or timeout in the scenario) or is a bug. Report it; nothing physical to check.

## Likely causes

1. Instrument off, still booting, or held by EasyEXPERT (it must release the instrument for external control;
   ATV-3, checked at hardware bring-up).
2. Wrong resource string or GPIB address (factory default 17; ATV-2) in the human's `config/local/settings.yaml`.
3. VISA library missing or the wrong one (`visa.library` empty means the vendor stack); two VISA stacks installed.
4. GPIB cable or USB-GPIB adapter loose; adapter not seen by the vendor connection tool.
5. Another program has an exclusive VISA lock on the resource.

A different process holding the instrument lock gives `busy` with the holder, not `transport_error`.

## First safe checks

1. `station_status`: backend, resource, config problems, lock holder, fault latch.
2. `uv run b1500 doctor` and `uv run b1500 config check` (read-only): Python, imports, config validity, data dir.
3. Read the exact error text; it names the step that failed (library, open, write, read).
4. A run in progress when the link dropped could not verify its cleanup, so the fault latch is set; a
   `safe_shutdown` without a link latches it too (fail safe). Continue with
   [cleanup-failed-fault](cleanup-failed-fault.md) once the link is back.

## Physical checks to ask the human

- Is the B1500A powered and past its boot screen? Has EasyEXPERT released the instrument for external control?
- Is the GPIB cable seated at both ends; does the vendor connection tool (Keysight Connection Expert or NI MAX)
  list the instrument at the expected address?
- Is the address on the instrument the one in their `config/local/settings.yaml`?

## Do not

- Edit `config/local/settings.yaml` or switch the backend; the human edits their config.
- Write or run your own PyVISA script to "test the connection", or install drivers.
- Retry in a tight loop; one retry after the human answers is enough.

## Stop and call safe_shutdown

- The link dropped during a run: the instrument may still hold outputs, so the human checks the front panel
  first; call `safe_shutdown` once the link is back.
- The error persists after the human's checks: hand over with the exact error text and `b1500 doctor` output.
