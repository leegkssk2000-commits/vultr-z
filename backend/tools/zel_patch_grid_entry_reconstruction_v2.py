from pathlib import Path

path=Path('backend/tools/zel_grid_entry_regime_reconstruction_v1.py')
text=path.read_text(encoding='utf-8')
replacements=[
(
'''    engine = load_module(args.engine, "zel_entry_regime_engine")
    producer = engine.import_producer(source_root)
    producer_path = Path(inspect.getsourcefile(producer) or getattr(producer, "__file__", ""))
    manifest_result = engine.validate_data_manifest(args.data_root, "1m")
    manifest = manifest_result[0] if isinstance(manifest_result, tuple) else manifest_result
''',
'''    engine = load_module(args.engine, "zel_entry_regime_engine")
    engine.worker_init(source_root, args.data_root, "1m")
    producer = engine._WORKER_PRODUCER
    producer_path = Path(inspect.getsourcefile(producer) or getattr(producer, "__file__", ""))
    manifest = engine._WORKER_MANIFEST
'''),
(
'''    if len(files) != 15:
        blockers.append("DATA_FILE_COUNT_MISMATCH")
''',
'''    if frame_count != len(grouped):
        blockers.append("USED_LANE_FRAME_COUNT_MISMATCH")
'''),
(
'''        "data_file_count": len(files),
        "loaded_frame_count": frame_count,
''',
'''        "data_file_count": len(files),
        "used_lane_count": len(grouped),
        "loaded_frame_count": frame_count,
'''),
]
for old,new in replacements:
    count=text.count(old)
    if count==0 and new in text:
        continue
    if count!=1:
        raise RuntimeError(f'PATCH_MATCH_COUNT_{count}:{old[:40]}')
    text=text.replace(old,new,1)
path.write_text(text,encoding='utf-8')
