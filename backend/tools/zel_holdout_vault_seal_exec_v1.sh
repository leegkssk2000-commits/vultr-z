#!/usr/bin/env bash
set -euo pipefail
IFS= read -r ZEL_HOLDOUT_HMAC_KEY
test -n "$ZEL_HOLDOUT_HMAC_KEY"
export ZEL_HOLDOUT_HMAC_KEY
python3 /tmp/zel_holdout_vault_seal_runner_v1.py "$@"
unset ZEL_HOLDOUT_HMAC_KEY
