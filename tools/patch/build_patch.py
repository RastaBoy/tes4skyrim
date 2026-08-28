#!/usr/bin/env python3
"""Build one patch ESP for the converted plugins, and zip it for install.

Three patches, one pipeline. Every one of them takes the same two inputs -- WHICH
patch, and WHICH converted plugins to pull in -- builds an override ESP against
exactly the masters it turns out to need, and wraps it the way every other
converted mod is wrapped (`output/Finished Mods/<name>.zip`, archive root = the
Data folder).

    python tools/patch/build_patch.py --patch cosmetic  --plugins Oblivion.esm
    python tools/patch/build_patch.py --patch creatures --plugins Oblivion.esm ElsweyrAnequina.esp
    python tools/patch/build_patch.py --patch horses    --plugins Oblivion.esm --no-zip
    python tools/patch/build_patch.py --list

| patch       | plugin                            | what it changes                |
|-------------|-----------------------------------|--------------------------------|
| `cosmetic`  | MyOwnTamrielCosmeticPatch.esp     | NPC outfits, hair, skin tone   |
| `creatures` | MyOwnTamrielCreaturePatch.esp     | creature races (no mounts)     |
| `horses`    | MyOwnTamrielHorsePatch.esp        | mounts: race, coat, saddle     |

Mounts are their own plugin because a rideable horse is the change a player
notices first, and it should be installable without also replacing 900 other
creatures.

WHY THE MASTER LIST IS COMPUTED
-------------------------------
The old cosmetic build started from a hand-authored ESP whose six masters were
fixed, so it only ever worked for one selection of plugins. Here the master list
is assembled from what the finished records actually reference -- tick only
Oblivion.esm and the creature patch masters `Skyrim.esm, Dawnguard.esm,
Dragonborn.esm, ccbgssse025-advdsgs.esm, Oblivion.esm` and nothing else. A patch
that masters a DLC it never uses simply fails to load for everyone without it.
"""

import argparse
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from output_layout import finished_dir                       # noqa: E402
from tools.patch.patch_builder import (                      # noqa: E402
    PatchPlugin, locate_plugin, order_masters, remap_record,
)
from tools.patch.plugin_patch import Patch, read_masters     # noqa: E402
from tools.patch.assign_creatures import CLONE_KEEP, find_converted  # noqa: E402
from tools.patch.patch_builder import FORMID_FIELDS, PLAIN_FIELDS  # noqa: E402

PATCH_DIR = REPO / 'patch_folder'
SOURCES = PATCH_DIR / 'sources'
OUT_DIR = PATCH_DIR / 'output'
REPORTS = PATCH_DIR / 'reports'

# The hand-authored ESP the cosmetic patch takes its own OTFT records from.
# Only its OWN records are carried; its fixed master list is discarded.
COSMETIC_TEMPLATE = SOURCES / 'MyCosmeticTamrielPatch.esp'
HAIR_PLUGIN = SOURCES / "KS Hairdo's.esp"
APACHII = 'Apachii_DivineEleganceStore.esm'
CONSTANTS = SOURCES / 'constants.py'

# The ship patch ships a replacement for one of Sailable Ship's own compiled
# scripts. It has to reach the game as a LOOSE file under Data/Scripts/, which
# is what wins over the copy in the mod's BSA.
SHIP_PLUGIN = 'Sailable Ship.esm'
SHIP_SCRIPT_DIR = 'ship_scripts'
EXTRA_FILES = {
    'ship': [(OUT_DIR / SHIP_SCRIPT_DIR / 'aaaShipUtilityScript.pex',
              'Scripts/aaaShipUtilityScript.pex'),
             # Skyrim reads Data/<plugin>.ini for every plugin it loads. This
             # one carries bBorderRegionsEnabled=0, without which Skyrim's
             # border wall stands between the player and every sea gate.
             (OUT_DIR / 'MyOwnTamrielShipPatch.ini',
              'MyOwnTamrielShipPatch.ini')],
}

PATCHES = {
    'cosmetic':  ('MyOwnTamrielCosmeticPatch.esp',
                  'NPC outfits, hair and skin tone'),
    'creatures': ('MyOwnTamrielCreaturePatch.esp',
                  'vanilla Skyrim creatures, and the removals'),
    'horses':    ('MyOwnTamrielHorsePatch.esp',
                  'mounts: vanilla horse race, coat and saddle'),
    'ineed':     ('MyOwnTamrieliNeedPatch.esp',
                  'Oblivion food and drink for iNeed, and who refills water'),
    'ship':      ('MyOwnTamrielShipPatch.esp',
                  'Sailable Ship: the Cyrodiil sea route lands in OUR Cyrodiil'),
}

# Patches whose records a later patch has to CARRY THROUGH, in load order.
# Two plugins that override the same record do not merge -- the later one wins
# the whole record -- so a patch built over actors an earlier patch already
# restyled must copy the earlier patch's version and master it. The iNeed
# patch and the cosmetic patch share 220 merchants; before this, whichever
# loaded second erased the other's work on all of them.
STACK_ON = {
    'ineed': ['MyOwnTamrielCosmeticPatch.esp',
              'MyOwnTamrielCreaturePatch.esp',
              'MyOwnTamrielHorsePatch.esp'],
}

# Subrecords each patch is allowed to change. The ship gate proves every OTHER
# field survived the copy byte-identically, so this list is the contract.
# The creature patch CLONES the vanilla actor, so it owns every field except
# the handful kept from the converted record -- and the gate's job flips from
# "prove the swap touched little" to "prove it kept exactly those". The horse
# patch stays on the narrower shell swap, because horses already work in game
# and there is no reason to hand them vanilla stats as well.
_ALL_NPC_FIELDS = (set(FORMID_FIELDS['NPC_']) | set(PLAIN_FIELDS['NPC_'])
                   | {'VMAD'})
OWNED_FIELDS = {
    'cosmetic':  'DOFT,PNAM,QNAM',
    'creatures': ','.join(sorted(_ALL_NPC_FIELDS - set(CLONE_KEEP))),
    'horses':    'RNAM,WNAM,ATKR,VTCK,ZNAM,CNAM,DPLT,DOFT,KSIZ,KWDA',
    # The iNeed patch APPENDS a faction and the vendor base stock to an actor;
    # everything else about the record has to come through untouched.
    'ineed':     'SNAM,CNTO,COCT',
    # The ship patch rewrites three script properties on ONE placed reference;
    # VMAD is the only subrecord it may touch. assign_ship_port.py checks the
    # property values themselves, which the NPC-shaped gate cannot.
    'ship':      'VMAD',
}

# Outfit list per placement keyword; first match wins, rest get the default.
DEFAULT_OUTFITS = 'OUTFITS_TO_CHOOSE'
OUTFIT_RULES = [('bruma', 'BRUMA_OUTFITS_TO_CHOOSE')]
# Outfit list per NPC-identity keyword -- her EditorID/name, her class, or any
# faction she belongs to. Checked BEFORE the placement rules and before the
# per-source default, because a bandit is a bandit wherever she camps and
# whichever plugin she came from.
OUTFIT_NPC_RULES = [('bandit', 'FEMALE_BANDITS_OUTFITS')]
# Per-source default, for a plugin whose NPCs should not wear the Tamriel set.
# ELSW_OUTFITS_TO_CHOOSE has existed in constants.py unused since the cosmetic
# patch could only ever read one source plugin; now that a build covers several,
# it is reachable.
SOURCE_OUTFITS = {'ElsweyrAnequina.esp': 'ELSW_OUTFITS_TO_CHOOSE'}
# Races to leave alone even though they carry a FaceGen head, by RACE EditorID
# (an 8-digit FormID also works). The beast races wear their hair as part of the
# head mesh -- horns, mane, spines -- so a KS Hairdo's style on one of them is a
# human wig on a lizard. Both converted plugins put every beast NPC on the
# VANILLA Skyrim race (measured 2026-08-28: ArgonianRace 00013740, KhajiitRace
# 00013745; Elsweyr's own TES4ANQ* races are all creatures with no FaceGen
# head), so naming the two vanilla records covers every source plugin.
EXCLUDE_RACES: list = ['ArgonianRace', 'KhajiitRace']


def find_skyrim_esm():
    """Skyrim.esm, so the hair pass can classify vanilla head parts."""
    try:
        from asset_convert.skyrim_assets import find_skyrim_data
        candidate = Path(find_skyrim_data()) / 'Skyrim.esm'
        return candidate if candidate.exists() else None
    except Exception:
        return None


def run(step, argv, dry_run):
    print(f'\n=== {step} ' + '=' * max(3, 66 - len(step)))
    print('  ' + ' '.join(f'"{a}"' if ' ' in str(a) else str(a) for a in argv))
    if dry_run:
        argv = list(argv) + ['--dry-run']
    result = subprocess.run([sys.executable, '-u'] + [str(a) for a in argv],
                            cwd=str(REPO))
    if result.returncode != 0:
        raise SystemExit(f'{step} failed (exit {result.returncode})')


# ---------------------------------------------------------------------------
# The cosmetic seed
# ---------------------------------------------------------------------------

def cosmetic_masters(plugins, output_dir):
    """Masters the cosmetic patch needs, in load order.

    Apachii supplies the armor its OTFT records list, KS Hairdo's the head
    parts, and each converted plugin brings its own masters with it.
    """
    names = ['Skyrim.esm', APACHII]
    for plugin in plugins:
        path = find_converted(str(output_dir), plugin)
        if path is None:
            raise SystemExit(f'{plugin} is not built in {output_dir} -- convert '
                             'it first')
        names += read_masters(Path(path).read_bytes()[:4096])
        names.append(plugin)
    names.append(HAIR_PLUGIN.name)
    return order_masters(names, lambda n: locate_plugin(n, output_dir))


def build_cosmetic_seed(plugins, output_dir, out_path):
    """Write the empty cosmetic patch: right masters, its own OTFT records.

    The template's CELL and WRLD entries are deliberately NOT carried. They are
    unmodified overrides that change nothing, and keeping them would force the
    patch to master plugins it otherwise has no reason to touch.
    """
    masters = cosmetic_masters(plugins, output_dir)
    patch = PatchPlugin(masters, description='Cosmetic patch for the converted '
                                             'Oblivion NPCs')
    template = Patch(COSMETIC_TEMPLATE)
    own = len(template.masters)
    mapping = {i: patch.master_index(n) for i, n in enumerate(template.masters)
               if n.lower() in patch.index}
    # The template's own records move into the patch's own index.
    mapping[own] = patch.own_index
    carried = 0
    for fid, (header, subs) in template.records_of('OTFT').items():
        if (fid >> 24) != own:
            continue        # an override of someone else's outfit; not ours
        patch.add('OTFT', *_carry('OTFT', fid, header, subs, mapping))
        carried += 1
    size, records, groups = patch.write(out_path)
    print(f'  seed: {carried} OTFT, masters {", ".join(masters)}')
    print(f'  {out_path} ({size:,} bytes)')
    return patch


def _carry(sig, fid, header, subs, mapping):
    header, subs = remap_record(sig, header, subs, mapping)
    return struct.unpack_from('<I', header, 12)[0], header, subs


def build_cosmetic(plugins, output_dir, out_path, seed, dry_run):
    if not COSMETIC_TEMPLATE.is_file():
        raise SystemExit(f'{COSMETIC_TEMPLATE} is missing -- it supplies the '
                         'outfit records the patch assigns')
    # The passes need a real file to read, and the seed that starts them is an
    # EMPTY patch -- so it is built beside the real one and moved into place
    # only once every pass has succeeded. A pass that aborts (a constants list
    # naming an OTFT the template does not carry, say) then leaves the last
    # good patch where it was instead of replacing it with a 1 KB stub.
    final = Path(out_path)
    out_path = final.with_suffix('.dryrun.esp' if dry_run else '.building.esp')
    print('\n=== seed ' + '=' * 61)
    build_cosmetic_seed(plugins, output_dir, out_path)
    REPORTS.mkdir(parents=True, exist_ok=True)
    skyrim = find_skyrim_esm()

    try:
        for plugin in plugins:
            source = find_converted(str(output_dir), plugin)
            tag = plugin.replace('.', '_')

            argv = [PATCH_DIR.parent / 'tools' / 'patch' / 'assign_female_outfits.py',
                    '--source', source, '--patch', out_path, '--out', out_path,
                    '--constants', CONSTANTS, '--default-outfits',
                    SOURCE_OUTFITS.get(plugin, DEFAULT_OUTFITS),
                    '--seed', seed, '--report', REPORTS / f'outfits_{tag}.tsv']
            for keyword, listname in OUTFIT_RULES:
                argv += ['--match-outfits', f'{keyword}={listname}']
            for keyword, listname in OUTFIT_NPC_RULES:
                argv += ['--match-npc-outfits', f'{keyword}={listname}']
            if OUTFIT_NPC_RULES:
                # Every selected plugin, in load order: the factions an
                # NPC belongs to usually live in a MASTER, not in the
                # plugin she is declared in.
                for other in plugins:
                    argv += ['--names-from', find_converted(str(output_dir), other)]
            run(f'outfits: {plugin}', argv, dry_run)

            argv = [PATCH_DIR.parent / 'tools' / 'patch' / 'assign_npc_hair.py',
                    '--source', source, '--patch', out_path, '--out', out_path,
                    '--hair-plugin', HAIR_PLUGIN, '--constants', CONSTANTS,
                    '--seed', seed, '--report', REPORTS / f'hair_{tag}.tsv']
            if skyrim:
                argv += ['--hdpt-from', skyrim]
            for race in EXCLUDE_RACES:
                argv += ['--exclude-race', race]
            run(f'hair: {plugin}', argv, dry_run)

            argv = [PATCH_DIR.parent / 'tools' / 'patch' / 'assign_skin_tone.py',
                    '--source', source, '--patch', out_path, '--out', out_path,
                    '--report', REPORTS / f'skin_{tag}.tsv']
            if skyrim:
                argv += ['--race-plugin', skyrim]
            run(f'skin tone: {plugin}', argv, dry_run)

    except BaseException:
        # A pass aborted: take the half-built scratch with it.
        Path(out_path).unlink(missing_ok=True)
        raise

    if dry_run:
        Path(out_path).unlink(missing_ok=True)
    else:
        os.replace(out_path, final)


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def _patch_masters(esp_path):
    with open(esp_path, 'rb') as fh:
        return read_masters(fh.read(8192))


def verify(patch_key, plugins, output_dir, esp_path):
    """Run the ship gate. A patch that fails structural checks is not zipped."""
    argv = [REPO / 'tools' / 'patch' / 'verify_npc_patch.py',
            '--patch', esp_path, '--owns', OWNED_FIELDS[patch_key]]
    if patch_key == 'ship':
        # The ship patch overrides Sailable Ship's records, not the converted
        # plugin's, so that is the file its fidelity is measured against. Its
        # own pass already checked the route values themselves.
        argv += ['--source', locate_plugin(SHIP_PLUGIN, output_dir)]
    else:
        for plugin in plugins:
            argv += ['--source', find_converted(str(output_dir), plugin)]
        # A record carried out of an earlier patch is measured against THAT
        # patch, not against the converted master it no longer matches. The
        # later --source wins, which is the same rule the game applies.
        for other in STACK_ON.get(patch_key, ()):
            if other.lower() in [m.lower() for m in _patch_masters(esp_path)]:
                argv += ['--source', OUT_DIR / other]
    # Outfits can come from any vanilla master the patch lists -- the horse
    # patch assigns Skyrim.esm's HorseSaddleOutfit, and a cloned elytra brings
    # one from the Creation Club plugin.
    skyrim = find_skyrim_esm()
    if skyrim:
        for master in _patch_masters(esp_path):
            candidate = Path(skyrim).parent / master
            if candidate.is_file():
                argv += ['--otft-from', candidate]
    if patch_key == 'cosmetic':
        argv += ['--hair-plugin', HAIR_PLUGIN]
    run('verify', argv, dry_run=False)


def package(esp_path, out_root, extras=()):
    """Zip the ESP the way every converted mod is zipped: root == Data.

    `extras` are (path, arcname) pairs for anything the patch needs alongside
    the plugin -- a loose script, say. A missing extra is an error: shipping
    the ESP without it would be a patch that silently does half its job.
    """
    esp_path = Path(esp_path)
    target = finished_dir(Path(out_root)) / f'{esp_path.stem}.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(esp_path, arcname=esp_path.name)
        for path, arcname in extras:
            if not Path(path).is_file():
                raise SystemExit(f'{path} is missing; the patch needs it '
                                 f'installed as {arcname}')
            zf.write(path, arcname=arcname)
            print(f'  + {arcname}')
    print(f'\nPackaged -> {target} ({target.stat().st_size:,} bytes)')
    print('Install it like any other converted mod: the archive root is the '
          'Data folder.')
    return target


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--patch', choices=sorted(PATCHES),
                    help='which patch to build')
    ap.add_argument('--plugins', nargs='+', default=[],
                    help='converted plugins to pull in, in load order')
    ap.add_argument('--output-dir', default=str(REPO / 'output'),
                    help='where the converted plugins live (default output/)')
    ap.add_argument('--seed', type=int, default=0,
                    help='cosmetic only: the random draw (same seed, same build)')
    ap.add_argument('--exact-only', action='store_true',
                    help='creatures/horses: apply only exact-tier swaps')
    ap.add_argument('--no-remove', action='store_true',
                    help='creatures: keep the remove-tier creatures in place')
    ap.add_argument('--landing', nargs=2, type=float, metavar=('X', 'Y'),
                    help='ship only: where the sea route puts the ship down '
                         '(default: the coordinates the route already carries)')
    ap.add_argument('--no-zip', action='store_true',
                    help='build the ESP but do not package it')
    ap.add_argument('--no-verify', action='store_true',
                    help='skip the ship gate (it is cheap; only for debugging)')
    ap.add_argument('--dry-run', action='store_true',
                    help='report only; write nothing')
    ap.add_argument('--list', action='store_true',
                    help='list the patches and exit')
    args = ap.parse_args()
    # The passes run as child processes with -u; without this the parent's own
    # headers arrive after their output and the log reads out of order.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    if args.list:
        for key in sorted(PATCHES):
            name, what = PATCHES[key]
            print(f'  {key:<10} {name:<34} {what}')
        return 0
    if not args.patch:
        ap.error('--patch is required (or --list)')
    if not args.plugins:
        ap.error('--plugins needs at least one converted plugin')

    name, what = PATCHES[args.patch]
    out_path = OUT_DIR / name
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print('=' * 70)
    print(f'  {name}  --  {what}')
    print(f'  plugins: {", ".join(args.plugins)}')
    print('=' * 70)

    if args.patch == 'cosmetic':
        build_cosmetic(args.plugins, args.output_dir, out_path, args.seed,
                       args.dry_run)
    elif args.patch == 'ship':
        argv = [REPO / 'tools' / 'patch' / 'assign_ship_port.py',
                '--plugins'] + list(args.plugins) + [
                '--output-dir', args.output_dir, '--out', out_path,
                '--script-dir', OUT_DIR / SHIP_SCRIPT_DIR]
        if args.landing:
            argv += ['--landing'] + [str(v) for v in args.landing]
        run(args.patch, argv, args.dry_run)
    elif args.patch == 'ineed':
        argv = [REPO / 'tools' / 'patch' / 'assign_ineed.py',
                '--plugins'] + list(args.plugins) + [
                '--output-dir', args.output_dir, '--out', out_path,
                '--report', REPORTS / 'ineed.tsv']
        for other in STACK_ON['ineed']:
            if (OUT_DIR / other).is_file():
                argv += ['--overlay', OUT_DIR / other]
        REPORTS.mkdir(parents=True, exist_ok=True)
        run(args.patch, argv, args.dry_run)
    else:
        scope = 'mounts' if args.patch == 'horses' else 'creatures'
        argv = [REPO / 'tools' / 'patch' / 'assign_creatures.py',
                '--plugins'] + list(args.plugins) + [
                '--output-dir', args.output_dir, '--scope', scope,
                '--out', out_path,
                '--report', REPORTS / f'{args.patch}.tsv']
        if scope == 'mounts':
            # Horses are confirmed working with the shell swap; cloning would
            # also hand them vanilla stats, which nobody asked for.
            argv.append('--no-clone')
        if args.exact_only:
            argv.append('--exact-only')
        if args.no_remove:
            argv.append('--no-remove')
        REPORTS.mkdir(parents=True, exist_ok=True)
        run(args.patch, argv, args.dry_run)

    if args.dry_run:
        print('\nDRY RUN -- nothing written')
        return 0
    if not Path(out_path).is_file():
        raise SystemExit(f'{out_path} was not written')
    if not args.no_verify:
        verify(args.patch, args.plugins, args.output_dir, out_path)
    if not args.no_zip:
        package(out_path, args.output_dir, EXTRA_FILES.get(args.patch, []))
    return 0


if __name__ == '__main__':
    sys.exit(main())
