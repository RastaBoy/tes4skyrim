#!/usr/bin/env python3
"""Build the cosmetic patch plugin: outfits + hair, in one pass.

Reads the untouched plugin from `sources/`, applies every cosmetic pass in
order, and writes the result to `output/`. The build always restarts from
`sources/`, so it is reproducible: same inputs and same `--seed` give a
byte-identical plugin, and a bad run is fixed by re-running, never by undoing.

    python patch_folder/pipeline.py                 # full build
    python patch_folder/pipeline.py --dry-run       # report only, write nothing
    python patch_folder/pipeline.py --only outfits  # one pass
    python patch_folder/pipeline.py --seed 7        # different random draw

Each pass is `tools/assign_*.py`, which can also be run on its own; this script
prints the exact command it runs so a pass can be repeated or tweaked by hand.
The passes compose -- each rewrites only its own fields and carries the rest of
the record through -- so their order here is not load-bearing.
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATCH_DIR = Path(__file__).resolve().parent
SOURCES = PATCH_DIR / 'sources'
OUTPUT = PATCH_DIR / 'output'
REPORTS = PATCH_DIR / 'reports'

PLUGIN = 'MyCosmeticTamrielPatch.esp'
NPC_SOURCE = REPO / 'output' / 'Oblivion.esm' / 'Oblivion.esm'
HAIR_PLUGIN = SOURCES / "KS Hairdo's.esp"
CONSTANTS = SOURCES / 'constants.py'

# Outfit list per placement keyword; first match wins, rest get the default.
DEFAULT_OUTFITS = 'OUTFITS_TO_CHOOSE'
OUTFIT_RULES = [
    ('bruma', 'BRUMA_OUTFITS_TO_CHOOSE'),
]

# Races to leave alone even though they carry a FaceGen head, as hex FormIDs in
# the source plugin's own numbering. Empty by default.
EXCLUDE_RACES: list[str] = []


def find_skyrim_esm():
    """Skyrim.esm, needed to classify vanilla head parts. None if not found."""
    sys.path.insert(0, str(REPO))
    try:
        from asset_convert.skyrim_assets import find_skyrim_data
        candidate = Path(find_skyrim_data()) / 'Skyrim.esm'
        return candidate if candidate.exists() else None
    except Exception:
        return None


def run(step, argv, dry_run):
    print(f'\n=== {step} ' + '=' * max(3, 66 - len(step)))
    print('  ' + ' '.join(f'"{a}"' if ' ' in str(a) else str(a) for a in argv))
    print(flush=True)
    result = subprocess.run([sys.executable, *[str(a) for a in argv]], cwd=REPO)
    if result.returncode != 0:
        raise SystemExit(f'{step} failed with exit code {result.returncode}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', choices=['outfits', 'hair'], action='append',
                    default=[], help='run just this pass (repeatable)')
    ap.add_argument('--seed', type=int, default=0,
                    help='RNG seed shared by every pass (default 0)')
    ap.add_argument('--dry-run', action='store_true',
                    help='report what each pass would do, write no plugin')
    ap.add_argument('--source', default=str(NPC_SOURCE),
                    help=f'plugin the NPCs come from (default {NPC_SOURCE})')
    args = ap.parse_args()

    passes = args.only or ['outfits', 'hair']
    src_plugin = SOURCES / PLUGIN
    out_plugin = OUTPUT / PLUGIN
    npc_source = Path(args.source)

    for path in (src_plugin, CONSTANTS, npc_source):
        if not path.exists():
            raise SystemExit(f'missing input: {path}')
    if 'hair' in passes and not HAIR_PLUGIN.exists():
        raise SystemExit(f'missing input: {HAIR_PLUGIN}')

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    # A full build always restarts from sources/ so it is reproducible. A
    # partial run (--only ...) continues from output/ instead, so it keeps what
    # the other passes already wrote; delete output/ for a clean slate.
    current = src_plugin
    if args.only and out_plugin.exists():
        current = out_plugin
        print(f'partial run: continuing from {out_plugin}')
    else:
        print(f'building from {src_plugin}')

    if 'outfits' in passes:
        argv = [REPO / 'tools' / 'assign_female_outfits.py',
                '--source', npc_source,
                '--patch', current,
                '--out', out_plugin,
                '--constants', CONSTANTS,
                '--default-outfits', DEFAULT_OUTFITS,
                '--seed', args.seed,
                '--report', REPORTS / 'outfits.tsv']
        for keyword, const in OUTFIT_RULES:
            argv += ['--match-outfits', f'{keyword}={const}']
        if args.dry_run:
            argv.append('--dry-run')
        run('outfits: female NPCs get a random OTFT', argv, args.dry_run)
        if not args.dry_run:
            current = out_plugin

    if 'hair' in passes:
        argv = [REPO / 'tools' / 'assign_npc_hair.py',
                '--source', npc_source,
                '--patch', current,
                '--out', out_plugin,
                '--hair-plugin', HAIR_PLUGIN,
                '--constants', CONSTANTS,
                '--seed', args.seed,
                '--report', REPORTS / 'hair.tsv']
        skyrim = find_skyrim_esm()
        if skyrim:
            argv += ['--hdpt-from', skyrim]
        else:
            print('!! Skyrim.esm not found; vanilla head parts cannot be '
                  'classified and will be left in place. Pass --hdpt-from to '
                  'tools/assign_npc_hair.py by hand if that matters.')
        for race in EXCLUDE_RACES:
            argv += ['--exclude-race', race]
        if args.dry_run:
            argv.append('--dry-run')
        run('hair: humanoid NPCs get a random hair + its HL part', argv,
            args.dry_run)
        if not args.dry_run:
            current = out_plugin

    print('\n' + '=' * 70)
    if args.dry_run:
        print('dry run: nothing written')
    else:
        print(f'built {out_plugin}  ({out_plugin.stat().st_size:,} bytes)')
        print(f'reports in {REPORTS}')


if __name__ == '__main__':
    main()
