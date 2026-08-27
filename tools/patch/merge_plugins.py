#!/usr/bin/env python3
"""Merge several TES5 plugins into ONE, the way a real load order resolves them.

    python tools/patch/merge_plugins.py A.esp B.esp --out output/A.esp

The inputs are given IN LOAD ORDER: a record the later plugin also has wins,
exactly as it would with both files installed. Everything else -- the records
only one of them has, the GRUP nesting each record sits in, every subrecord the
merge does not have to touch -- is carried through byte for byte.

What the merge actually has to solve:

* **The master list is rebuilt.** The output masters the UNION of the inputs'
  masters, minus the inputs themselves: a plugin that listed another input as a
  master (`MyOwnCyrodiilPatch.esp` masters `MyOwnGamePatch.esp`) no longer can,
  because that plugin is now part of this one. Officials come first in
  Bethesda's order, then Creation Club, then ESMs, then ESPs -- an ESP can
  never precede an ESM in a Skyrim load order.
* **Every FormID is therefore renumbered.** A FormID's high byte indexes the
  plugin's OWN master list, so a master moving from slot 3 to slot 4 moves every
  reference to it. References into a merged input, and each input's own records,
  all land on the output's own index. The remap walks the per-subrecord FormID
  map in `patch_builder.py`; an unknown subrecord signature ABORTS rather than
  shipping a stale master index. When the mapping turns out to be the identity
  (nothing moved), records are copied verbatim and no field knowledge is needed.
* **Two inputs authoring the same object ID abort the run.** Their own records
  would collide at the output's index and one would silently eat the other.
  An input OVERRIDING another input's record is not a collision -- that is the
  whole point -- and is reported as an override.

The GRUP tree is merged node by node, so two plugins with refs in the same cell
end up with one cell-children group holding both, not two rival copies.
"""

import argparse
import struct
import sys
import zlib
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.patch.plugin_patch import (                       # noqa: E402
    FLAG_COMPRESSED, GRP_HDR, GROUP_ORDER, REC_HDR, SUB_HDR,
    build_subrecords, read_subrecords, zstring,
)
from tools.patch.patch_builder import (                      # noqa: E402
    OFFICIAL_ORDER, remap_fid, remap_record,
)

# Group types whose label is a FormID rather than a block number or a grid.
FORMID_LABEL_TYPES = {1, 6, 8, 9, 10}


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------

class Record:
    __slots__ = ('sig', 'fid', 'header', 'subs', 'source', 'authored')

    def __init__(self, sig, fid, header, subs, source, authored):
        self.sig = sig
        self.fid = fid
        self.header = header
        self.subs = subs
        self.source = source        # plugin name the record came from
        self.authored = authored    # True if that plugin DEFINES it (own index)


class Group:
    __slots__ = ('gtype', 'label', 'stamp', 'items')

    def __init__(self, gtype, label, stamp):
        self.gtype = gtype
        self.label = label
        self.stamp = stamp
        self.items = OrderedDict()   # key -> Record | Group


def _rec_key(fid):
    return ('R', fid)


def _grp_key(gtype, label):
    return ('G', gtype, label)


class Plugin:
    """One input, parsed into a GRUP tree with its header kept intact."""

    def __init__(self, path):
        self.path = Path(path)
        self.name = self.path.name
        buf = self.path.read_bytes()
        hsize = struct.unpack_from('<I', buf, 4)[0]
        self.header_flags = struct.unpack_from('<I', buf, 8)[0]
        self.header_subs = read_subrecords(buf[REC_HDR:REC_HDR + hsize])
        self.masters = [zstring(p) for s, p in self.header_subs if s == 'MAST']
        self.own_index = len(self.masters)
        self.next_object_id = 0
        for sig, payload in self.header_subs:
            if sig == 'HEDR':
                self.next_object_id = struct.unpack_from('<I', payload, 8)[0]
        self.onam = [f for sig, payload in self.header_subs if sig == 'ONAM'
                     for f in struct.unpack(f'<{len(payload) // 4}I', payload)]
        self.top = OrderedDict()
        self._parse(buf, REC_HDR + hsize, len(buf), self.top)

    def _parse(self, buf, pos, end, out):
        while pos < end:
            if bytes(buf[pos:pos + 4]) == b'GRUP':
                gsize, label, gtype = struct.unpack_from('<I4si', buf, pos + 4)
                if gsize < GRP_HDR:
                    raise SystemExit(f'{self.name}: GRUP at {pos} is {gsize} bytes')
                grp = Group(gtype, bytes(label), bytes(buf[pos + 16:pos + 24]))
                self._parse(buf, pos + GRP_HDR, pos + gsize, grp.items)
                out[_grp_key(gtype, bytes(label))] = grp
                pos += gsize
                continue
            sig = bytes(buf[pos:pos + 4]).decode('ascii', 'replace')
            dsize, flags, fid = struct.unpack_from('<III', buf, pos + 4)
            hdr = bytearray(buf[pos:pos + REC_HDR])
            data = bytes(buf[pos + REC_HDR:pos + REC_HDR + dsize])
            if flags & FLAG_COMPRESSED:
                # Rewritten uncompressed, so the stale flag has to go with it.
                data = zlib.decompress(data[4:])
                struct.pack_into('<I', hdr, 8, flags & ~FLAG_COMPRESSED)
            out[_rec_key(fid)] = Record(
                sig, fid, bytes(hdr), read_subrecords(data), self.name,
                (fid >> 24) == self.own_index)
            pos += REC_HDR + dsize

    def records(self, items=None):
        """Every record in the tree, depth first."""
        items = self.top if items is None else items
        for item in items.values():
            if isinstance(item, Group):
                yield from self.records(item.items)
            else:
                yield item

    def records_with_chain(self, items=None, chain=()):
        """(record, chain) -- the enclosing GRUPs, outermost first."""
        items = self.top if items is None else items
        for item in items.values():
            if isinstance(item, Group):
                yield from self.records_with_chain(
                    item.items, chain + ((item.gtype, item.label),))
            else:
                yield item, chain


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------

def merged_master_list(plugins, drop):
    """The union of every input's masters, minus the plugins being merged.

    Officials in Bethesda's order, then Creation Club, then remaining ESMs,
    then ESPs -- within each bucket, the order the inputs first named them.
    """
    seen = OrderedDict()
    for plugin in plugins:
        for name in plugin.masters:
            if name.lower() in drop:
                continue
            seen.setdefault(name.lower(), name)
    officials, cc, esm, esp = [], [], [], []
    for name in seen.values():
        low = name.lower()
        if low in OFFICIAL_ORDER:
            officials.append(name)
        elif low.startswith('cc'):
            cc.append(name)
        elif low.endswith('.esm'):
            esm.append(name)
        else:
            esp.append(name)
    officials.sort(key=lambda n: OFFICIAL_ORDER.index(n.lower()))
    cc.sort(key=str.lower)
    return officials + cc + esm + esp


def build_mapping(plugin, index_of, own_index, drop, cut=()):
    """index -> index, taking this plugin's FormIDs into the merged file's.

    A master in `cut` gets NO entry, so remapping anything that references it
    raises -- which is how the caller finds what cannot survive the cut.
    """
    mapping = {}
    for i, name in enumerate(plugin.masters):
        low = name.lower()
        if low in cut:
            continue
        if low in drop:
            mapping[i] = own_index          # a master that is now part of us
        elif low in index_of:
            mapping[i] = index_of[low]
        else:
            raise SystemExit(f'{plugin.name} masters "{name}", which the merged '
                             'master list does not contain')
    mapping[plugin.own_index] = own_index
    return mapping


# ---------------------------------------------------------------------------
# Remap + merge
# ---------------------------------------------------------------------------

def remap_tree(items, mapping, form_version=None):
    """Rewrite every record and every FormID-labelled GRUP into the new space."""
    out = OrderedDict()
    for key, item in items.items():
        if isinstance(item, Group):
            label = item.label
            if item.gtype in FORMID_LABEL_TYPES:
                fid = struct.unpack('<I', label)[0]
                label = struct.pack('<I', remap_fid(fid, mapping, 'GRUP label'))
            grp = Group(item.gtype, label, item.stamp)
            grp.items = remap_tree(item.items, mapping, form_version)
            out[_grp_key(grp.gtype, label)] = grp
        else:
            hdr, subs = remap_record(item.sig, item.header, item.subs, mapping,
                                     form_version=form_version)
            fid = struct.unpack_from('<I', hdr, 12)[0]
            out[_rec_key(fid)] = Record(item.sig, fid, hdr, subs, item.source,
                                        item.authored)
    return out


def merge_tree(dst, src, stats):
    """Fold `src` into `dst`. A record in both is taken from `src`."""
    for key, item in src.items():
        have = dst.get(key)
        if isinstance(item, Group):
            if have is None:
                dst[key] = item
            else:
                merge_tree(have.items, item.items, stats)
            continue
        if have is None:
            dst[key] = item
            if item.authored:
                stats['authored'][item.fid] = item.source
            continue
        owner = stats['authored'].get(item.fid)
        if item.authored and owner is not None and owner != item.source:
            stats['collisions'].append((item.fid, owner, item.source, item.sig))
        stats['overrides'].append((item.fid, item.sig, have.source, item.source))
        dst[key] = item                      # keeps the original position
        if item.authored:
            stats['authored'][item.fid] = item.source


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def record_bytes(rec):
    data = build_subrecords(rec.subs)
    hdr = bytearray(rec.header)
    struct.pack_into('<I', hdr, 4, len(data))
    struct.pack_into('<I', hdr, 12, rec.fid)
    return bytes(hdr) + data


def items_bytes(items):
    out = bytearray()
    for item in items.values():
        out += group_bytes(item) if isinstance(item, Group) else record_bytes(item)
    return bytes(out)


def group_bytes(grp):
    body = items_bytes(grp.items)
    out = bytearray(b'GRUP')
    out += struct.pack('<I', GRP_HDR + len(body))
    out += grp.label
    out += struct.pack('<i', grp.gtype)
    out += grp.stamp
    return bytes(out) + body


def count_items(items):
    records = groups = 0
    for item in items.values():
        if isinstance(item, Group):
            groups += 1
            r, g = count_items(item.items)
            records += r
            groups += g
        else:
            records += 1
    return records, groups


def header_bytes(base, masters, onam, record_count, next_object_id):
    """The output's TES4 header: `base`'s, with masters/HEDR/ONAM replaced.

    Everything else the author wrote -- CNAM, SNAM, INTV, INCC -- is kept, in
    the order the CK writes it: HEDR, CNAM, SNAM, MAST/DATA pairs, ONAM, INTV.
    """
    kept = [(s, p) for s, p in base.header_subs
            if s not in ('HEDR', 'MAST', 'DATA', 'ONAM')]
    hedr = next(p for s, p in base.header_subs if s == 'HEDR')
    hedr = hedr[:4] + struct.pack('<II', record_count, next_object_id) + hedr[12:]
    subs = [('HEDR', hedr)]
    subs += [(s, p) for s, p in kept if s in ('CNAM', 'SNAM')]
    for name in masters:
        subs.append(('MAST', name.encode('cp1252') + b'\0'))
        subs.append(('DATA', b'\0' * 8))
    if onam:
        subs.append(('ONAM', b''.join(struct.pack('<I', f) for f in onam)))
    subs += [(s, p) for s, p in kept if s not in ('CNAM', 'SNAM')]
    data = build_subrecords(subs)
    hdr = bytearray(b'TES4')
    hdr += struct.pack('<III', len(data), base.header_flags, 0)
    hdr += struct.pack('<IHH', 0, 44, 0)
    return bytes(hdr) + data


def top_rank(key):
    label = key[2].decode('ascii', 'replace')
    return (GROUP_ORDER.index(label) if label in GROUP_ORDER else len(GROUP_ORDER))


# ---------------------------------------------------------------------------
# Cutting a master loose
# ---------------------------------------------------------------------------

def describe(rec):
    name = ''
    for sig, payload in rec.subs:
        if sig in ('FULL', 'EDID') and not name:
            name = zstring(payload)
    return f'{rec.sig} {rec.fid:08X} {name}'.rstrip()


def _needs(rec, probe):
    """True if any FormID in `rec` points at an index missing from `probe`."""
    try:
        remap_record(rec.sig, rec.header, rec.subs, probe, form_version=None)
    except SystemExit:
        return True
    return False


def prune_masters(items, dropped, probe, removed):
    """Remove everything that cannot exist without the dropped masters.

    Three things bind a plugin to a master, and all three are here:
      * a record OVERRIDING one of its records (its FormID carries that index);
      * a GRUP labelled with one of its FormIDs -- a cell-children or
        world-children group, which is how a placed reference gets INTO
        somebody else's cell, so everything inside goes with it;
      * a surviving record still REFERENCING it from a subrecord.
    An emptied group is dropped too: the CK never writes one.
    """
    for key in list(items):
        item = items[key]
        if isinstance(item, Group):
            if (item.gtype in FORMID_LABEL_TYPES
                    and (struct.unpack('<I', item.label)[0] >> 24) in dropped):
                fid = struct.unpack('<I', item.label)[0]
                removed.append(('group', item.gtype, fid,
                                list(_walk(item.items))))
                del items[key]
                continue
            prune_masters(item.items, dropped, probe, removed)
            if not item.items:
                del items[key]
            continue
        if (item.fid >> 24) in dropped or _needs(item, probe):
            removed.append(('record', None, item.fid, [item]))
            del items[key]


def cut_masters(merged, masters, dropped_names):
    """Drop `dropped_names` from the master list and everything that needs them.

    Returns (kept masters, the re-indexed tree, what was removed, the index
    remap that re-indexing used). Runs to a
    fixed point: dropping a record can orphan whatever referenced it, and that
    reference is exactly as broken as the first one.
    """
    dropped = {i for i, n in enumerate(masters) if n.lower() in dropped_names}
    own_index = len(masters)
    probe = {i: i for i in range(own_index + 1) if i not in dropped}
    removed = []
    while True:
        before = len(removed)
        prune_masters(merged, dropped, probe, removed)
        if len(removed) == before:
            break
    kept = [n for n in masters if n.lower() not in dropped_names]
    slot = {n.lower(): i for i, n in enumerate(kept)}
    reindex = {i: slot[n.lower()] for i, n in enumerate(masters)
               if n.lower() in slot}
    reindex[own_index] = len(kept)
    return kept, remap_tree(merged, reindex), removed, reindex


def _base_object(rec):
    for sig, payload in rec.subs:
        if sig == 'NAME':
            return struct.unpack('<I', payload)[0]
    return 0


def lost_placements(merged, removed, reindex):
    """NPCs that HAD a placement and no longer have one, after the cut.

    Not the same as 'has no ACHR': several of these NPCs were never placed by
    these plugins in the first place, and saying the cut unplaced them would be
    a lie.
    """
    still = {_base_object(r) for r in _walk(merged) if r.sig == 'ACHR'}
    npcs = {r.fid: r for r in _walk(merged) if r.sig == 'NPC_'}
    lost = []
    for _kind, _gtype, _fid, records in removed:
        for rec in records:
            if rec.sig != 'ACHR':
                continue
            base = _base_object(rec)
            if (base >> 24) not in reindex:
                continue
            base = remap_fid(base, reindex, 'ACHR')
            if base not in still and base not in [x for x, _ in lost]:
                lost.append((base, npcs.get(base)))
    return lost


# ---------------------------------------------------------------------------
# The ship gate
# ---------------------------------------------------------------------------

def _tile(buf, pos, end, counts, trail):
    """Every byte of [pos, end) is either a record or a GRUP, nesting exactly."""
    while pos < end:
        if pos + REC_HDR > end:
            trail.append(f'{end - pos} trailing bytes at {pos}')
            return
        if bytes(buf[pos:pos + 4]) == b'GRUP':
            gsize = struct.unpack_from('<I', buf, pos + 4)[0]
            if gsize < GRP_HDR or pos + gsize > end:
                trail.append(f'GRUP at {pos} claims {gsize} bytes')
                return
            counts['groups'] += 1
            _tile(buf, pos + GRP_HDR, pos + gsize, counts, trail)
            pos += gsize
            continue
        dsize, flags, _fid = struct.unpack_from('<III', buf, pos + 4)
        if pos + REC_HDR + dsize > end:
            trail.append(f'record at {pos} claims {dsize} bytes')
            return
        if not flags & FLAG_COMPRESSED:
            data = buf[pos + REC_HDR:pos + REC_HDR + dsize]
            q = 0
            while q + SUB_HDR <= len(data):
                q += SUB_HDR + struct.unpack_from('<H', data, q + 4)[0]
            if q != len(data):
                trail.append(f'record at {pos}: subrecords fill {q} of {dsize}')
        counts['records'] += 1
        pos += REC_HDR + dsize


def verify(out_path, plugins, masters, drop, dropped_names=frozenset()):
    """Prove the merged file before it ships. Returns the number of failures."""
    own_index = len(masters)
    buf = Path(out_path).read_bytes()
    failures = 0

    def check(name, ok, detail=''):
        nonlocal failures
        print(f'  {"PASS" if ok else "FAIL"}  {name:<10} {detail}')
        if not ok:
            failures += 1

    hsize = struct.unpack_from('<I', buf, 4)[0]
    counts = {'records': 0, 'groups': 0}
    trail = []
    _tile(buf, REC_HDR + hsize, len(buf), counts, trail)
    check('structure', not trail, '; '.join(trail) or
          f'{counts["records"]} records, {counts["groups"]} groups tile exactly')

    hedr = next(p for s, p in read_subrecords(buf[REC_HDR:REC_HDR + hsize])
                if s == 'HEDR')
    stated = struct.unpack_from('<I', hedr, 4)[0]
    want = counts['records'] + counts['groups']
    check('hedr', stated == want, f'{stated} (records + groups = {want})')

    merged = Plugin(out_path)
    labels = [k[2].decode('ascii', 'replace') for k in merged.top]
    ranked = sorted(labels, key=lambda l: top_rank(('G', 0, l.encode())))
    check('groups', labels == ranked, ' '.join(labels))
    check('masters', merged.masters == masters, ', '.join(merged.masters))

    # An identity remap over the merged file's own index space: remap_fid
    # aborts on a FormID pointing PAST the last master, which is exactly the
    # stale-index bug this tool exists to avoid, and the walk re-derives every
    # byte of every subrecord that carries a FormID.
    identity = {i: i for i in range(own_index + 1)}
    bad = []
    total = 0
    for rec in _walk(merged.top):
        total += 1
        try:
            _hdr, subs = remap_record(rec.sig, rec.header, rec.subs, identity,
                                      form_version=None)
        except SystemExit as exc:
            bad.append(f'{rec.sig} {rec.fid:08X}: {exc}')
            continue
        if subs != rec.subs:
            bad.append(f'{rec.sig} {rec.fid:08X} is not stable under identity')
    check('formids', not bad, '; '.join(bad[:4]) or
          f'every FormID in {total} records lands on a listed master')

    # Fidelity: the winner of every input record is that record, byte for byte,
    # with only its master indexes moved. A record that needed a master the run
    # CUT LOOSE is expected to be gone -- and is checked to be gone, not merely
    # excused.
    index_of = {n.lower(): i for i, n in enumerate(masters)}
    got = {rec.fid: rec for rec in _walk(merged.top)}
    winner, expect_gone = {}, {}
    for plugin in plugins:
        mapping = build_mapping(plugin, index_of, own_index, drop, dropped_names)
        for rec, chain in plugin.records_with_chain():
            cut_chain = any(
                gtype in FORMID_LABEL_TYPES
                and plugin.masters[i].lower() in dropped_names
                for gtype, label in chain
                for i in [struct.unpack('<I', label)[0] >> 24]
                if i < len(plugin.masters))
            try:
                fid = remap_fid(rec.fid, mapping, rec.sig)
            except SystemExit:
                continue                    # its own FormID belonged to a cut master
            try:
                _hdr, subs = remap_record(rec.sig, rec.header, rec.subs, mapping,
                                          form_version=None)
            except SystemExit:
                expect_gone[fid] = f'{rec.sig} {fid:08X} from {plugin.name}'
                continue
            if cut_chain:
                expect_gone[fid] = f'{rec.sig} {fid:08X} from {plugin.name}'
            else:
                winner[fid] = (plugin.name, rec.sig, subs)
    missing, differ = [], []
    for fid, (name, sig, subs) in winner.items():
        have = got.get(fid)
        if have is None:
            missing.append(f'{sig} {fid:08X} from {name} is not in the output')
        elif have.subs != subs:
            differ.append(f'{sig} {fid:08X} from {name} was altered')
    check('fidelity', not missing and not differ,
          '; '.join((missing + differ)[:4]) or
          f'{len(winner)} records match their source byte for byte')
    if dropped_names:
        alive = [text for fid, text in expect_gone.items() if fid in got]
        check('cut', not alive, '; '.join(alive[:4]) or
              f'{len(expect_gone)} records needing '
              f'{", ".join(sorted(dropped_names))} are gone')
    return failures


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def merge(paths, out_path, dry_run=False, no_verify=False,
          cut_masters_named=()):
    plugins = [Plugin(p) for p in paths]
    out_path = Path(out_path)
    drop = {p.name.lower() for p in plugins} | {out_path.name.lower()}
    masters = merged_master_list(plugins, drop)
    index_of = {n.lower(): i for i, n in enumerate(masters)}
    own_index = len(masters)

    print(f'merging {len(plugins)} plugins into {out_path.name}')
    for plugin in plugins:
        print(f'  {plugin.name:<32} masters={plugin.masters}')
    print(f'\nmerged master list ({len(masters)}), own index {own_index:02X}:')
    for i, name in enumerate(masters):
        print(f'  {i:02X}  {name}')

    merged = OrderedDict()
    stats = {'authored': {}, 'collisions': [], 'overrides': []}
    onam = []
    for plugin in plugins:
        mapping = build_mapping(plugin, index_of, own_index, drop)
        moved = {k: v for k, v in mapping.items() if k != v}
        print(f'\n{plugin.name}: index remap {mapping}'
              f'{"" if moved else "  (identity)"}')
        # An identity mapping needs no field knowledge at all: nothing moved,
        # so every record is already in the merged file's FormID space.
        tree = plugin.top if not moved else remap_tree(plugin.top, mapping)
        onam += [remap_fid(f, mapping, 'ONAM') for f in plugin.onam]
        merge_tree(merged, tree, stats)
        records, groups = count_items(merged)
        print(f'  after merge: {records} records, {groups} groups')

    if stats['overrides']:
        print(f'\n{len(stats["overrides"])} records taken from the later plugin:')
        for fid, sig, was, now in stats['overrides']:
            print(f'  {sig} {fid:08X}  {was} -> {now}')
    if stats['collisions']:
        print(f'\n{len(stats["collisions"])} FORMID COLLISIONS -- two plugins '
              'author the same object ID:')
        for fid, a, b, sig in stats['collisions']:
            print(f'  {sig} {fid:08X}  authored by BOTH {a} and {b}')
        raise SystemExit('refusing to merge: one record would silently replace '
                         'a different record. Renumber one of them first.')

    dropped_names = {n.lower() for n in cut_masters_named}
    unknown = dropped_names - {n.lower() for n in masters}
    if unknown:
        raise SystemExit(f'--drop-master names {sorted(unknown)}, which the '
                         f'merged file does not master anyway')
    if dropped_names:
        before = count_items(merged)[0]
        masters, merged, removed, reindex = cut_masters(
            merged, masters, dropped_names)
        index_of = {n.lower(): i for i, n in enumerate(masters)}
        own_index = len(masters)
        onam = [remap_fid(f, reindex, 'ONAM') for f in onam
                if (f >> 24) in reindex]
        print(f'\ncut loose: {", ".join(sorted(cut_masters_named))}')
        print(f'  {before - count_items(merged)[0]} records removed:')
        for kind, gtype, fid, records in removed:
            if kind == 'group':
                print(f'    GRUP type {gtype} of {fid:08X} -- '
                      f'{len(records)} records inside:')
                for rec in records:
                    print(f'        {describe(rec)}')
            else:
                print(f'    {describe(records[0])}')
        lost = lost_placements(merged, removed, reindex)
        if lost:
            print(f'  {len(lost)} NPCs lost their only placement (the NPC_ '
                  'record survives; nothing in the world spawns it now):')
            for fid, rec in lost:
                print(f'    {describe(rec) if rec else format(fid, "08X")}')

    ordered = OrderedDict(sorted(merged.items(), key=lambda kv: top_rank(kv[0])))
    records, groups = count_items(ordered)
    next_object_id = max(p.next_object_id for p in plugins)
    used = max((r.fid & 0xFFFFFF) for r in _walk(ordered)
               if (r.fid >> 24) == own_index) + 1
    next_object_id = max(next_object_id, used)

    body = items_bytes(ordered)
    head = header_bytes(plugins[0], masters, sorted(set(onam)),
                        records + groups, next_object_id)

    print(f'\n{records} records, {groups} groups, next object id '
          f'{next_object_id:08X}')
    by_sig = {}
    for rec in _walk(ordered):
        by_sig[rec.sig] = by_sig.get(rec.sig, 0) + 1
    print('  ' + ', '.join(f'{s} {n}' for s, n in sorted(by_sig.items())))

    if dry_run:
        print('\nDRY RUN -- nothing written')
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(head + body)
    print(f'\nwrote {out_path}  ({len(head) + len(body)} bytes)')
    if no_verify:
        return 0
    print('\nverifying:')
    failures = verify(out_path, plugins, masters, drop, dropped_names)
    if failures:
        raise SystemExit(f'{failures} check(s) FAILED -- do not ship this file')
    return 0


def _walk(items):
    for item in items.values():
        if isinstance(item, Group):
            yield from _walk(item.items)
        else:
            yield item


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plugins', nargs='+',
                    help='the plugins to merge, IN LOAD ORDER (later wins)')
    ap.add_argument('--out', required=True,
                    help='the merged plugin; its FILENAME is the plugin identity')
    ap.add_argument('--dry-run', action='store_true',
                    help='report only; write nothing')
    ap.add_argument('--drop-master', action='append', default=[], metavar='NAME',
                    help='cut this master loose: every record and every placed '
                         'reference that needs it is removed (repeatable)')
    ap.add_argument('--no-verify', action='store_true',
                    help='skip the ship gate (it is cheap; only for debugging)')
    args = ap.parse_args()
    if len(args.plugins) < 2:
        ap.error('give at least two plugins to merge')
    return merge(args.plugins, args.out, args.dry_run, args.no_verify,
                 args.drop_master)


if __name__ == '__main__':
    sys.exit(main())
