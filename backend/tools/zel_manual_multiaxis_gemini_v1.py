from __future__ import annotations

# Compatibility entrypoint. The canonical implementation analyzes each public
# video independently, quarantines provider-invalid sources, and aggregates only
# source-bound receipts before producing bounded hypotheses.
from backend.tools.zel_manual_multiaxis_gemini_v2 import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
