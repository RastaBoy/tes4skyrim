#!/usr/bin/env python3
"""Verify a built NPC-override patch plugin before it ships.

Every check either passes or prints what failed and how much; the exit code is
non-zero if anything failed, so this can gate a build.

    python tools/verify_npc_patch.py \
        --patch    patch_folder/output/MyCosmeticTamrielPatch.esp \
        --original patch_folder/sources/MyCosmeticTamrielPatch.esp \
        --source   output/Oblivion.esm/Oblivion.esm \
        --hair-plugin "patch_folder/sources/KS Hairdo's.esp"

Checks:
  1. structure    every byte tiles: records and GRUPs nest exactly, and every
                  uncompressed record's subrecords fill its data block
  2. hedr         HEDR record count == records (excluding the file header) + GRUPs
  3. groups       top-level GRUPs are in canonical (xEdit/CK) order
  4. masters      every FormID referenced by an NPC_ subrecord (VMAD included)
                  names a master the patch actually lists
  5. fidelity     every subrecord the passes do NOT own is byte-identical to the
                  source record after master-index remapping, and the field
                  order is unchanged
  6. order        DOFT and PNAM sit where the canonical NPC_ field order puts them
  7. carried      groups the passes never touch are byte-identical to --original
  8. outfits      every DOFT names a real OTFT -- this patch's own (assigned) or
                  the source plugin's (carried through untouched)
  9. hair         PNAM starts with a Hair-type part from --hair-plugin followed
                  by an Is-Extra-Part companion, gender flags agree with ACBS,
                  and no other head part comes from the hair plugin
"""

import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.plugin_patch import (          # noqa: E402
    ACBS_FEMALE, AFTER_DOFT, AFTER_PNAM, FLAG_COMPRESSED, GROUP_ORDER, GRP_HDR,
    NPC_FORMID_FIELDS, NPC_PLAIN_FIELDS, Patch, REC_HDR, SUB_HDR, SourcePlugin,
    first, make_remap, read_subrecords, remap_fid, remap_npc_subrecord,
    top_level_groups, vmad_formid_offsets, zstring,
)

HDPT_TYPE_HAIR = 3
HDPT_FLAG_MALE = 0x02
HDPT_FLAG_FEMALE = 0x04
HDPT_FLAG_EXTRA = 0x08


class Report:
    def __init__(self):
        self.failed = 0

    def ok(self, name, detail=''):
        print(f'  PASS  {name:12} {detail}')

    def fail(self, name, detail):
        self.failed += 1
        print(f'  FAIL  {name:12} {detail}')

    def check(self, name, condition, detail):
        (self.ok if condition else self.fail)(name, detail)


def check_structure(buf, rep):
    counts = Counter()

    def walk(pos, end):
        while pos < end:
            if pos + REC_HDR > end:
                raise ValueError(f'truncated entry at {pos:#x}')
            if buf[pos:pos + 4] == b'GRUP':
                size = struct.unpack_from('<I', buf, pos + 4)[0]
                if size < GRP_HDR or pos + size > end:
                    raise ValueError(f'GRUP at {pos:#x} overruns its parent')
                counts['groups'] += 1
                walk(pos + GRP_HDR, pos + size)
                pos += size
                continue
            dsize, flags = struct.unpack_from('<II', buf, pos + 4)
            sig = buf[pos:pos + 4].decode('ascii', 'replace')
            if pos + REC_HDR + dsize > end:
                raise ValueError(f'{sig} at {pos:#x} overruns its group')
            counts['records'] += 1
            counts[sig] += 1
            if not flags & FLAG_COMPRESSED:
                p, e = pos + REC_HDR, pos + REC_HDR + dsize
                while p < e:
                    if p + SUB_HDR > e:
                        raise ValueError(f'{sig} at {pos:#x}: truncated subrecord')
                    p += SUB_HDR + struct.unpack_from('<H', buf, p + 4)[0]
                if p != e:
                    raise ValueError(f'{sig} at {pos:#x}: subrecords overrun by '
                                     f'{p - e} bytes')
            pos += REC_HDR + dsize

    hsize = struct.unpack_from('<I', buf, 4)[0]
    try:
        walk(REC_HDR + hsize, len(buf))
    except ValueError as exc:
        rep.fail('structure', str(exc))
        return counts
    rep.ok('structure', f'{counts["records"]} records, {counts["groups"]} groups, '
                        f'{dict((k, v) for k, v in counts.items() if len(k) == 4)}')

    hedr = next((p for s, p in read_subrecords(buf[REC_HDR:REC_HDR + hsize])
                 if s == 'HEDR'), None)
    if hedr is None:
        rep.fail('hedr', 'no HEDR subrecord in the file header')
    else:
        got = struct.unpack_from('<I', hedr, 4)[0]
        want = counts['records'] + counts['groups']
        rep.check('hedr', got == want, f'{got} (records+groups = {want})')

    labels = [g[0] for g in top_level_groups(buf)]
    rank = [GROUP_ORDER.index(l) if l in GROUP_ORDER else len(GROUP_ORDER)
            for l in labels]
    rep.check('groups', rank == sorted(rank), ' '.join(labels))
    return counts


def check_masters(patch, rep):
    limit = len(patch.masters)          # the patch's own index
    idx = Counter()
    bad = Counter()
    for pfid, (_hdr, subs) in patch.npcs.items():
        if pfid >> 24 > limit:
            bad['record FormID'] += 1
        for sig, payload in subs:
            field = NPC_FORMID_FIELDS.get(sig)
            if field:
                off, stride = field
                for base in range(0, len(payload), stride):
                    v = struct.unpack_from('<I', payload, base + off)[0] >> 24
                    idx[v] += 1
                    if v > limit:
                        bad[sig] += 1
            elif sig == 'VMAD':
                for o in vmad_formid_offsets(payload):
                    v = struct.unpack_from('<I', payload, o)[0] >> 24
                    idx[v] += 1
                    if v > limit:
                        bad['VMAD'] += 1
            elif sig not in NPC_PLAIN_FIELDS:
                bad['unknown ' + sig] += 1
    named = ', '.join(
        f'{i:02X}={patch.masters[i] if i < limit else Path(patch.path).name}:{n}'
        for i, n in sorted(idx.items()))
    rep.check('masters', not bad, named if not bad else f'out of range: {dict(bad)}')


def check_fidelity(patch, src, mapping, owned, rep):
    src_index = {remap_fid(f, mapping): v for f, v in src.by_type['NPC_'].items()}
    missing = order = value = 0
    checked = 0
    for pfid, (_hdr, subs) in patch.npcs.items():
        origin = src_index.get(pfid)
        if origin is None:
            missing += 1
            continue
        want = [(s, p) for s, p in origin[1] if s not in owned]
        got = [(s, p) for s, p in subs if s not in owned]
        if [s for s, _ in want] != [s for s, _ in got]:
            order += 1
            continue
        for (sig, payload), (_gsig, gpayload) in zip(want, got):
            checked += 1
            if remap_npc_subrecord(sig, payload, mapping) != gpayload:
                value += 1
    detail = (f'{checked - value}/{checked} subrecords identical to the source '
              f'after remap')
    if missing:
        detail += f'; {missing} records not found in the source'
    if order:
        detail += f'; {order} records changed field order'
    rep.check('fidelity', not (missing or order or value), detail)


def check_order(patch, rep):
    bad = Counter()
    for _pfid, (_hdr, subs) in patch.npcs.items():
        sigs = [s for s, _ in subs]
        for sig, successors in (('DOFT', AFTER_DOFT), ('PNAM', AFTER_PNAM)):
            if sig not in sigs:
                continue
            i = sigs.index(sig)
            if any(s in successors for s in sigs[:i]):
                bad[sig] += 1
            run_end = len(sigs) - 1 - sigs[::-1].index(sig)
            if any(s != sig for s in sigs[i:run_end + 1]):
                bad[sig + ' split'] += 1
    rep.check('order', not bad,
              'DOFT and PNAM in canonical position in all '
              f'{len(patch.npcs)} records' if not bad else dict(bad))


def check_carried(patch, original, rep):
    if original is None:
        rep.ok('carried', 'skipped (--original not given)')
        return
    base = Patch(original)
    diff = [k for k in base.groups if k != 'NPC_'
            and base.groups[k] != patch.groups.get(k)]
    compared = [k for k in base.groups if k != 'NPC_']
    rep.check('carried', not diff,
              f'{len(compared)} untouched groups byte-identical '
              f'({" ".join(compared)})' if not diff else f'changed: {diff}')


def check_outfits(patch, src_otft, rep):
    """Every DOFT must name a real OTFT -- this patch's own (an assigned
    outfit) or the source plugin's (one carried through untouched)."""
    mine = set(patch.records_of('OTFT'))
    known = mine | src_otft
    assigned = Counter()
    carried = 0
    bad = 0
    total = 0
    for _pfid, (_hdr, subs) in patch.npcs.items():
        doft = first(subs, 'DOFT')
        if doft is None:
            continue
        total += 1
        target = struct.unpack('<I', doft)[0]
        if target in mine:
            assigned[target] += 1
        elif target in known:
            carried += 1
        else:
            bad += 1
    if not total:
        rep.ok('outfits', 'no DOFT present')
        return
    rep.check('outfits', not bad,
              f'{total} NPCs with an outfit: {sum(assigned.values())} assigned '
              f'here ({len(assigned)} distinct), {carried} carried from the '
              'source' if not bad
              else f'{bad} DOFT targets are an OTFT in neither this patch nor '
                   'the source')


def check_hair(patch, hair_plugin, rep):
    if hair_plugin is None:
        rep.ok('hair', 'skipped (--hair-plugin not given)')
        return
    plugin = SourcePlugin(hair_plugin, {'HDPT'})
    mapping = make_remap(plugin.masters, patch.masters, plugin.name)
    info = {}
    for fid, (_hdr, subs) in plugin.by_type['HDPT'].items():
        pnam = first(subs, 'PNAM')
        data = first(subs, 'DATA')
        info[remap_fid(fid, mapping)] = (
            zstring(first(subs, 'EDID')),
            struct.unpack('<I', pnam)[0] if pnam else None,
            data[0] if data else 0)

    bad = Counter()
    styled = 0
    used = Counter()
    for _pfid, (_hdr, subs) in patch.npcs.items():
        parts = [struct.unpack('<I', p)[0] for s, p in subs if s == 'PNAM']
        mine = [p for p in parts if p in info]
        if not mine:
            continue
        styled += 1
        acbs = first(subs, 'ACBS')
        female = bool(acbs and struct.unpack_from('<I', acbs, 0)[0] & ACBS_FEMALE)
        want_flag = HDPT_FLAG_FEMALE if female else HDPT_FLAG_MALE
        if len(parts) < 2 or parts[0] not in info or parts[1] not in info:
            bad['hair+HL not first'] += 1
            continue
        hair, hl = info[parts[0]], info[parts[1]]
        used[hair[0]] += 1
        if hair[1] != HDPT_TYPE_HAIR:
            bad['first part is not Hair type'] += 1
        if not hair[2] & want_flag:
            bad['hair gender flag disagrees with ACBS'] += 1
        if hl[1] != 0 or not hl[2] & HDPT_FLAG_EXTRA:
            bad['second part is not an extra part'] += 1
        if hl[0].lower() != (hair[0] + 'HL').lower():
            bad['companion is not <hair>HL'] += 1
        if any(p in info for p in parts[2:]):
            bad['stray head part from the hair plugin'] += 1
    rep.check('hair', not bad,
              f'{styled} NPCs, {len(used)} distinct styles, hair+HL leading '
              'every head-part run' if not bad else dict(bad))


def main():
    ap = argparse.ArgumentParser(
        description='Verify a built NPC-override patch plugin.')
    ap.add_argument('--patch', required=True, help='the BUILT plugin to check')
    ap.add_argument('--source', required=True,
                    help='plugin the NPC_ overrides were copied from')
    ap.add_argument('--original',
                    help='the patch before any pass ran, to prove untouched '
                         'groups are byte-identical')
    ap.add_argument('--hair-plugin', help='enables the head-part checks')
    ap.add_argument('--owns', default='DOFT,PNAM',
                    help='comma-separated subrecords the passes are allowed to '
                         'change (default DOFT,PNAM)')
    args = ap.parse_args()

    rep = Report()
    buf = Path(args.patch).read_bytes()
    print(f'{args.patch}  ({len(buf):,} bytes)')

    check_structure(buf, rep)
    patch = Patch(args.patch)
    print(f'  ....  masters      {patch.masters}')
    print(f'  ....  overrides    {len(patch.npcs)} NPC_')

    src = SourcePlugin(args.source, {'NPC_', 'OTFT'})
    mapping = make_remap(src.masters, patch.masters, src.name)
    src_otft = {remap_fid(f, mapping) for f in src.by_type['OTFT']}

    check_masters(patch, rep)
    check_fidelity(patch, src, mapping,
                   {s.strip() for s in args.owns.split(',') if s.strip()}, rep)
    check_order(patch, rep)
    check_carried(patch, args.original, rep)
    check_outfits(patch, src_otft, rep)
    check_hair(patch, args.hair_plugin, rep)

    print()
    if rep.failed:
        print(f'{rep.failed} check(s) FAILED')
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
