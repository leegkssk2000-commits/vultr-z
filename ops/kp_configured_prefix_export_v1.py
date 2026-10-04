"""Finish the second, pre-existing configured source without rereading the main cut.

Reuses hash-verified PR1355 price export. Adds only the immutable small prefix
that the ORIGINAL forward config names. No new market requests or economics.
"""
PRIMARY_SHA = '9ae88eb5f51fa796c52f61ed51e2aec084691290baf3c5bfc85ef150926b1efb'
PREFIX_IDENTITY_SHA = '4fd19e5b8866b8ecb7a19d64d9e17711efd7e446a4faf5d5a6399acd1fd47b88'
PREFIX_START = 1789430400000


def complete_prefix(primary_raw, expected_code_hashes):
    require(sha(primary_raw) == PRIMARY_SHA, 'PRIMARY_INPUT_PIN')
    data = load(primary_raw)
    require(data['price_bodies_verified'] is True and data['market_runs'] == 0, 'PRIMARY_INPUT_PROFILE')
    require(data['deployed_code_hashes'] == expected_code_hashes, 'DEPENDENCY_PIN_CHANGED')
    config_raw, meta = saved_file(ROOT/'FRESH_FORWARD_CONFIG_V2.json')
    require(meta['sha256'] == data['config_source']['sha256'], 'ORIGINAL_CONFIG_CHANGED')
    config = load(config_raw)
    require(config['sources'] == [
        {'path': str(ROOT/'fresh_1m'), 'identity_sha256': PREFIX_IDENTITY_SHA},
        {'path': str(SOURCE_ROOT), 'identity_sha256': IDENTITY_SHA}], 'CONFIGURED_SOURCES_CHANGED')
    for path, pin in expected_code_hashes.items():
        require(sha(read_relative(TREE,path,300000)) == pin, 'DEPLOYED_CODE_CHANGED')
    before = state_census()
    prefix_root = ROOT/'fresh_1m'
    prefix = capture(prefix_root, PREFIX_IDENTITY_SHA, time_budget_s=30)
    require(all(s['start_ms'] == PREFIX_START and s['end_exclusive_ms'] == START for s in prefix['symbols']), 'PREFIX_BOUNDARY_NOT_EXACT')
    prefix_rows = {s: [] for s in SYMBOLS}
    count = 0
    for i, old in enumerate(prefix['receipt_metadata']):
        receipt_raw = read_relative(prefix_root, old['receipt_path'], 262144)
        require(sha(receipt_raw) == old['receipt_sha256'], 'PREFIX_RECEIPT_CHANGED')
        receipt = load(receipt_raw)
        raw = read_relative(prefix_root,receipt['body_path'],1024*1024)
        normal = read_relative(prefix_root,receipt['normalized_path'],1024*1024)
        require(sha(raw) == old['body_sha256'] and sha(normal) == old['normalized_sha256'], 'PREFIX_BODY_HASH')
        rows, csv_bytes = normalize_body(raw,receipt)
        require(bounded_gunzip(normal,8*1024*1024) == csv_bytes, 'PREFIX_NORMALIZATION')
        for row in rows:
            prefix_rows[old['symbol']].append([row[k] for k in FIELDS]+[receipt['received_at_ms'],i,0])
        count += len(rows)
    for symbol in SYMBOLS:
        combined = prefix_rows[symbol] + [row+[1] for row in data['minutes'][symbol]]
        require([row[0] for row in combined] == list(range(PREFIX_START,COMMON_END,60000)), 'CONFIGURED_UNION_GAP_OR_OVERLAP')
        data['minutes'][symbol] = combined
    data.update(configured_sources_verified=True, source_start_ms=PREFIX_START,
                fields=data['fields']+['source_namespace'], prefix_snapshot=prefix,
                prefix_raw_rows_verified=count, prefix_receipts_verified=prefix['receipt_metadata_verified'],
                primary_input_sha256=PRIMARY_SHA, primary_source_start_ms=START,
                prefix_before=before, prefix_after=state_census(),
                configured_source_namespaces={'0':str(prefix_root),'1':str(SOURCE_ROOT)})
    return data


if __name__ == '__main__':
    payload = bounded_gunzip(base64.b64decode(KP_INPUT_B64,validate=True),64*1024*1024)
    try:
        result = complete_prefix(payload,KP_EXPECTED_CODE_HASHES)
        with gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb',mtime=0) as output:
            output.write(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
    except Exception as exc:
        print('KP_BODY_EXPORT_REJECTED:'+type(exc).__name__+':'+str(exc)[:250],file=sys.stderr)
        raise
