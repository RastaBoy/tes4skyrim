#!/usr/bin/env python
"""Reconvert only the NIFs a change actually affects, into the real output tree.

A full ``convert.py --meshes-only`` pass is ~20,000 meshes and many minutes at
100% CPU; almost every mesh fix touches a handful of them.  This runs the SAME
code path as the mesh phase (``nif_converter._batch_worker`` -> ``convert_nif``
with the pipeline's arguments) over a named subset, writing to the same
destination the phase would, so the result is byte-identical to what a full
rebuild would have produced for those files and the user can launch the game
immediately.

Selection is by path fragment against the plugin's extracted mesh tree, or by
``--list`` file (one path or fragment per line, ``#`` comments allowed), which
is how a sweep script hands over exactly what it found.

    python tools/nif/convert_meshes_subset.py -f Oblivion.esm \
        architecture/lowerclass/doorfulllower02.nif clutter/lampsconce

    python tools/nif/convert_meshes_subset.py -f Nehrim.esm --list temp/hits.txt

``--dry-run`` prints the matched files and stops -- always worth one pass
before writing into ``output/``.  ``--out DIR`` redirects the write elsewhere
(``temp/``) when the point is to inspect rather than to ship.

Does NOT touch the textures, the mesh manifest or ``textures_used.txt``: a
mesh change that also changes which TEXTURES a mesh references needs the full
phase, because the prune runs off that manifest.  The tool says so when a
converted mesh reports a texture the manifest does not already list.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from asset_convert import nif_converter                     # noqa: E402
from output_layout import asset_root, plugin_out_root       # noqa: E402


def _select(mesh_root: Path, patterns, list_file):
    """Every NIF under *mesh_root* matching a fragment, in tree order."""
    frags = [p.replace('\\', '/').lower().lstrip('/') for p in patterns]
    if list_file:
        for line in Path(list_file).read_text(encoding='utf-8').splitlines():
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            # Sweep scripts hand over full source paths; keep only the part
            # below meshes/ so the fragment match works either way.
            norm = line.replace('\\', '/').lower()
            if '/meshes/' in norm:
                norm = norm.split('/meshes/', 1)[1]
            frags.append(norm)
    if not frags:
        return []

    hits = []
    for nif in sorted(mesh_root.rglob('*.nif')):
        rel = nif.relative_to(mesh_root)
        rel_parts = [p.lower() for p in rel.parts]
        if any(seg in rel_parts for seg in nif_converter.SKIP_PATHS):
            continue          # the mesh phase never writes these
        norm = '/'.join(rel_parts)
        if any(f in norm for f in frags):
            hits.append((nif, rel))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-f', '--file', required=True, metavar='PLUGIN',
                    help='Plugin whose extracted mesh tree to convert from '
                         '(e.g. Oblivion.esm)')
    ap.add_argument('patterns', nargs='*',
                    help='Path fragments to match (case-insensitive, / or \\)')
    ap.add_argument('--list', metavar='FILE',
                    help='File of path fragments, one per line (# comments)')
    ap.add_argument('--extract-dir', default='export')
    ap.add_argument('--output-dir', default='output')
    ap.add_argument('--out', metavar='DIR',
                    help='Write here instead of the plugin output tree')
    ap.add_argument('--workers', type=int, default=0,
                    help='0 = the mesh phase default')
    ap.add_argument('--dry-run', action='store_true',
                    help='List the matched meshes and stop')
    a = ap.parse_args(argv)

    plugin = Path(a.file).name
    mesh_root = Path(asset_root(a.extract_dir, plugin)) / 'meshes'
    if not mesh_root.is_dir():
        print(f'No extracted mesh tree at {mesh_root}')
        return 2
    if a.out:
        out_root = Path(a.out)
    else:
        out_root = Path(plugin_out_root(a.output_dir, plugin,
                                        str(a.extract_dir))) / 'meshes' / 'tes4'

    hits = _select(mesh_root, a.patterns, a.list)
    if not hits:
        print('No mesh matched.')
        return 1
    print(f'{len(hits)} mesh(es) -> {out_root}')
    for _, rel in hits:
        print(f'  {rel}')
    if a.dry_run:
        return 0

    work = [(str(nif), str(out_root / rel), True, None, str(mesh_root),
             None, False, False) for nif, rel in hits]

    workers = a.workers or nif_converter._WORKER_COUNT
    workers = max(1, min(workers, len(work)))
    results = []
    if workers > 1:
        import multiprocessing as mp
        with mp.Pool(processes=workers,
                     initializer=nif_converter._pyffi_capture_init) as pool:
            for res in pool.imap_unordered(nif_converter._batch_worker, work):
                results.append(res)
    else:
        nif_converter._pyffi_capture_init()
        results = [nif_converter._batch_worker(w) for w in work]

    converted = errors = skipped = 0
    textures = set()
    for status, nif_str, payload in results:
        name = Path(nif_str).name
        if status != 'ok':
            errors += 1
            print(f'  ERROR {name}: {payload}')
            continue
        textures.update(payload.get('textures', ()))
        if payload.get('error'):
            errors += 1
            print(f'  ERROR {name}: {payload["error"]}')
        elif payload.get('converted') or payload.get('copied'):
            converted += 1
        else:
            skipped += 1
            print(f'  SKIP  {name}: {payload.get("skip_reason", "?")}')
    print(f'\n{converted} converted, {skipped} skipped, {errors} errors')

    # The texture prune runs off textures_used.txt, which only the full phase
    # rewrites.  A subset run that pulls in a texture the manifest never saw
    # would ship a mesh whose texture the prune then deletes.
    manifest = Path(asset_root(a.extract_dir, plugin)) / 'textures_used.txt'
    if textures and manifest.is_file():
        known = {ln.strip().lower()
                 for ln in manifest.read_text(encoding='utf-8').splitlines()
                 if ln.strip()}
        new = sorted(t for t in textures if t.lower() not in known)
        if new:
            print(f'\n[warn] {len(new)} texture(s) not in {manifest.name} -- '
                  f'run the full mesh phase so the prune keeps them:')
            for t in new[:10]:
                print(f'   {t}')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
