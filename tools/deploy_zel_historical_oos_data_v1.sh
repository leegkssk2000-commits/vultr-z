#!/usr/bin/env bash
set -Eeuo pipefail

ARCHIVE="${1:?archive path required}"
SHA_FILE="${2:?sha file required}"
ACTIVE_ROOT="${3:-/opt/zel/historical-oos-v1}"
RESULT_PATH="${4:-/tmp/zel_historical_oos_data_deploy_result.json}"
PYTHON="/home/z/z/.venv/bin/python"

[[ -f "${ARCHIVE}" ]] || { echo "ARCHIVE_MISSING" >&2; exit 1; }
[[ -f "${SHA_FILE}" ]] || { echo "SHA_FILE_MISSING" >&2; exit 1; }
[[ -x "${PYTHON}" ]] || { echo "PYTHON_MISSING" >&2; exit 1; }

archive_dir="$(dirname "${ARCHIVE}")"
archive_name="$(basename "${ARCHIVE}")"
sha_name="$(basename "${SHA_FILE}")"
(
  cd "${archive_dir}"
  sed "s#${ARCHIVE}#${archive_name}#g" "${sha_name}" | sha256sum -c -
)

stamp="$(date -u +%Y%m%dT%H%M%SZ).$$"
staging="${ACTIVE_ROOT}.staging.${stamp}"
backup="${ACTIVE_ROOT}.rollback.${stamp}"
rm -rf "${staging}"
mkdir -p "${staging}"
tar -xzf "${ARCHIVE}" -C "${staging}" --strip-components=1

"${PYTHON}" - "${staging}" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
manifest_path=root/'manifest.json'
assert manifest_path.is_file(),manifest_path
d=json.loads(manifest_path.read_text())
assert d['state']=='PASS_HISTORICAL_OOS_DATA_READY',d
assert d['total_market_rows']==302400,d
assert d['window_count']==6,d
assert d['forward_overlap_count']==0,d
assert d['final_holdout_accessed'] is False,d
assert d['historical_data_is_promotion_authority'] is False,d
assert d['promotion_authority'] is False,d
assert d['execution_authority']=='NONE',d
assert d['order_authority']=='BLOCKED',d
for row in d['files']:
    path=root/row['path']
    assert path.is_file(),path
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest==row['sha256'],(path,digest,row['sha256'])
PY

if [[ -d "${ACTIVE_ROOT}" ]]; then
  rm -rf "${backup}"
  mv "${ACTIVE_ROOT}" "${backup}"
fi
mv "${staging}" "${ACTIVE_ROOT}"

"${PYTHON}" - "${ACTIVE_ROOT}" "${backup}" "${RESULT_PATH}" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1]); backup=sys.argv[2]; out=Path(sys.argv[3])
d=json.loads((root/'manifest.json').read_text())
payload={
  'schema_version':'zel.historical_oos_data.deploy.result.v1',
  'state':'PASS',
  'verdict':'HISTORICAL_OOS_DATA_ATOMICALLY_INSTALLED',
  'generated_at':datetime.now(timezone.utc).isoformat(),
  'active_root':str(root),
  'rollback_root':backup if Path(backup).exists() else None,
  'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
  'total_market_rows':d['total_market_rows'],
  'window_count':d['window_count'],
  'symbol_count':len(d['symbols']),
  'forward_overlap_count':d['forward_overlap_count'],
  'promotion_authority':False,
  'execution_authority':'NONE',
  'order_authority':'BLOCKED',
  'action':'hold',
}
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
print(json.dumps(payload,sort_keys=True))
PY
