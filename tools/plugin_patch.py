#!/usr/bin/env python3
"""Read TES5 plugins and build NPC_ override records inside a patch plugin.

Shared by the `assign_*` patch tools. The model is xEdit's "copy as override":
the record written into the patch IS the master's record, byte for byte, with
only its FormID master indexes remapped into the patch's load order and the
fields the tool is responsible for substituted. A field the tool never touches
cannot drift.

`Patch` keeps every group the patch already had as raw bytes and rebuilds only
the NPC_ group, so running two of these tools one after the other accumulates
edits on the same records instead of one clobbering the other.
"""

import struct
import zlib
from collections import OrderedDict
from pathlib import Path

REC_HDR = 24
GRP_HDR = 24
SUB_HDR = 6
FLAG_COMPRESSED = 0x00040000

ACBS_FEMALE = 0x00000001

# Canonical top-level GRUP order (xEdit / Creation Kit). Used only to insert a
# new group where the game's own masters would have put it.
GROUP_ORDER = [
    'GMST', 'KYWD', 'LCRT', 'AACT', 'TXST', 'GLOB', 'CLAS', 'FACT', 'HDPT',
    'EYES', 'RACE', 'SOUN', 'ASPC', 'MGEF', 'SCPT', 'LTEX', 'ENCH', 'SPEL',
    'SCRL', 'ACTI', 'TACT', 'ARMO', 'BOOK', 'CONT', 'DOOR', 'INGR', 'LIGH',
    'MISC', 'APPA', 'STAT', 'SCOL', 'MSTT', 'PWAT', 'GRAS', 'TREE', 'CLDC',
    'FLOR', 'FURN', 'WEAP', 'AMMO', 'NPC_', 'LVLN', 'KEYM', 'ALCH', 'IDLM',
    'COBJ', 'PROJ', 'HAZD', 'SLGM', 'LVLI', 'WTHR', 'CLMT', 'SPGD', 'RFCT',
    'REGN', 'NAVI', 'CELL', 'WRLD', 'DIAL', 'QUST', 'IDLE', 'PACK', 'CSTY',
    'LSCR', 'LVSP', 'ANIO', 'WATR', 'EFSH', 'EXPL', 'DEBR', 'IMGS', 'IMAD',
    'FLST', 'PERK', 'BPTD', 'ADDN', 'AVIF', 'CAMS', 'CPTH', 'VTYP', 'MATT',
    'IPCT', 'IPDS', 'ARMA', 'ECZN', 'LCTN', 'MESG', 'RGDL', 'DOBJ', 'LGTM',
    'MUST', 'DLVW', 'WOOP', 'SHOU', 'EQUP', 'RELA', 'SCEN', 'ASTP', 'OTFT',
    'ARTO', 'MATO', 'MOVT', 'SNDR', 'DUAL', 'SNCT', 'SOPM', 'COLL', 'CLFM',
    'REVB',
]

# ---------------------------------------------------------------------------
# NPC_ subrecords: where FormIDs live.
#
# An unknown signature aborts the run rather than being copied with a stale
# master index, which would be a silently broken reference.
# ---------------------------------------------------------------------------

# signature -> (first FormID offset, stride). One FormID per stride-sized entry.
NPC_FORMID_FIELDS = {
    'TPLT': (0, 4), 'RNAM': (0, 4), 'VTCK': (0, 4), 'CNAM': (0, 4),
    'DOFT': (0, 4), 'SOFT': (0, 4), 'DPLT': (0, 4), 'HCLF': (0, 4),
    'ZNAM': (0, 4), 'INAM': (0, 4), 'PKID': (0, 4), 'SPLO': (0, 4),
    'PNAM': (0, 4), 'CSDI': (0, 4), 'WNAM': (0, 4), 'ANAM': (0, 4),
    'ATKR': (0, 4), 'CRIF': (0, 4), 'FTST': (0, 4), 'GNAM': (0, 4),
    'ECOR': (0, 4), 'DEFA': (0, 4), 'CSCR': (0, 4), 'SPOR': (0, 4),
    'OCOR': (0, 4), 'GWOR': (0, 4), 'KWDA': (0, 4),
    'CNTO': (0, 8),   # item FormID + count
    'SNAM': (0, 8),   # faction FormID + rank
    'PRKR': (0, 8),   # perk FormID + rank
}

# Carries no FormID at all.
NPC_PLAIN_FIELDS = {
    'EDID', 'OBND', 'ACBS', 'AIDT', 'DATA', 'DNAM', 'FULL', 'SHRT',
    'NAM5', 'NAM6', 'NAM7', 'NAM8', 'NAM9', 'NAMA', 'COCT', 'SPCT', 'PRKZ',
    'QNAM', 'TINI', 'TINC', 'TINV', 'TIAS', 'CSDT', 'CSDC', 'KSIZ',
    'ATKD', 'ATKE',
}

NPC_STRUCTURED_FIELDS = {'VMAD'}

# Canonical NPC_ field order, verified against the Skyrim.esm dump:
#   ... DNAM, PNAM(x), HCLF, ZNAM, GNAM, NAM5, NAM6, NAM7, NAM8,
#   CSDT/CSDI/CSDC, CSCR, DOFT, SOFT, DPLT, CRIF, FTST, QNAM, NAM9, NAMA,
#   TINI/TINC/TINV/TIAS
AFTER_PNAM = ('HCLF', 'ZNAM', 'GNAM', 'NAM5', 'NAM6', 'NAM7', 'NAM8',
              'CSDT', 'CSDI', 'CSDC', 'CSCR', 'DOFT', 'SOFT', 'DPLT',
              'CRIF', 'FTST', 'QNAM', 'NAM9', 'NAMA',
              'TINI', 'TINC', 'TINV', 'TIAS')
AFTER_DOFT = ('SOFT', 'DPLT', 'CRIF', 'FTST', 'QNAM', 'NAM9', 'NAMA',
              'TINI', 'TINC', 'TINV', 'TIAS')
AFTER_QNAM = ('NAM9', 'NAMA', 'TINI', 'TINC', 'TINV', 'TIAS')


# ---------------------------------------------------------------------------
# Subrecord / record plumbing
# ---------------------------------------------------------------------------

def read_subrecords(data):
    """[(sig, payload)] from a record's data blob."""
    subs = []
    pos, n = 0, len(data)
    while pos + SUB_HDR <= n:
        sig = data[pos:pos + 4].decode('ascii', 'replace')
        size = struct.unpack_from('<H', data, pos + 4)[0]
        pos += SUB_HDR
        if pos + size > n:
            break
        subs.append((sig, bytes(data[pos:pos + size])))
        pos += size
    return subs


def build_subrecords(subs):
    out = bytearray()
    for sig, payload in subs:
        out += sig.encode('ascii')
        out += struct.pack('<H', len(payload))
        out += payload
    return bytes(out)


def first(subs, sig):
    for s, payload in subs:
        if s == sig:
            return payload
    return None


def zstring(payload):
    return payload.split(b'\0')[0].decode('cp1252') if payload else ''


def read_masters(buf):
    """Master file names, in load order, from a plugin's TES4 header."""
    size = struct.unpack_from('<I', buf, 4)[0]
    return [zstring(payload)
            for sig, payload in read_subrecords(buf[REC_HDR:REC_HDR + size])
            if sig == 'MAST']


def iter_records(buf, want_types):
    """Yield (sig, form_id, header, data, parent_cell, parent_wrld).

    Walks the whole GRUP tree; only records whose signature is in want_types
    have their bytes returned.
    """
    size = struct.unpack_from('<I', buf, 4)[0]
    ends = []
    saved = []
    pos = REC_HDR + size
    end = len(buf)
    parent_cell = parent_wrld = 0

    while pos < end:
        while ends and pos >= ends[-1]:
            ends.pop()
            parent_cell, parent_wrld = saved.pop()
        if pos + REC_HDR > end:
            break
        sig = bytes(buf[pos:pos + 4])
        if sig == b'GRUP':
            gsize, label, gtype = struct.unpack_from('<I4si', buf, pos + 4)
            saved.append((parent_cell, parent_wrld))
            if gtype == 1:                       # world children
                parent_wrld = struct.unpack('<I', label)[0]
            elif gtype in (6, 8, 9, 10):         # cell children
                parent_cell = struct.unpack('<I', label)[0]
            ends.append(pos + gsize)
            pos += GRP_HDR
            continue
        dsize, flags, fid = struct.unpack_from('<III', buf, pos + 4)
        stype = sig.decode('ascii', 'replace')
        if stype in want_types:
            hdr = bytearray(buf[pos:pos + REC_HDR])
            data = bytes(buf[pos + REC_HDR:pos + REC_HDR + dsize])
            if flags & FLAG_COMPRESSED:
                # Rewritten records are emitted uncompressed, so drop the flag
                # here rather than carrying a stale one into the patch.
                data = zlib.decompress(data[4:])
                struct.pack_into('<I', hdr, 8, flags & ~FLAG_COMPRESSED)
            yield (stype, fid, bytes(hdr), data, parent_cell, parent_wrld)
        pos += REC_HDR + dsize


def top_level_groups(buf):
    """[(label, start, size)] for the plugin's top-level GRUPs."""
    size = struct.unpack_from('<I', buf, 4)[0]
    pos = REC_HDR + size
    out = []
    while pos < len(buf):
        gsize, label = struct.unpack_from('<I4s', buf, pos + 4)
        out.append((label.decode('ascii', 'replace'), pos, gsize))
        pos += gsize
    return out


# ---------------------------------------------------------------------------
# FormID remapping
# ---------------------------------------------------------------------------

def make_remap(source_masters, patch_masters, source_name):
    """index -> index, taking FormIDs from one plugin's space into the patch's.

    A FormID's high byte indexes the plugin's own master list, with the plugin
    itself one past the end.
    """
    order = {name.lower(): i for i, name in enumerate(patch_masters)}
    mapping = {}
    for i, name in enumerate(source_masters):
        if name.lower() not in order:
            raise SystemExit(f'{source_name} depends on master "{name}", which '
                             'the patch does not list; add it to the patch first')
        mapping[i] = order[name.lower()]
    if source_name.lower() not in order:
        raise SystemExit(f'the patch does not list "{source_name}" as a master')
    mapping[len(source_masters)] = order[source_name.lower()]
    return mapping


def remap_fid(fid, mapping):
    idx = fid >> 24
    new = mapping.get(idx)
    if new is None:
        raise SystemExit(f'FormID {fid:08X} uses master index {idx}, past the '
                         'source plugin\'s own master list')
    return (new << 24) | (fid & 0x00FFFFFF)


def _wstring_end(buf, pos):
    return pos + 2 + struct.unpack_from('<H', buf, pos)[0]


def vmad_formid_offsets(vmad):
    """Byte offsets of every Object-property FormID inside a VMAD blob."""
    ver, objfmt = struct.unpack_from('<hh', vmad, 0)
    if objfmt not in (1, 2):
        raise SystemExit(f'VMAD object format {objfmt} not understood')
    offsets = []

    def value(p, ptype):
        if ptype == 1:
            offsets.append(p if objfmt == 1 else p + 4)
            return p + 8
        if ptype == 2:
            return _wstring_end(vmad, p)
        if ptype in (3, 4):
            return p + 4
        if ptype == 5:
            return p + 1
        raise SystemExit(f'VMAD property type {ptype} not understood')

    pos = 4
    nscripts = struct.unpack_from('<H', vmad, pos)[0]
    pos += 2
    for _ in range(nscripts):
        pos = _wstring_end(vmad, pos)
        if ver >= 4:
            pos += 1                                # script flags
        nprops = struct.unpack_from('<H', vmad, pos)[0]
        pos += 2
        for _ in range(nprops):
            pos = _wstring_end(vmad, pos)
            ptype = vmad[pos]
            pos += 2                                # type + status
            if ptype <= 5:
                pos = value(pos, ptype)
            elif 11 <= ptype <= 15:
                count = struct.unpack_from('<I', vmad, pos)[0]
                pos += 4
                for _ in range(count):
                    pos = value(pos, ptype - 10)
            else:
                raise SystemExit(f'VMAD property type {ptype} not understood')
    if pos != len(vmad):
        raise SystemExit(f'VMAD walk consumed {pos} of {len(vmad)} bytes')
    return offsets


def remap_npc_subrecord(sig, payload, mapping):
    if sig in NPC_PLAIN_FIELDS:
        return payload
    if sig in NPC_STRUCTURED_FIELDS:
        buf = bytearray(payload)
        for off in vmad_formid_offsets(payload):
            fid = struct.unpack_from('<I', buf, off)[0]
            struct.pack_into('<I', buf, off, remap_fid(fid, mapping))
        return bytes(buf)
    field = NPC_FORMID_FIELDS.get(sig)
    if field is None:
        raise SystemExit(f'NPC_ subrecord "{sig}" is not in the FormID map; add '
                         'it before running (a wrong master index here is a '
                         'silently broken reference)')
    firstoff, stride = field
    if len(payload) % stride:
        raise SystemExit(f'{sig} is {len(payload)} bytes, not a multiple of {stride}')
    buf = bytearray(payload)
    for base in range(0, len(buf), stride):
        off = base + firstoff
        fid = struct.unpack_from('<I', buf, off)[0]
        struct.pack_into('<I', buf, off, remap_fid(fid, mapping))
    return bytes(buf)


def remap_npc_record(header, subs, mapping):
    """(header, subs) copied from a master into the patch's FormID space."""
    new_subs = [(sig, remap_npc_subrecord(sig, payload, mapping))
                for sig, payload in subs]
    fid = struct.unpack_from('<I', header, 12)[0]
    hdr = bytearray(header)
    struct.pack_into('<I', hdr, 12, remap_fid(fid, mapping))
    return bytes(hdr), new_subs


# ---------------------------------------------------------------------------
# Ordered field insertion
# ---------------------------------------------------------------------------

def insert_run(subs, sig, payloads, successors):
    """Replace every `sig` subrecord with `payloads`, keeping canonical order.

    The run goes where the first existing `sig` was; failing that, immediately
    before the first subrecord listed in `successors`; failing that, at the end.
    """
    at = next((i for i, (s, _) in enumerate(subs) if s == sig), None)
    kept = [(s, p) for s, p in subs if s != sig]
    if at is None:
        at = next((i for i, (s, _) in enumerate(kept) if s in successors),
                  len(kept))
    else:
        at = len([1 for s, _ in subs[:at] if s != sig])
    run = [(sig, p) for p in payloads]
    return kept[:at] + run + kept[at:]


# ---------------------------------------------------------------------------
# Source plugin
# ---------------------------------------------------------------------------

class SourcePlugin:
    """A plugin read for its records, indexed by type."""

    def __init__(self, path, want_types):
        self.path = Path(path)
        self.name = self.path.name
        buf = self.path.read_bytes()
        self.masters = read_masters(buf)
        self.by_type = {t: OrderedDict() for t in want_types}
        self.parents = {}
        for sig, fid, hdr, data, pcell, pwrld in iter_records(buf, want_types):
            self.by_type[sig][fid] = (hdr, read_subrecords(data))
            self.parents[fid] = (pcell, pwrld)

    def edid(self, fid):
        for table in self.by_type.values():
            if fid in table:
                return zstring(first(table[fid][1], 'EDID'))
        return ''


# ---------------------------------------------------------------------------
# Patch plugin
# ---------------------------------------------------------------------------

class Patch:
    """A patch plugin whose NPC_ group can be extended and re-extended.

    Every other top-level group is carried through as raw bytes, so a second
    tool run adds to the same file without disturbing what the first wrote.
    """

    def __init__(self, path):
        self.path = Path(path)
        buf = self.path.read_bytes()
        self.buf = buf
        self.masters = read_masters(buf)
        hsize = struct.unpack_from('<I', buf, 4)[0]
        self.header = bytes(buf[:REC_HDR + hsize])
        self.groups = OrderedDict()
        self.group_stamp = b'\x00' * 8
        for label, start, size in top_level_groups(buf):
            self.groups[label] = bytes(buf[start:start + size])
            if label == 'NPC_':
                self.group_stamp = bytes(buf[start + 16:start + 24])
        if self.group_stamp == b'\x00' * 8 and self.groups:
            firstgrp = next(iter(self.groups.values()))
            self.group_stamp = firstgrp[16:24]

        self.npcs = OrderedDict()          # fid -> (header, subs)
        if 'NPC_' in self.groups:
            for sig, fid, hdr, data, _c, _w in iter_records(
                    self._as_plugin(self.groups['NPC_']), {'NPC_'}):
                self.npcs[fid] = (hdr, read_subrecords(data))

    def _as_plugin(self, group_bytes):
        """A minimal buffer iter_records can walk: header record + one group."""
        return self.header + group_bytes

    def records_of(self, sig):
        """Parsed records of a non-NPC_ group, keyed by FormID."""
        out = OrderedDict()
        if sig in self.groups:
            for _s, fid, hdr, data, _c, _w in iter_records(
                    self._as_plugin(self.groups[sig]), {sig}):
                out[fid] = (hdr, read_subrecords(data))
        return out

    def set_npc(self, fid, header, subs):
        self.npcs[fid] = (header, subs)

    def write(self, out_path):
        body = bytearray()
        for fid, (hdr, subs) in self.npcs.items():
            data = build_subrecords(subs)
            rec = bytearray(hdr)
            struct.pack_into('<I', rec, 4, len(data))
            struct.pack_into('<I', rec, 12, fid)
            body += rec + data
        group = bytearray(b'GRUP')
        group += struct.pack('<I', GRP_HDR + len(body))
        group += b'NPC_'
        group += struct.pack('<i', 0)
        group += self.group_stamp
        group += body
        self.groups['NPC_'] = bytes(group)

        def rank(label):
            return (GROUP_ORDER.index(label) if label in GROUP_ORDER
                    else len(GROUP_ORDER))

        out = bytearray(self.header)
        records = 0
        grups = 0
        for label in sorted(self.groups, key=rank):
            out += self.groups[label]
        for label, blob in self.groups.items():
            r, g = _count_group(blob)
            records += r
            grups += g

        # HEDR "number of records" counts every record OUTSIDE the file header
        # plus every GRUP -- measured against this patch, Apachii_Divine-
        # EleganceStore.esm and KS Hairdo's.esp, which all agree.
        hsize = struct.unpack_from('<I', out, 4)[0]
        pos = REC_HDR
        while pos + SUB_HDR <= REC_HDR + hsize:
            sig = bytes(out[pos:pos + 4])
            size = struct.unpack_from('<H', out, pos + 4)[0]
            if sig == b'HEDR':
                struct.pack_into('<I', out, pos + SUB_HDR + 4, records + grups)
                break
            pos += SUB_HDR + size
        else:
            raise SystemExit('patch header has no HEDR subrecord')

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(bytes(out))
        return len(out), records, grups


def _count_group(blob, pos=0, end=None):
    """(records, groups) inside a serialized GRUP, counting nested groups."""
    if end is None:
        end = len(blob)
    records = groups = 0
    while pos < end:
        if blob[pos:pos + 4] == b'GRUP':
            gsize = struct.unpack_from('<I', blob, pos + 4)[0]
            groups += 1
            r, g = _count_group(blob, pos + GRP_HDR, pos + gsize)
            records += r
            groups += g
            pos += gsize
        else:
            dsize = struct.unpack_from('<I', blob, pos + 4)[0]
            records += 1
            pos += REC_HDR + dsize
    return records, groups
