# Q4R3 TB-1.1 classifier binding root cause

## Exact failure

The fixed wrapper defined a corrected `classify_kind`, then executed:

```python
for _name in dir(_original):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_original, _name)
```

That loop copied the original module's `classify_kind` back into the wrapper global namespace and overwrote the corrected function. The subsequent line:

```python
_original.classify_kind = classify_kind
```

therefore rebound the original module to its own defective classifier, not to the fixed classifier. This is why pytest temporary ancestors were still classified by the old path-wide regex.

## Eradication

- fixed function renamed `_fixed_classify_kind`
- original re-export explicitly excludes `classify_kind` and `main`
- both bindings are asserted:
  - wrapper `classify_kind is _fixed_classify_kind`
  - original module `classify_kind is _fixed_classify_kind`
- support directories must be exact `test/tests/script/scripts`
- support prefixes are evaluated only on the final basename
- all ten support prefixes are tested as ancestor names and must remain `runtime_definition`
- actual support directory and final-basename cases must remain `support_verifier_installer`

No runtime unit or ZEL data surface is changed by this classifier repair.
