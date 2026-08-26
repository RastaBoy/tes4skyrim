#!/usr/bin/env python3
"""Assign outfits (OTFT) to the female NPCs of a source plugin by writing NPC_
override records into a patch plugin.

The patch plugin must already list the source plugin as a master and must
already contain the OTFT records the outfits are chosen from (matched by
EditorID). Every female NPC_ of the source is copied into the patch as an
override -- xEdit's "copy as override" -- with its FormID references remapped
into the patch's load order and its DOFT (Default Outfit) replaced by an outfit
drawn deterministically from a list.

Which list an NPC draws from is decided by where the NPC is PLACED: every ACHR
in the source that points at the NPC contributes its parent cell, and the cell's
EditorID / FULL name / parent worldspace EditorID+FULL are matched against the
`--match-outfits` keywords. First keyword that matches wins; NPCs that match
nothing use `--default-outfits`.

An NPC the patch already overrides keeps every other edit it carries -- only
DOFT is touched -- so this can be run after (or before) the other assign_* tools.

Selection is deterministic: sha256(seed, FormID) picks the outfit, so re-running
produces an identical plugin.

Usage:
    python tools/assign_female_outfits.py \
        --source output/Oblivion.esm/Oblivion.esm \
        --patch  patch_folder/sources/MyCosmeticTamrielPatch.esp \
        --out    patch_folder/output/MyCosmeticTamrielPatch.esp \
        --constants patch_folder/sources/constants.py \
        --default-outfits OUTFITS_TO_CHOOSE \
        --match-outfits bruma=BRUMA_OUTFITS_TO_CHOOSE

    # dry run: print the assignment table, write nothing
    python tools/assign_female_outfits.py ... --dry-run --report temp/outfits.tsv
"""

import argparse
import hashlib
import struct
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.plugin_patch import (          # noqa: E402
    ACBS_FEMALE, AFTER_DOFT, Patch, SourcePlugin, first, insert_run,
    make_remap, remap_fid, remap_npc_record, zstring,
)


def load_constants(path):
    ns = {}
    exec(compile(Path(path).read_text(encoding='utf-8'), str(path), 'exec'),
         ns, ns)
    return {k: v for k, v in ns.items() if not k.startswith('_')}


def main():
    ap = argparse.ArgumentParser(
        description='Give every female NPC of a source plugin a random outfit, '
                    'written as NPC_ overrides into a patch plugin.')
    ap.add_argument('--source', required=True,
                    help='plugin the NPCs come from (must be a master of the patch)')
    ap.add_argument('--patch', required=True, help='patch plugin to extend')
    ap.add_argument('--out', help='output plugin path (default: overwrite --patch)')
    ap.add_argument('--constants', required=True,
                    help='python file defining the outfit EditorID lists')
    ap.add_argument('--default-outfits', default='OUTFITS_TO_CHOOSE',
                    help='constant name used when no --match-outfits keyword hits')
    ap.add_argument('--match-outfits', action='append', default=[],
                    metavar='KEYWORD=CONSTANT',
                    help='use CONSTANT for NPCs placed in a cell or worldspace '
                         'whose EditorID/name contains KEYWORD (repeatable, '
                         'first match wins)')
    ap.add_argument('--seed', type=int, default=0,
                    help='RNG seed; the same seed always produces the same plugin')
    ap.add_argument('--report', help='write the full assignment table here')
    ap.add_argument('--dry-run', action='store_true',
                    help='report only, write no plugin')
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else Path(args.patch)
    consts = load_constants(args.constants)

    patch = Patch(args.patch)
    print(f'patch masters: {patch.masters}')
    print(f'patch NPC_ overrides already present: {len(patch.npcs)}')

    otft_by_edid = {}
    for fid, (_hdr, subs) in patch.records_of('OTFT').items():
        otft_by_edid[zstring(first(subs, 'EDID')).lower()] = fid
    print(f'patch OTFT records: {len(otft_by_edid)}')

    def resolve(names, where):
        out = []
        for n in names:
            fid = otft_by_edid.get(n.lower())
            if fid is None:
                raise SystemExit(f'{where}: no OTFT with EditorID "{n}" in '
                                 f'{Path(args.patch).name}')
            out.append((n, fid))
        return out

    rules = []
    for spec in args.match_outfits:
        if '=' not in spec:
            raise SystemExit(f'--match-outfits needs KEYWORD=CONSTANT, got {spec!r}')
        keyword, const = spec.split('=', 1)
        if const not in consts:
            raise SystemExit(f'{args.constants} has no list named {const}')
        rules.append((keyword.strip().lower(), const,
                      resolve(consts[const], const)))
    if args.default_outfits not in consts:
        raise SystemExit(f'{args.constants} has no list named {args.default_outfits}')
    default_rule = (args.default_outfits,
                    resolve(consts[args.default_outfits], args.default_outfits))

    src = SourcePlugin(args.source, {'NPC_', 'CELL', 'ACHR', 'WRLD'})
    mapping = make_remap(src.masters, patch.masters, src.name)
    print(f'source masters: {src.masters}')
    print('master index remap: '
          + ', '.join(f'{k:02X}->{v:02X}' for k, v in sorted(mapping.items())))

    placements = defaultdict(set)
    for fid, (_hdr, subs) in src.by_type['ACHR'].items():
        name = first(subs, 'NAME')
        if name and len(name) == 4:
            placements[struct.unpack('<I', name)[0]].add(src.parents[fid][0])

    def location_text(npc_fid):
        parts = []
        for cell_fid in placements.get(npc_fid, ()):
            cell = src.by_type['CELL'].get(cell_fid)
            if not cell:
                continue
            parts += [zstring(first(cell[1], 'EDID')),
                      zstring(first(cell[1], 'FULL'))]
            wrld_fid = src.parents[cell_fid][1]
            wrld = src.by_type['WRLD'].get(wrld_fid)
            if wrld:
                parts += [zstring(first(wrld[1], 'EDID')),
                          zstring(first(wrld[1], 'FULL'))]
        return ' '.join(parts).lower()

    females = []
    for fid, (_hdr, subs) in src.by_type['NPC_'].items():
        acbs = first(subs, 'ACBS')
        if acbs and struct.unpack_from('<I', acbs, 0)[0] & ACBS_FEMALE:
            females.append(fid)
    females.sort()

    assignments = []
    per_rule = defaultdict(int)
    for fid in females:
        text = location_text(fid)
        rule_name, table = default_rule
        for keyword, const, resolved in rules:
            if keyword in text:
                rule_name, table = const, resolved
                break
        # sha256 of (seed, FormID) rather than the raw FormID: NPCs of one town
        # have consecutive FormIDs, and a Mersenne twister seeded with
        # consecutive small ints is visibly correlated over a short list.
        digest = hashlib.sha256(f'{args.seed}:{fid:08X}'.encode()).digest()
        rng = Random(int.from_bytes(digest[:8], 'little'))
        outfit_edid, outfit_fid = table[rng.randrange(len(table))]
        subs = src.by_type['NPC_'][fid][1]
        assignments.append((fid, zstring(first(subs, 'EDID')),
                            zstring(first(subs, 'FULL')), rule_name,
                            outfit_edid, outfit_fid))
        per_rule[rule_name] += 1

    print(f'female NPCs: {len(females)}')
    for name, count in sorted(per_rule.items()):
        print(f'  {name}: {count}')
    print(f'  (of those, {sum(1 for f in females if not placements.get(f))} '
          'are not placed in any cell)')

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, 'w', encoding='utf-8') as fh:
            fh.write('SOURCE_FORMID\tPATCH_FORMID\tEDITORID\tNAME\tLIST\tOUTFIT\n')
            for fid, edid, full, rule, oedid, _ofid in assignments:
                fh.write(f'{fid:08X}\t{remap_fid(fid, mapping):08X}\t{edid}\t'
                         f'{full}\t{rule}\t{oedid}\n')
        print(f'report: {args.report}')

    if args.dry_run:
        print('dry run: nothing written')
        return

    updated = added = 0
    for fid, _edid, _full, _rule, _oedid, outfit_fid in assignments:
        pfid = remap_fid(fid, mapping)
        if pfid in patch.npcs:
            header, subs = patch.npcs[pfid]
            updated += 1
        else:
            header, subs = remap_npc_record(*src.by_type['NPC_'][fid], mapping)
            added += 1
        subs = insert_run(subs, 'DOFT', [struct.pack('<I', outfit_fid)],
                          AFTER_DOFT)
        patch.set_npc(pfid, header, subs)

    size, records, groups = patch.write(out_path)
    print(f'NPC_ overrides: {added} added, {updated} updated, '
          f'{len(patch.npcs)} total')
    print(f'wrote {out_path} ({size:,} bytes, {records} records, {groups} groups)')


if __name__ == '__main__':
    main()
