# B1500 Driver Kernel Instructions

This subtree owns instrument-facing code. Treat all code here as safety-critical.

## Driver Constraints

- Do not build FLEX commands with ad hoc string concatenation in recipes or MCP tools.
- Put command construction behind typed builder methods with validation.
- Never combine `*RST` or `AB` with other commands in one message.
- Keep query-buffer handling separate from measurement-buffer handling.
- Prefer ASCII `FMT 1` or `FMT 5` until binary parsing is explicitly implemented and tested.

## Transaction Template

Every measurement recipe should follow this shape:

1. Validate policy and station profile.
2. Validate module capabilities and channel roles.
3. Configure format, ADC, ranges, compliance, and wait settings.
4. Enable only required channels.
5. Execute measurement.
6. Wait for completion.
7. Read errors and status.
8. Read and parse data.
9. Persist raw and parsed outputs.
10. Execute cleanup, normally `DZ` and `CL`.

## Safety-Critical Implementation Notes

- Keep cleanup in `finally` blocks or equivalent transaction guards.
- Log every outgoing command and relevant response.
- Return structured fault objects rather than opaque strings.
- Use a single execution lock per instrument session.
