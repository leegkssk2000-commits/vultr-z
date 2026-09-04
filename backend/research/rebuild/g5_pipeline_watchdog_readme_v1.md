# G5 Pipeline Watchdog V1

Purpose: make every zero-closed-T state attributable to one pipeline stage instead of reporting generic WAIT.

Decision classes:
- SIGNAL_STARVATION
- ADMISSION_REJECTING_ALL_RAW_SIGNALS
- ACTIONABLE_SIGNAL_NOT_OPENED
- SIGNAL_LIVE_MATURING
- CLOSED_CANDIDATE_WAITING_SETTLEMENT_OR_WRITER
- ECONOMIC_EVIDENCE_NEGATIVE
- ECONOMIC_EVIDENCE_ACCUMULATING
- UPSTREAM_SIGNAL_STARVATION
- PROVENANCE_OR_WRITER_PATH_REVIEW_REQUIRED
- BBO_CAPTURE_GAP_UNOBSERVABLE

This is observer-only. It cannot mutate strategy, RR/exit, selection, promotion, execution, order, live, or G6 authority.
