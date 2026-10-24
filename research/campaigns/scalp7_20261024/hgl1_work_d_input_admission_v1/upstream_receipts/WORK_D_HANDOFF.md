# Existing Work D handoff — HGL1 only

SOURCE_RULE_READY / CODE_AND_FIXTURES_READY / DATA_BINDING_BLOCKED.

This is a source compiler package, not an economic owner takeover. D branch observed: `work/zel-portfolio-coverage-20261021` at `ab71035013e226bdc9409a5f36f2f22c7cde3320`. A remains the sole official economic FULL owner. This Work ran zero market DEV/FULL, no orders, no collector, no paid API. K117 and completed KAMA/Grimes/Stage4 evidence remain unchanged. The denied57-trade ledger was not read or retried.

## Files D can consume now

- `FROZEN_SPEC.json`: one source-based long-only HGL1 version. Pre-outcome freeze commit `e1d0036f9807b231133eb2f012b603d0ff3049bb`.
- `SOURCE_RECEIPTS.json`, `SOURCE_TO_RULE.md`: actual primary URL/page/hash and exact author/ZEL distinction.
- `reference.py`: native EMA/ADX, causal first-pullback state machine and conservative fills; no market I/O.
- `input_gate.py`: original raw/normalized receipt verification via three pinned read-only source modules, isolated1h aggregation, fresh-window and tick binding. No shared-loader modification.
- `fixtures.json`, `test_*.py`: executable synthetic counterexamples. Synthetic input is not historical market input.
- `dev_runner.py`: D-only single ledger with20/40bp columns, censored position marking, frequency/concurrency/PNL/PF/DD/streak reporting. No economic command is called on import.
- `INPUT_TEMPLATE.json`: intentionally invalid until real bindings are known.

## No strategy research remains; these source bindings remain unverified

| Required item | Current result | Who supplies factual evidence |
|---|---|---|
| New immutable minute snapshot | null; not opened | Existing authorized source owner, read-only export |
| CURSOR/IDENTITY/raw/normalized SHA chain | null | D preflight verifies actual bytes |
| Source permission + independent consumption receipt | null | Existing owner; assertion is not cryptographic novelty proof |
| Predeclared DEV window and freeze ref | null | D, before observing that window's outcomes |
| Tick values and original metadata hash/effective interval | null | Authorized source snapshot |
| True historical funding/fill evidence | UNKNOWN | Not replaced by zero; DEV remains model-only |

Do not fill any of these from the retired historical corpus, donor57 rows, guessed precision or invented receipt time. If the existing source cannot provide this, keep DATA_BINDING_BLOCKED; do not start another collector or ask another interface to retrieve denied content. This source restriction affects any proposed replacement mechanism too, so adding a second strategy does not remove it.

## Exact entry points

Run from a checkout containing the final handoff commit linked in Issue1358. The Issue comment gives an immutable `HANDOFF_COMMIT`; inspect only this additive package. Keep the existing D owner, claim and source paths. No new cron/Work writer or FULL reservation is created.

```bash
P=research/campaigns/scalp7_20261024/holygrail_source_contract_v1
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s "$P" -p 'test_*.py' -v
```

The supplied template is expected to fail closed (tested exit2):

```bash
P=research/campaigns/scalp7_20261024/holygrail_source_contract_v1
TEMPLATE_SHA=$(sha256sum "$P/INPUT_TEMPLATE.json" | cut -d' ' -f1)
PYTHONDONTWRITEBYTECODE=1 python -B "$P/dev_runner.py" preflight \
  --repo-root "$PWD" --manifest "$P/INPUT_TEMPLATE.json" --input-sha256 "$TEMPLATE_SHA"
```

D completes `INPUT_BOUND.json` beside the unchanged frozen spec, using actual evidence; commits the selected source/window before DEV, then seals final captured input bytes before evaluating them. `D_INPUT_MANIFEST_SHA256` must be that exact file SHA, not the combined input digest later returned by preflight. It is not supplied here because the file does not exist.

```bash
P=research/campaigns/scalp7_20261024/holygrail_source_contract_v1
: "${D_INPUT_MANIFEST_SHA256:?exact sealed INPUT_BOUND.json SHA256 required}"
PYTHONDONTWRITEBYTECODE=1 python -B "$P/dev_runner.py" preflight \
  --repo-root "$PWD" --manifest "$P/INPUT_BOUND.json" \
  --input-sha256 "$D_INPUT_MANIFEST_SHA256"
```

Only the existing D may subsequently execute its bounded cheap screen. `D_EXISTING_CLAIM_DIR` must be its existing durable shared reservation directory and `D_NEW_RESULT_PATH` a not-yet-existing output on the authorized worker. These are factual D runtime inputs, not a newly invented owner. Directory-level `O_EXCL` prevents repetition only for processes using that same directory; it does not replace D's cross-host allocation/ownership check. The permanent candidate claim survives failure; do not delete/retry it automatically.

```bash
P=research/campaigns/scalp7_20261024/holygrail_source_contract_v1
: "${D_INPUT_MANIFEST_SHA256:?exact sealed manifest SHA required}"
: "${D_EXISTING_CLAIM_DIR:?existing D durable shared claim directory required}"
: "${D_NEW_RESULT_PATH:?new output path outside source snapshot required}"
PYTHONDONTWRITEBYTECODE=1 python -B "$P/dev_runner.py" dev \
  --repo-root "$PWD" --manifest "$P/INPUT_BOUND.json" \
  --input-sha256 "$D_INPUT_MANIFEST_SHA256" \
  --claim-dir "$D_EXISTING_CLAIM_DIR" --out "$D_NEW_RESULT_PATH"
```

One candidate, one<=31-day DEV window, one chronological ledger, two cost columns. No grid, second source window or parameter repair after outcomes. New adverse evidence closes this version rather than permitting a retry. Cost2-positive is only a candidate for separate review, never G5/Live permission. No Actions deployment should run for this package.

## Acknowledgment

Publication into the dedicated research branch and an Issue1358 handoff comment is delivery. It is NOT proof that another Work session read it. D acknowledgment, bound market-input receipt and actual market DEV execution must each be reported separately; all are pending in this packet.
