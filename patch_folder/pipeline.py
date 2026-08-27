#!/usr/bin/env python3
"""Build the cosmetic patch. A thin shim over tools/patch/build_patch.py.

The build itself moved to `tools/patch/build_patch.py`, which drives all three
patches (cosmetic, creatures, horses) through one pipeline and is what the GUI's
Patches section calls. Two copies of "assemble a patch ESP" would drift, so this
file only survives as the short command the docs have always named.

    python patch_folder/pipeline.py                          # every converted plugin
    python patch_folder/pipeline.py -f Oblivion.esm           # just this one
    python patch_folder/pipeline.py --seed 7                  # a different draw
    python patch_folder/pipeline.py --dry-run

For the creature and horse patches, or to skip the zip, call the driver:

    python tools/patch/build_patch.py --patch creatures --plugins Oblivion.esm
    python tools/patch/build_patch.py --list
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DRIVER = REPO / 'tools' / 'patch' / 'build_patch.py'


def converted_plugins(output_dir):
    """Every converted plugin under `output_dir`, masters first.

    Same ordering rule the GUI panel uses: a patch has to declare a master
    before the plugin resting on it, because the index IS the FormID high byte.
    """
    from asset_convert.sibling_lod import converted_plugins as scan
    from tools.esm.make_master import read_header, resolve
    names = sorted(scan(Path(output_dir)))

    def masters_of(name):
        try:
            _flags, masters = read_header(resolve(name, str(output_dir)))
            return [m for m in masters if m in set(names)]
        except Exception:
            return []

    ordered, seen = [], set()

    def visit(name, stack=()):
        if name in seen or name in stack:
            return
        for master in masters_of(name):
            visit(master, stack + (name,))
        seen.add(name)
        ordered.append(name)

    for name in names:
        visit(name)
    return ordered


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-f', '--plugin', action='append', dest='plugins',
                    default=[], metavar='PLUGIN',
                    help='converted plugin to cover; repeatable. Default: all')
    ap.add_argument('--output-dir', default=str(REPO / 'output'))
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--no-zip', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    plugins = args.plugins or converted_plugins(args.output_dir)
    if not plugins:
        print(f'nothing converted in {args.output_dir} -- convert a plugin first')
        return 1

    argv = [sys.executable, '-u', str(DRIVER), '--patch', 'cosmetic',
            '--plugins'] + plugins + [
            '--output-dir', args.output_dir, '--seed', str(args.seed)]
    if args.no_zip:
        argv.append('--no-zip')
    if args.dry_run:
        argv.append('--dry-run')
    return subprocess.run(argv, cwd=str(REPO)).returncode


if __name__ == '__main__':
    sys.exit(main())
