#!/usr/bin/env python3
"""Bring each NPC's QNAM (texture lighting) back into agreement with the
skin-tone tint layer the record actually carries, as NPC_ overrides in a patch.

Fixes the face-lighter-than-body (or darker-than-body) mismatch: QNAM and the
skin-tone tint layer are the same colour expressed twice, and the engine paints
the face from one and the body from the other. Vanilla always derives QNAM from
the layer as

    QNAM_channel = floor(127 * (1 - TINV/100) + TINC_channel * TINV/100) / 255

blending toward MID-GREY, not toward white. See
`tes5_import.npc_face_mapper.skin_tone_qnam`, which this tool calls so the
converter and the patch can never drift apart.

Which layer is the skin tone is not guessed: the NPC's RACE lists its tint
masks, and the one whose TINP mask type is 6 ("Skin Tone") — taken from the
male or female section according to the NPC's ACBS female bit — names the TINI
index to use. A record carrying exactly one tint layer uses that layer even
when its race cannot be read.

Usage:
    python tools/patch/assign_skin_tone.py \
        --source output/Oblivion.esm/Oblivion.esm \
        --patch  patch_folder/output/MyCosmeticTamrielPatch.esp \
        --out    patch_folder/output/MyCosmeticTamrielPatch.esp \
        --race-plugin "<SSE>/Data/Skyrim.esm" \
        --report temp/skin.tsv
"""

import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tes5_import.npc_face_mapper import skin_tone_qnam   # noqa: E402
from tools.patch.plugin_patch import (                          # noqa: E402
    ACBS_FEMALE, AFTER_QNAM, Patch, SourcePlugin, first, insert_run,
    make_remap, remap_fid, remap_npc_record, zstring,
)

TINP_SKIN_TONE = 6

# The RACE record carries a male head-data block then a female one; these
# subrecords open each. Every TINI/TINP pair after one belongs to that gender.
_MALE_SECTION = ('RPRM', 'AHCM', 'FTSM', 'DFTM')
_FEMALE_SECTION = ('RPRF', 'AHCF', 'FTSF', 'DFTF')


def race_skin_indices(subs):
    """(male_index, female_index) of the race's Skin Tone tint mask, or None."""
    section = None
    found = {}
    index = None
    for sig, payload in subs:
        if sig in _MALE_SECTION:
            section = 'M'
        elif sig in _FEMALE_SECTION:
            section = 'F'
        elif sig == 'TINI' and len(payload) >= 2:
            index = struct.unpack('<H', payload[:2])[0]
        elif sig == 'TINP' and len(payload) >= 2 and index is not None:
            if struct.unpack('<H', payload[:2])[0] == TINP_SKIN_TONE:
                found.setdefault(section, index)
    return found.get('M'), found.get('F')


def npc_tint_layers(subs):
    """[{'idx','c','v','a'}] for the record's tint layers, in order."""
    out = []
    cur = None
    for sig, payload in subs:
        if sig == 'TINI':
            if cur:
                out.append(cur)
            cur = {'idx': struct.unpack('<H', payload[:2])[0]}
        elif cur is None:
            continue
        elif sig == 'TINC':
            cur['c'] = tuple(payload[:3])
        elif sig == 'TINV':
            cur['v'] = struct.unpack('<I', payload[:4])[0]
        elif sig == 'TIAS':
            cur['a'] = struct.unpack('<h', payload[:2])[0]
    if cur:
        out.append(cur)
    return [l for l in out if 'c' in l and 'v' in l]


def main():
    ap = argparse.ArgumentParser(
        description="Rewrite NPC_ QNAM to agree with the record's skin-tone "
                    'tint layer.')
    ap.add_argument('--source', required=True,
                    help='plugin the NPCs come from (must be a master of the patch)')
    ap.add_argument('--patch', required=True, help='patch plugin to extend')
    ap.add_argument('--out', help='output plugin path (default: overwrite --patch)')
    ap.add_argument('--race-plugin', action='append', default=[], metavar='PLUGIN',
                    help='extra plugin to read RACE tint masks from (repeatable); '
                         'the source is always read')
    ap.add_argument('--report', help='write the full table here')
    ap.add_argument('--dry-run', action='store_true',
                    help='report only, write no plugin')
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else Path(args.patch)
    patch = Patch(args.patch)
    print(f'patch masters: {patch.masters}')
    print(f'patch NPC_ overrides already present: {len(patch.npcs)}')

    src = SourcePlugin(args.source, {'NPC_', 'RACE'})
    mapping = make_remap(src.masters, patch.masters, src.name)

    skin_index = {}          # patch-space race FormID -> (male idx, female idx)
    race_name = {}
    for fid, (_hdr, subs) in src.by_type['RACE'].items():
        pfid = remap_fid(fid, mapping)
        skin_index[pfid] = race_skin_indices(subs)
        race_name[pfid] = zstring(first(subs, 'EDID'))
    for path in args.race_plugin:
        extra = SourcePlugin(path, {'RACE'})
        emap = make_remap(extra.masters, patch.masters, extra.name)
        for fid, (_hdr, subs) in extra.by_type['RACE'].items():
            pfid = remap_fid(fid, emap)
            skin_index.setdefault(pfid, race_skin_indices(subs))
            race_name.setdefault(pfid, zstring(first(subs, 'EDID')))
        print(f'{Path(path).name}: +{len(extra.by_type["RACE"])} RACE tint masks')
    resolved = sum(1 for v in skin_index.values() if v[0] is not None
                   or v[1] is not None)
    print(f'races with a Skin Tone (TINP=6) mask: {resolved} of {len(skin_index)}')

    rows = []
    reason = Counter()
    for fid, (_hdr, subs) in src.by_type['NPC_'].items():
        tints = npc_tint_layers(subs)
        if not tints:
            reason['no tint layer'] += 1
            continue
        acbs = first(subs, 'ACBS')
        female = bool(acbs and struct.unpack_from('<I', acbs, 0)[0] & ACBS_FEMALE)
        rnam = first(subs, 'RNAM')
        race = struct.unpack('<I', rnam)[0] if rnam else 0
        want_idx = None
        if race:
            pair = skin_index.get(remap_fid(race, mapping))
            if pair:
                want_idx = pair[1] if female else pair[0]
        layer = next((l for l in tints if l['idx'] == want_idx), None)
        if layer is None:
            if len(tints) == 1:
                layer = tints[0]
                reason['single layer, race mask unknown'] += 1
            else:
                reason['cannot identify the skin-tone layer'] += 1
                continue
        else:
            reason['matched the race Skin Tone mask'] += 1
        want = skin_tone_qnam(layer['c'], layer['v'])
        have = first(subs, 'QNAM')
        cur = struct.unpack('<3f', have) if have and len(have) == 12 else None
        delta = (max(abs(a - b) * 255 for a, b in zip(cur, want))
                 if cur else None)
        rows.append((fid, zstring(first(subs, 'EDID')),
                     zstring(first(subs, 'FULL')),
                     race_name.get(remap_fid(race, mapping), '?') if race else '?',
                     'F' if female else 'M', layer, cur, want, delta))

    print(f'\nNPCs with a skin-tone layer: {len(rows)}')
    for k, v in reason.most_common():
        print(f'  {k}: {v}')

    buckets = Counter()
    for r in rows:
        d = r[8]
        buckets['no QNAM at all' if d is None
                else 'already correct' if d < 0.51
                else 'off by 1-4/255' if d < 4.5
                else 'off by 5-15/255' if d < 15.5
                else 'off by >15/255'] += 1
    print('\nQNAM vs the record\'s own tint layer:')
    for k in ('already correct', 'off by 1-4/255', 'off by 5-15/255',
              'off by >15/255', 'no QNAM at all'):
        if buckets.get(k):
            print(f'  {k}: {buckets[k]}')

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, 'w', encoding='utf-8') as fh:
            fh.write('SOURCE_FORMID\tPATCH_FORMID\tEDITORID\tNAME\tRACE\tSEX\t'
                     'TINI\tTINC\tTINV\tQNAM_WAS\tQNAM_NOW\tMAX_DELTA_255\n')
            for fid, edid, full, race, sex, layer, cur, want, delta in rows:
                was = ','.join(f'{x * 255:.0f}' for x in cur) if cur else ''
                now = ','.join(f'{x * 255:.0f}' for x in want)
                fh.write(f'{fid:08X}\t{remap_fid(fid, mapping):08X}\t{edid}\t{full}\t'
                         f'{race}\t{sex}\t{layer["idx"]}\t'
                         f'{",".join(str(c) for c in layer["c"])}\t{layer["v"]}\t'
                         f'{was}\t{now}\t'
                         f'{"" if delta is None else f"{delta:.0f}"}\n')
        print(f'report: {args.report}')

    if args.dry_run:
        print('dry run: nothing written')
        return

    added = updated = unchanged = 0
    for fid, _edid, _full, _race, _sex, _layer, cur, want, delta in rows:
        pfid = remap_fid(fid, mapping)
        if pfid in patch.npcs:
            header, subs = patch.npcs[pfid]
            updated += 1
        else:
            header, subs = remap_npc_record(*src.by_type['NPC_'][fid], mapping)
            added += 1
        if delta is not None and delta < 0.51:
            unchanged += 1
        subs = insert_run(subs, 'QNAM', [struct.pack('<3f', *want)], AFTER_QNAM)
        patch.set_npc(pfid, header, subs)

    size, records, groups = patch.write(out_path)
    print(f'\nNPC_ overrides: {added} added, {updated} updated, '
          f'{len(patch.npcs)} total ({unchanged} already had the right QNAM)')
    print(f'wrote {out_path} ({size:,} bytes, {records} records, {groups} groups)')


if __name__ == '__main__':
    main()
