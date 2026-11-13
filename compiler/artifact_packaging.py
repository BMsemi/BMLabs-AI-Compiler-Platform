"""Lossless storage for large generated diagnostics, including failed builds."""
import gzip
import hashlib
import json
import shutil


def compress_diagnostics(work, threshold=4 * 1024 * 1024):
    records = {}
    for name in ('synthesized.json', 'model_aig.json', 'synthesized_aig.json', 'netlist.vvp'):
        path = work/name
        if not path.is_file() or path.stat().st_size <= threshold:
            continue
        compressed = work/(name+'.gz')
        if compressed.exists():
            raise ValueError(f'Refusing to replace existing diagnostic archive: {compressed}')
        with path.open('rb') as stream:
            original_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        with path.open('rb') as source, gzip.open(compressed, 'wb', compresslevel=6) as target:
            shutil.copyfileobj(source, target, length=1024*1024)
        with gzip.open(compressed, 'rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != original_hash:
                raise ValueError(f'Lossless diagnostic verification failed: {compressed}')
        records[name] = {'artifact': compressed.name, 'uncompressed_bytes': path.stat().st_size,
                         'uncompressed_sha256': original_hash, 'compression': 'gzip', 'verified': True}
        path.unlink()
    if records:
        (work/'diagnostic_archives.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    return records
