# Q4R3 R0 Result States

- `PASS`: all 12 canonical owners proven and every R0 exit criterion satisfied.
- `HOLD`: audit completed but one or more owners, wrappers, mappings, or classifications remain unresolved.
- `FAIL`: audit integrity failed, runtime safety verification failed, or evidence could not be produced.

`HOLD` is the expected state when the system contains real ambiguity. It is not converted to PASS by scoring heuristics.
