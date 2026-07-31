from __future__ import annotations

from backend.tools import strategy11_supertrend_parent_basis_v1 as parent
from backend.tools.strategy11_supertrend_fast_basis_v1 import authentic_supertrend_fast

parent.authentic_supertrend = authentic_supertrend_fast

if __name__ == "__main__":
    raise SystemExit(parent.main())
