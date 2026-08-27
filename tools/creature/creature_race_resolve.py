#!/usr/bin/env python3
"""Resolve creature RACE FormIDs out of the DLC / Creation Club / Beyond Skyrim
plugins, so the vanilla-creature-swap table can quote VERIFIED ids.

The equivalence table (docs/creature_race_equivalence.md) can verify anything in
Skyrim.esm against references/Skyrim.esm, but Dawnguard/Dragonborn/CC/Beyond
Skyrim have no dump in the repo — every id for those was a placeholder. This
reads the real files and prints, for each, the RACE records whose EditorID
matches a search term, with the LOCAL FormID and the master's own name.

A swap ESP referencing one of these must:
  * declare the source plugin as a master, and
  * write the id with the load-order byte the master gets at runtime
    (the low 24 bits printed here are what is stable).

Note ESL-flagged plugins: their records live in the 0xFE___xxx space at
runtime, so only the low 12 bits of the id are addressable. That is flagged in
the output because it changes how the reference must be written.

Usage:
    python tools/creature/creature_race_resolve.py --all
    python tools/creature/creature_race_resolve.py --plugin Dragonborn.esm
    python tools/creature/creature_race_resolve.py --plugin BSAssets.esm --grep goblin
    python tools/creature/creature_race_resolve.py --plugin <newmod.esp> --skins
    python tools/creature/creature_race_resolve.py --all --json out.json
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.esm.tes5_esm_reader import read_tes5_file, _get, _zstring

# The plugins the swap table wants ids from, and why.
SOURCES = [
    ('Dawnguard.esm',            'DLC1  — frost giant, death hound, gargoyle'),
    ('Dragonborn.esm',           'DLC2  — riekling, netch, boar, ash spawn'),
    ('BSAssets.esm',             'Beyond Skyrim — goblin, scamp, ogre, imp, minotaur'),
    ('BSHeartland.esm',          'Beyond Skyrim: Cyrodiil — daedroth, CYR skeleton/wisp/troll'),
    ('ccbgssse040-advobgobs.esl', 'CC Goblins'),
    ('ccbgssse025-advdsgs.esm',  'CC Saints & Seducers — golden saint, dark seducer, elytra'),
    ('ccbgssse003-zombies.esl',  'CC Plague of the Dead — zombie'),
    ('ccbgssse036-petbwolf.esl', 'CC Bone Wolf'),
    ('ccbgssse067-daedinv.esm',  'CC The Cause — ayleid lich'),
]

ESL_FLAG = 0x00000200


def find_data_dir(explicit=None):
    if explicit:
        return explicit
    try:
        from asset_convert.skyrim_assets import find_skyrim_data
        d = find_skyrim_data()
        if d:
            return str(d)
    except Exception:
        pass
    try:
        import winreg
        for root, sub in (
                (winreg.HKEY_LOCAL_MACHINE,
                 r'SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim Special Edition'),
                (winreg.HKEY_LOCAL_MACHINE,
                 r'SOFTWARE\Bethesda Softworks\Skyrim Special Edition')):
            try:
                k = winreg.OpenKey(root, sub)
                p = winreg.QueryValueEx(k, 'Installed Path')[0]
                return os.path.join(p, 'Data')
            except OSError:
                continue
    except Exception:
        pass
    return None


def races_in(path, want_skins=False):
    """[(local_fid, editorid, skin_fid, skin_edid)] per RACE, plus the ESL flag.

    `skin_fid` is the race's WNAM -- the body ARMO. A swap that replaces the
    race without also replacing the skin leaves the actor on its old body mesh
    with bone names the new skeleton does not have, so the skin is not optional
    trivia; see docs/creature_race_equivalence.md. The ARMO EditorID is only
    resolved when `want_skins`, and only for skins defined in this same file --
    a skin inherited from a master comes back with an empty name.
    """
    types = {'RACE', 'ARMO'} if want_skins else {'RACE'}
    header, records, _loc = read_tes5_file(path, parse_types=types)
    flags = 0
    if header is not None:
        flags = getattr(header, 'flags', 0) or 0
    armo = {}
    races = []
    for rec in records:
        sub = _get(rec, 'EDID')
        edid = _zstring(sub.data) if sub else ''
        if rec.type == 'ARMO':
            armo[rec.form_id] = edid
        elif rec.type == 'RACE':
            skin = 0
            if want_skins:
                w = _get(rec, 'WNAM')
                if w is not None and len(w.data) >= 4:
                    skin = struct.unpack('<I', w.data[:4])[0]
            races.append((rec.form_id, edid, skin))
    out = [(f, e, s, armo.get(s, '')) for f, e, s in races]
    return out, bool(flags & ESL_FLAG)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data-dir', help='Skyrim Data folder (auto-detected)')
    ap.add_argument('--plugin', help='just this one plugin')
    ap.add_argument('--grep', help='only EditorIDs containing this (case-insens)')
    ap.add_argument('--all', action='store_true', help='every known source')
    ap.add_argument('--skins', action='store_true',
                    help="also print each race's WNAM skin ARMO -- what a swap "
                         'has to replace alongside the race')
    ap.add_argument('--json', help='also write results as JSON here')
    args = ap.parse_args()

    data = find_data_dir(args.data_dir)
    if not data or not os.path.isdir(data):
        print('Could not find the Skyrim Data folder; pass --data-dir')
        return 2
    print('Data: %s\n' % data)

    todo = ([(args.plugin, '')] if args.plugin
            else SOURCES if args.all else SOURCES)
    result = {}
    for name, why in todo:
        path = os.path.join(data, name)
        if not os.path.isfile(path):
            print('%-30s -- NOT INSTALLED (rows must be greyed out)' % name)
            continue
        try:
            races, is_esl = races_in(path, want_skins=args.skins)
        except Exception as exc:
            print('%-30s !! read failed: %s' % (name, exc))
            continue
        hits = [row for row in races
                if not args.grep or args.grep.lower() in row[1].lower()]
        print('=== %s ===%s' % (name, ('  [%s]' % why) if why else ''))
        print('    %d RACE records%s%s'
              % (len(races), ', ESL-flagged (runtime FE___xxx)' if is_esl else '',
                 ', %d match' % len(hits) if args.grep else ''))
        for fid, edid, skin, skin_edid in sorted(hits, key=lambda t: t[1].lower()):
            if args.skins:
                print('      0x%08X  %-44s skin=0x%08X %s'
                      % (fid, edid, skin, skin_edid))
            else:
                print('      0x%08X  %s' % (fid, edid))
        result[name] = {'esl': is_esl,
                        'races': [{'fid': '0x%08X' % f, 'edid': e,
                                   'skin': '0x%08X' % s, 'skin_edid': se}
                                  for f, e, s, se in hits]}
        print()

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=2)
        print('wrote %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
