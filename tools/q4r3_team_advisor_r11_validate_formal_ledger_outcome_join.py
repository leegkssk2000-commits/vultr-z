#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from canonical.zlice.outcome_join import read_formal_ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    result = read_formal_ledger(args.ledger)
    print(json.dumps({"rows": len(result.outcomes), "ready": result.join_ready}, sort_keys=True))
    return 0 if result.join_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
