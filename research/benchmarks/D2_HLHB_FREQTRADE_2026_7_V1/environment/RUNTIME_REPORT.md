# Freqtrade runtime installation receipt

Status: INSTALLED_AND_BACKTESTING_IMPORT_VERIFIED. Economic runs: 0. Market requests: 0.

- Isolated interpreter: `/workspace/scratch/91d255a1335a/ft-runtime/bin/python`
- Actual Freqtrade: `2026.7`. Expected upstream source: `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`.
- Official wheel SHA256: `be08e26ed0f642ce9ada8b7fcfb1ed6766dc8ef95f131650c1d3fecf419f3815`.
- Python: 3.12.13, Linux x86_64 glibc2.39. No system site packages inherited.
- All 44 applicable requirements from the exact upstream source satisfied; actual transitive dependencies frozen with downloaded artifact hashes.
- `pip check`: No broken requirements found.
- Actual `Backtesting` and `IStrategy` imports succeeded.
- 332 engine Python files exactly match the verified wheel; no engine patch.
- 10,690 installed RECORD entries verified by size and hash; zero mismatches.

## Installation issue and resolution

Initial unconstrained wheel dependency resolution selected pyarrow 25.0.1. `freqtrade --version` passed but Backtesting import failed with SIGBUS. Isolated imports located the failure at `pyarrow/__init__.py:59`. RECORD verification found `libarrow.so.2500` truncated to 30,408,704 bytes against the expected 55,368,864 bytes; other 752 pyarrow entries matched. This is evidence of an installation integrity defect, not evidence that the strategy or engine is economically invalid.

Disk and shared-memory capacity were available. A documented allocator/SIMD/thread configuration probe did not repair the corrupted file. ptrace/strace was unavailable and was not bypassed. No engine patch or unsupported dependency fallback was used.

The exact upstream source requirements pin pyarrow 25.0.0. Applying this original pin restored Backtesting import. All original upstream pins were then applied. pip left old joblib/cachetools dist-info and numpy uninstall temporary directories; only those identified residues within this newly created venv were moved to a separate scratch quarantine. The final environment passed the complete RECORD, upstream constraint and import checks.

## Reproducibility evidence

- `requirements-hashed.txt`: all installed runtime distributions except bootstrap pip, with exact version and original download SHA256.
- `pip-freeze.txt`: actual installed versions including pip.
- `pip-install-report.json`, `pip-pyarrow-upstream-pin-report.json`, `pip-upstream-requirements-report.json`: exact download provenance.
- `ENGINE_CORE_SOURCE_SHA256.json`: four engine source hashes for parent-agent commit comparison.
- `RUNTIME_VERIFICATION.json`, `UPSTREAM_PIN_VERIFICATION.json`, `FINAL_RECORD_INTEGRITY.json`: actual final verification.
- `INSTALL_COMMANDS.json`: executed installation and verification command arguments.

The companion `freqtrade-client` resolved as 2026.8; the trading engine remains exactly Freqtrade 2026.7. The client version is explicitly frozen and is not an engine fallback. No economic comparison has been run by the installation agent.
