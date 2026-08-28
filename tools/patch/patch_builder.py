#!/usr/bin/env python3
"""Build a patch ESP from scratch, with a master list computed from what it uses.

`plugin_patch.Patch` edits an EXISTING hand-authored ESP: its master list is
fixed, and only the `NPC_` group can be rebuilt. That is right for the cosmetic
passes, which always target the same plugins. It is not enough here, because:

  * which plugins a patch masters depends on which converted plugins the user
    ticked, and on which vanilla races the swap table actually reaches (a patch
    that never uses a Dragonborn race must NOT master Dragonborn.esm, or it
    stops loading for anyone without the DLC);
  * a creature swap has to override records other than `NPC_` -- `LVLN` to pull
    a deleted creature out of the leveled lists, and `ACHR` to switch off the
    ones placed by hand.

`ACHR` is the awkward one: a placed reference lives at the bottom of a GRUP
chain (`CELL -> block -> sub-block -> cell children -> temporary children`, or
`WRLD -> world children -> exterior block -> sub-block -> ...`). Rather than
DERIVING that nesting from block-numbering rules, this module READS the chain
the source plugin already uses and rebuilds it verbatim -- the authored answer,
not a reconstruction. `iter_records_chained` is what makes that possible.

Everything else follows `plugin_patch`'s model and its two rules: a record is
copied byte for byte with only its FormID master indexes remapped, and an
unrecognised subrecord signature ABORTS rather than being written with a stale
master index. Every entry in `FORMID_FIELDS` below was measured against the
plugins in this repo; nothing is there on the strength of a guess.
"""

import struct
import zlib
from collections import OrderedDict
from pathlib import Path

from .plugin_patch import (
    GRP_HDR, GROUP_ORDER, REC_HDR, FLAG_COMPRESSED,
    NPC_FORMID_FIELDS, NPC_PLAIN_FIELDS, NPC_STRUCTURED_FIELDS,
    _count_group, build_subrecords, insert_run, read_masters, read_subrecords,
    vmad_formid_offsets, zstring,
)

# Re-exported: a caller that only imports this module still needs to place a
# new subrecord in canonical field order.
set_field = insert_run

TES4_FORM_VERSION = 44
HEDR_VERSION = 1.71

# Group types that appear in a placed reference's chain.
GT_TOP, GT_WORLD_CHILDREN = 0, 1
GT_INTERIOR_BLOCK, GT_INTERIOR_SUBBLOCK = 2, 3
GT_EXTERIOR_BLOCK, GT_EXTERIOR_SUBBLOCK = 4, 5
GT_CELL_CHILDREN, GT_PERSISTENT, GT_TEMPORARY, GT_DISTANT = 6, 8, 9, 10

# Record flag 0x800 -- Initially Disabled. The engine spawns nothing for a
# reference carrying it, which is how a patch removes a hand-placed actor
# without deleting the record (a deleted record is what breaks other plugins).
FLAG_INITIALLY_DISABLED = 0x00000800
FLAG_PERSISTENT = 0x00000400


# ---------------------------------------------------------------------------
# Where FormIDs live, per record type.
#
# MEASURED, never assumed -- each entry was read out of the converted plugins
# and checked field by field (see docs/python_tools_reference.md). A signature
# absent from BOTH tables for its type aborts the run: writing a subrecord whose
# contents we do not understand is how a patch ships silently broken refs.
# ---------------------------------------------------------------------------

# ACHR and REFR are one record family -- a placed reference -- and share their
# whole subrecord vocabulary, so they share these two tables.
REF_FORMID_FIELDS = {
    'NAME': (0, 4), 'XLCN': (0, 4), 'XEZN': (0, 4), 'XHOR': (0, 4),
    'XLRT': (0, 4), 'XLRM': (0, 4), 'XLRL': (0, 4), 'XOWN': (0, 4),
    'XEMI': (0, 4), 'XLIB': (0, 4), 'XMBR': (0, 4), 'XTRI': (0, 4),
    'XLKR': (0, 4),          # keyword + linked ref, both FormIDs
    'XPOD': (0, 4),          # portal: the two rooms it joins
    'XESP': (0, 8),          # enable parent FormID + flags u32
    'XAPR': (0, 8),          # activate parent FormID + delay float
    'XNDP': (0, 8),          # navmesh FormID + teleport triangle u16 + pad
    'XTEL': (0, 32),         # destination door FormID, then pos/rot/flags
    'XLOC': (4, 20),         # level u8 + pad, KEY FormID, flags, unused
}

REF_PLAIN_FIELDS = {
    'EDID', 'DATA', 'FULL', 'FNAM', 'TNAM', 'XMRK', 'XSCL', 'XRGD', 'XRGB',
    'XPRD', 'XPPA', 'XRDS', 'XAPD', 'XATO', 'XLCM', 'XCNT', 'XCVL', 'XCZA',
    'XCZC', 'XLOD', 'XLIG', 'XALP', 'XACT', 'XWCN', 'XWCU', 'XIS2', 'XPCI',
    'XPTL', 'XRMR', 'XSED', 'XMBO', 'XPRM', 'XSPC',
}

FORMID_FIELDS = {
    'NPC_': dict(NPC_FORMID_FIELDS),
    # LVLO is 12 bytes: level u16, pad u16, FormID u32, count u16, pad u16.
    'LVLN': {'LVLO': (4, 12), 'LVLG': (0, 4)},
    'ACHR': dict(REF_FORMID_FIELDS),
    'REFR': dict(REF_FORMID_FIELDS),
    # XCLR is an array of REGN FormIDs. XEZN is the encounter zone.
    'CELL': {'LTMP': (0, 4), 'XOWN': (0, 4), 'XLCN': (0, 4), 'XCLR': (0, 4),
             'XCWT': (0, 4), 'XCIM': (0, 4), 'XCAS': (0, 4), 'XCCM': (0, 4),
             'XCMO': (0, 4), 'XILL': (0, 4), 'XEZN': (0, 4)},
    # NAM2 water, NAM3 LOD water type, CNAM climate, XLCN location.
    # NAM4 is the LOD water HEIGHT (a float) and must stay plain.
    'WRLD': {'XLCN': (0, 4), 'CNAM': (0, 4), 'NAM2': (0, 4), 'NAM3': (0, 4),
             'WNAM': (0, 4), 'INAM': (0, 4), 'ZNAM': (0, 4), 'LTMP': (0, 4),
             'XEZN': (0, 4)},
    'OTFT': {'INAM': (0, 4)},
    # HNAM extra parts, TNAM base texture set, RNAM valid races, CNAM colour.
    # PNAM (part type) and NAM0 (file type) are ENUMS, not FormIDs -- their
    # small values resolve against Skyrim.esm by coincidence.
    'HDPT': {'HNAM': (0, 4), 'TNAM': (0, 4), 'RNAM': (0, 4), 'CNAM': (0, 4)},
    'TXST': {},
    'RELA': {},
    # A form list is nothing but its entries: one LNAM FormID each.
    'FLST': {'LNAM': (0, 4)},
    # Measured against the real Skyrim.esm on 2026-08-28: CNTO is FormID +
    # count u32 (9,597/9,597 resolve to items, and offset 4 is the count --
    # 8,702 of them are 1); SNAM/QNAM are the open/close SOUNDS (137/137 and
    # 135/135 resolve to SNDR). COED is deliberately ABSENT: Skyrim.esm ships
    # exactly one and it does not resolve, so an unexpected one must abort
    # rather than be copied with a stale master index.
    'CONT': {'CNTO': (0, 8), 'SNAM': (0, 4), 'QNAM': (0, 4)},
    # LVLI is LVLN's shape without the model. Same measurement: LVLO
    # 20,340/20,340 resolve at offset 4, LVLG 65/65 to GLOB.
    'LVLI': {'LVLO': (4, 12), 'LVLG': (0, 4)},
    # Only the vendor half of FACT is mapped, because that is the only half
    # this repo overrides. VEND is the sell-what FormList, VENC the merchant
    # container. PLVD is STRUCTURED, not plain: its value field is a FormID
    # only for some location types (see plvd_formid_offsets).
    # XNAM is a relation: target FormID + int32 modifier + u32 combat
    # reaction, 12 bytes. Measured 1,036/1,036 resolve in Skyrim.esm.
    'FACT': {'VEND': (0, 4), 'VENC': (0, 4), 'XNAM': (0, 12)},
}

PLAIN_FIELDS = {
    'NPC_': set(NPC_PLAIN_FIELDS),
    'LVLN': {'EDID', 'OBND', 'LVLD', 'LVLF', 'LLCT', 'MODL', 'MODT', 'MODS',
             'COED'},
    'ACHR': set(REF_PLAIN_FIELDS),
    'REFR': set(REF_PLAIN_FIELDS),
    # XWEM is the water environment map -- a TEXTURE PATH, not a FormID.
    'CELL': {'EDID', 'FULL', 'DATA', 'XCLL', 'XCLC', 'XCLW', 'XWCN', 'XWCS',
             'XWCU', 'TVDT', 'MHDT', 'XNAM', 'XWEM', 'LNAM'},
    'WRLD': {'EDID', 'FULL', 'DNAM', 'MODL', 'MODT', 'MODS', 'MNAM', 'ONAM',
             'NAMA', 'DATA', 'NAM0', 'NAM9', 'NAM4', 'PNAM', 'ICON', 'WCTR',
             'MHDT', 'OFST', 'XXXX', 'TNAM', 'UNAM', 'XWEM'},
    'OTFT': {'EDID'},
    'FLST': {'EDID', 'OBND'},
    'CONT': {'EDID', 'OBND', 'FULL', 'MODL', 'MODT', 'MODS', 'DATA', 'COCT'},
    'LVLI': {'EDID', 'OBND', 'LVLD', 'LVLF', 'LLCT'},
    'FACT': {'EDID', 'FULL', 'DATA', 'CRVA', 'VENV', 'RNAM', 'MNAM', 'FNAM'},
    'HDPT': {'EDID', 'FULL', 'MODL', 'MODT', 'MODS', 'DATA', 'PNAM', 'NAM0',
             'NAM1'},
    'TXST': {'EDID', 'OBND', 'TX00', 'TX01', 'TX02', 'TX03', 'TX04', 'TX05',
             'TX06', 'TX07', 'DODT', 'DNAM'},
    'RELA': {'EDID'},
}


def plvd_formid_offsets(data):
    """FACT PLVD (Vendor Location): int32 type, u32 value, int32 (always 0).

    The value is a FormID only for the types that name one -- measured over
    Skyrim.esm's 145 vendor factions: type 1 points at a CELL (77 of them),
    type 0 at a REFR (35), and type 12 means "near self" with the value
    always 0 (23). Declaring the field a plain FormID would rewrite that 0
    into `masterIndex << 24` and invent a reference out of nothing.
    """
    if len(data) != 12:
        raise SystemExit(f'FACT PLVD is {len(data)} bytes, expected 12')
    kind, value, _tail = struct.unpack('<iIi', data)
    return [4] if kind in (0, 1) and value else []


def rela_formid_offsets(data):
    """RELA DATA: parent FormID, child FormID, rank u16 + pad u16, ASTP."""
    if len(data) != 16:
        raise SystemExit(f'RELA DATA is {len(data)} bytes, expected 16')
    return [0, 4, 12]


def wrld_rnam_formid_offsets(data):
    """WRLD RNAM 'Large References': cell x/y u16 pair, count u32, then
    `count` entries of (REFR FormID, cell X i16, cell Y i16).

    Measured over every WRLD in Skyrim.esm: 11,105 RNAM blobs parse exactly at
    this layout and all 193,424 references resolve to a record in the file.
    """
    if len(data) < 8:
        raise SystemExit(f'WRLD RNAM is {len(data)} bytes, too short')
    count = struct.unpack_from('<I', data, 4)[0]
    if 8 + count * 8 != len(data):
        raise SystemExit(f'WRLD RNAM says {count} refs but is {len(data)} bytes')
    return [8 + i * 8 for i in range(count)]


# rectype -> {signature: a function giving every FormID offset in the payload}.
# For fields whose FormIDs are not on a fixed stride.
STRUCTURED_FIELDS = {
    'NPC_': {sig: vmad_formid_offsets for sig in NPC_STRUCTURED_FIELDS},
    'ACHR': {'VMAD': vmad_formid_offsets},
    'REFR': {'VMAD': vmad_formid_offsets},
    'CELL': {'VMAD': vmad_formid_offsets},
    'CONT': {'VMAD': vmad_formid_offsets},
    'FACT': {'PLVD': plvd_formid_offsets},
    'WRLD': {'RNAM': wrld_rnam_formid_offsets},
    'RELA': {'DATA': rela_formid_offsets},
}

# Canonical NPC_ field order, read off vanilla creature actors in
# references/Skyrim.esm/NPC_.txt (WhiterunPlayerHorse, EncHorseSaddledBrown,
# EncWolf, EncSabreCat, EncMammothWild, EncGoatDomestic all agree):
#   ... VTCK TPLT RNAM WNAM ATKR AIDT PKID KSIZ KWDA CNAM FULL DATA DNAM
#       ZNAM NAM5 NAM6 NAM7 NAM8 CSCR DOFT DPLT QNAM ...
# A subrecord this patch ADDS has to land in that order, so each new field
# carries the tuple of everything that may legally follow it.
_TAIL = ('CNAM', 'FULL', 'DATA', 'DNAM', 'ZNAM', 'NAM5', 'NAM6', 'NAM7',
         'NAM8', 'CSDT', 'CSDI', 'CSDC', 'CSCR', 'DOFT', 'SOFT', 'DPLT',
         'CRIF', 'FTST', 'QNAM', 'NAM9', 'NAMA', 'TINI', 'TINC', 'TINV',
         'TIAS')
AFTER_WNAM = ('ATKR', 'AIDT', 'PKID', 'KSIZ', 'KWDA') + _TAIL
AFTER_ATKR = ('AIDT', 'PKID', 'KSIZ', 'KWDA') + _TAIL
AFTER_KSIZ = ('KWDA',) + _TAIL
AFTER_KWDA = _TAIL
AFTER_VTCK = ('TPLT', 'RNAM', 'WNAM') + AFTER_WNAM
AFTER_CNAM = _TAIL[1:]
AFTER_ZNAM = ('NAM5', 'NAM6', 'NAM7', 'NAM8', 'CSDT', 'CSDI', 'CSDC', 'CSCR',
              'DOFT', 'SOFT', 'DPLT', 'CRIF', 'FTST', 'QNAM', 'NAM9', 'NAMA',
              'TINI', 'TINC', 'TINV', 'TIAS')
AFTER_DPLT = ('CRIF', 'FTST', 'QNAM', 'NAM9', 'NAMA', 'TINI', 'TINC', 'TINV',
              'TIAS')


# ---------------------------------------------------------------------------
# Reading, with the GRUP chain preserved
# ---------------------------------------------------------------------------

def iter_records_chained(buf, want_types):
    """Yield (sig, fid, flags, header, data, chain) for the types asked for.

    `chain` is the tuple of enclosing GRUPs, outermost first, each as
    `(group_type, label_bytes)`. Rebuilding that tuple verbatim is how a placed
    reference gets written back into the right cell without re-deriving
    Bethesda's block numbering.
    """
    size = struct.unpack_from('<I', buf, 4)[0]
    pos, end = REC_HDR + size, len(buf)
    stack = []                      # [(group_end, (gtype, label))]
    while pos < end:
        while stack and pos >= stack[-1][0]:
            stack.pop()
        if pos + REC_HDR > end:
            break
        if bytes(buf[pos:pos + 4]) == b'GRUP':
            gsize, label, gtype = struct.unpack_from('<I4si', buf, pos + 4)
            if gsize < GRP_HDR:
                break
            stack.append((pos + gsize, (gtype, bytes(label))))
            pos += GRP_HDR
            continue
        sig = bytes(buf[pos:pos + 4]).decode('ascii', 'replace')
        dsize, flags, fid = struct.unpack_from('<III', buf, pos + 4)
        if sig in want_types:
            hdr = bytearray(buf[pos:pos + REC_HDR])
            data = bytes(buf[pos + REC_HDR:pos + REC_HDR + dsize])
            if flags & FLAG_COMPRESSED:
                # Written back uncompressed, so drop the flag rather than
                # carrying a stale one into the patch.
                data = zlib.decompress(data[4:])
                flags &= ~FLAG_COMPRESSED
                struct.pack_into('<I', hdr, 8, flags)
            yield (sig, fid, flags, bytes(hdr), data,
                   tuple(entry for _e, entry in stack))
        pos += REC_HDR + dsize


class ChainedSource:
    """A plugin read for several record types, keeping each one's GRUP chain."""

    def __init__(self, path, want_types):
        self.path = Path(path)
        self.name = self.path.name
        buf = self.path.read_bytes()
        self.masters = read_masters(buf)
        self.own_index = len(self.masters)
        self.by_type = {t: OrderedDict() for t in want_types}
        self.chains = {}
        for sig, fid, flags, hdr, data, chain in iter_records_chained(
                buf, want_types):
            self.by_type[sig][fid] = (hdr, read_subrecords(data))
            self.chains[(sig, fid)] = chain

    def edid(self, sig, fid):
        rec = self.by_type.get(sig, {}).get(fid)
        if not rec:
            return ''
        for s, payload in rec[1]:
            if s == 'EDID':
                return zstring(payload)
        return ''


class SourceStack:
    """The converted plugin, plus the patches already built on top of it.

    Two plugins that override the same record do NOT merge in game: the later
    one wins the WHOLE record. A patch that copies its records straight off the
    converted master therefore REVERTS every earlier patch's change to any
    record they share -- silently, and only for the ones they have in common.
    Measured case: the cosmetic patch and the iNeed patch both override the
    same 220 merchant NPCs, so whichever loaded second erased the other's work.

    Reading through the stack instead -- the base plugin first, then each
    earlier patch in load order -- makes the later patch CARRY the earlier
    ones' fields, which is what last-one-wins requires. The patch must then
    master every overlay it reads a record from, so the load order can never
    put it first.
    """

    def __init__(self, base_path, overlay_paths, want_types):
        self.layers = [ChainedSource(p, want_types)
                       for p in [base_path, *overlay_paths]]
        self.base = self.layers[0]
        self.overlays = self.layers[1:]
        # The base plugin's own attributes, so a caller that only wants the
        # converted plugin can treat a stack as the ChainedSource it replaces.
        self.path = self.base.path
        self.name = self.base.name
        self.masters = self.base.masters
        self.own_index = self.base.own_index
        self.by_type = self.base.by_type
        self.chains = self.base.chains
        self.index = {}
        for layer in self.layers:
            owners = [m.lower() for m in layer.masters] + [layer.name.lower()]
            for sig, table in layer.by_type.items():
                for fid in table:
                    i = fid >> 24
                    if i < len(owners):
                        self.index[(sig, owners[i], fid & 0xFFFFFF)] = (layer,
                                                                        fid)

    def latest(self, sig, owner, low):
        """(layer, fid) for the WINNING version of one record, or None.

        `owner` is the plugin that DEFINES the record and `low` its object id,
        because a FormID's high byte means something different in every file
        that names it.
        """
        return self.index.get((sig, owner.lower(), low & 0xFFFFFF))

    def contributors(self, sig, keys):
        """The overlays that override any of `keys` -- [(owner, low), ...].

        A patch should master an overlay only when it actually reads a record
        from it: mastering one it never uses makes the patch refuse to load for
        everyone who does not have that file.
        """
        out = []
        for layer in self.overlays:
            owners = [m.lower() for m in layer.masters] + [layer.name.lower()]
            hit = False
            for fid in layer.by_type.get(sig, ()):
                i = fid >> 24
                if i < len(owners) and (owners[i], fid & 0xFFFFFF) in keys:
                    hit = True
                    break
            if hit:
                out.append(layer.name)
        return out


def overlay_contributors(paths, want_types, keys):
    """Which of `paths` override any of `keys` -- read without a base plugin.

    The master list has to be settled BEFORE any record is added, but which
    overlays are worth mastering is only knowable by reading them, so this
    answers that question on its own.
    """
    out = []
    for path in paths:
        layer = ChainedSource(path, want_types)
        owners = [m.lower() for m in layer.masters] + [layer.name.lower()]
        for sig, table in layer.by_type.items():
            if any((owners[fid >> 24], fid & 0xFFFFFF) in keys
                   for fid in table if (fid >> 24) < len(owners)):
                out.append(path)
                break
    return out


# ---------------------------------------------------------------------------
# Remapping any record type
# ---------------------------------------------------------------------------

def remap_fid(fid, mapping, where=''):
    idx = fid >> 24
    new = mapping.get(idx)
    if new is None:
        raise SystemExit(
            f'FormID {fid:08X}{" in " + where if where else ""} uses master '
            f'index {idx}, past the source plugin\'s own master list')
    return (new << 24) | (fid & 0x00FFFFFF)


def remap_subrecord(rectype, sig, payload, mapping):
    if sig in PLAIN_FIELDS.get(rectype, ()):
        return payload
    offsets_of = STRUCTURED_FIELDS.get(rectype, {}).get(sig)
    if offsets_of is not None:
        buf = bytearray(payload)
        for off in offsets_of(payload):
            fid = struct.unpack_from('<I', buf, off)[0]
            struct.pack_into('<I', buf, off, remap_fid(fid, mapping, sig))
        return bytes(buf)
    field = FORMID_FIELDS.get(rectype, {}).get(sig)
    if field is None:
        raise SystemExit(
            f'{rectype} subrecord "{sig}" is in neither the FormID map nor the '
            'plain list; add it to patch_builder.py before running (a wrong '
            'master index here is a silently broken reference)')
    firstoff, stride = field
    if len(payload) % stride:
        raise SystemExit(f'{rectype}.{sig} is {len(payload)} bytes, not a '
                         f'multiple of {stride}')
    buf = bytearray(payload)
    for base in range(0, len(buf), stride):
        off = base + firstoff
        fid = struct.unpack_from('<I', buf, off)[0]
        struct.pack_into('<I', buf, off, remap_fid(fid, mapping, sig))
    return bytes(buf)


def remap_record(rectype, header, subs, mapping, form_version=TES4_FORM_VERSION):
    """(header, subs) copied from a source plugin into the patch's ID space.

    `form_version=None` keeps the record's own -- what a MERGE wants, since it
    is reproducing an authored record rather than writing a new one.
    """
    new_subs = [(sig, remap_subrecord(rectype, sig, payload, mapping))
                for sig, payload in subs]
    hdr = bytearray(header)
    fid = struct.unpack_from('<I', hdr, 12)[0]
    struct.pack_into('<I', hdr, 12, remap_fid(fid, mapping, rectype))
    if form_version is not None:
        # A record the patch AUTHORS is written at the current form version;
        # carrying an older one through makes the CK re-save fields we never set.
        struct.pack_into('<H', hdr, 20, form_version)
    return bytes(hdr), new_subs


def remap_chain(chain, mapping):
    """The same GRUP chain with its cell/worldspace labels remapped.

    Group types 1, 6, 8, 9 and 10 label themselves with a FormID; 2 and 3 carry
    a block number and 4 and 5 a grid coordinate, and those are left alone.
    """
    out = []
    for gtype, label in chain:
        if gtype in (GT_WORLD_CHILDREN, GT_CELL_CHILDREN, GT_PERSISTENT,
                     GT_TEMPORARY, GT_DISTANT):
            fid = struct.unpack('<I', label)[0]
            label = struct.pack('<I', remap_fid(fid, mapping, 'GRUP label'))
        out.append((gtype, label))
    return tuple(out)


# ---------------------------------------------------------------------------
# Load order
# ---------------------------------------------------------------------------

# Officials come first and in Bethesda's own order; anything else keeps the
# order the caller passes. A master list that puts Oblivion.esm before
# Skyrim.esm is not merely untidy -- the index IS the FormID high byte.
OFFICIAL_ORDER = [
    'skyrim.esm', 'update.esm', 'dawnguard.esm', 'hearthfires.esm',
    'dragonborn.esm',
]


# Where a plugin named as a master might actually live, in the order worth
# trying: the patch's own inputs, then the converted output, then the game.
def locate_plugin(name, output_dir=None, repo=None):
    """A path to the plugin called `name`, or None if nothing here has it.

    Missing is not an error: vanilla masters are always present in a real load
    order even when this machine cannot point at them.
    """
    repo = Path(repo) if repo else Path(__file__).resolve().parents[2]
    sources = repo / 'patch_folder' / 'sources'
    candidates = [sources / name]
    # A third-party mod usually arrives as a FOLDER (patch_folder/sources/iNeed/
    # iNeed.esp), so look one level down as well.
    if sources.is_dir():
        candidates += [d / name for d in sorted(sources.iterdir()) if d.is_dir()]
    out_root = Path(output_dir) if output_dir else repo / 'output'
    if out_root.is_dir():
        candidates.append(out_root / name / name)
        candidates += [d / name for d in sorted(out_root.iterdir())
                       if d.is_dir()]
    try:
        from asset_convert.skyrim_assets import find_skyrim_data
        candidates.append(Path(find_skyrim_data()) / name)
    except Exception:
        pass
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def expand_masters(names, locate):
    """`names` plus the masters of every plugin in it, transitively.

    A plugin does not strictly have to declare its masters' masters, but the CK
    writes them and -- more to the point -- `make_remap` builds a mapping for
    EVERY master a source plugin lists, so reading head parts out of
    `KS Hairdo's.esp` fails outright unless the patch also lists `Update.esm`.
    Declaring the extra master is cheaper than special-casing the reader.

    `locate(name)` returns a path to that plugin, or None when it cannot be
    found; an unfindable plugin contributes no parents rather than aborting,
    because vanilla masters are always present in a real load order. Emitted
    depth-first, so a master always precedes the plugin resting on it.
    """
    out = []
    done = set()
    visiting = set()

    def visit(name):
        low = name.lower()
        if low in done or low in visiting:
            return          # already placed, or a cycle -- neither can recurse
        visiting.add(low)
        path = locate(name)
        if path:
            try:
                with open(path, 'rb') as fh:
                    parents = read_masters(fh.read(8192))
            except OSError:
                parents = []
            for parent in parents:
                visit(parent)
        visiting.discard(low)
        done.add(low)
        out.append(name)

    for name in names:
        visit(name)
    return out


def order_masters(names, locate=None):
    """Officials first in Bethesda's order, then Creation Club, then the rest.

    `names` is deduplicated case-insensitively. Pass `locate` -- the same
    callback `expand_masters` takes -- and the non-official plugins come back in
    DEPENDENCY order no matter what order they went in; without it the caller's
    order is kept verbatim, and the caller is then responsible for putting a
    master ahead of whatever rests on it. That is not a style point: the index
    into this list IS the FormID's high byte, so `ElsweyrAnequina.esp` landing
    before `Oblivion.esm` is a load order the game will not accept.
    """
    seen = OrderedDict()
    for n in names:
        seen.setdefault(n.lower(), n)
    ordered = list(seen.values())
    if locate is not None:
        ordered = expand_masters(ordered, locate)
    officials, cc, rest = [], [], []
    for name in ordered:
        low = name.lower()
        if low in OFFICIAL_ORDER:
            officials.append(name)
        elif low.startswith('cc'):
            cc.append(name)
        else:
            rest.append(name)
    officials.sort(key=lambda n: OFFICIAL_ORDER.index(n.lower()))
    cc.sort(key=str.lower)
    return officials + cc + rest


# ---------------------------------------------------------------------------
# The patch
# ---------------------------------------------------------------------------

class PatchPlugin:
    """A patch ESP assembled in memory: masters, flat groups, nested refs."""

    def __init__(self, masters, author='TES4-to-TES5 converter',
                 description='', next_object_id=0x00000800):
        self.masters = list(masters)
        self.index = {n.lower(): i for i, n in enumerate(self.masters)}
        self.author = author
        self.description = description
        self.next_object_id = next_object_id
        self.own_index = len(self.masters)
        self.flat = OrderedDict()        # sig -> {fid: (header, subs)}
        self.nested = OrderedDict()      # chain -> [(sig, fid, header, subs)]
        self.parents = OrderedDict()     # (sig, fid) -> (header, subs)

    # -- masters -----------------------------------------------------------
    def master_index(self, plugin_name):
        try:
            return self.index[plugin_name.lower()]
        except KeyError:
            raise SystemExit(
                f'the patch does not master "{plugin_name}"; it lists '
                f'{self.masters}. Masters must be settled before records are '
                'added, because the index is the FormID high byte')

    def remap_from(self, source):
        """index -> index, taking `source`'s FormIDs into the patch's space."""
        mapping = {}
        for i, name in enumerate(source.masters):
            mapping[i] = self.master_index(name)
        mapping[source.own_index] = self.master_index(source.name)
        return mapping

    def fid(self, plugin_name, local_fid):
        """A FormID in the patch's space, from a plugin name + its local id."""
        return (self.master_index(plugin_name) << 24) | (local_fid & 0xFFFFFF)

    # -- records -----------------------------------------------------------
    def add(self, sig, fid, header, subs):
        """A record in a flat top-level group (NPC_, LVLN, OTFT, ...)."""
        self.flat.setdefault(sig, OrderedDict())[fid] = (header, subs)

    def get(self, sig, fid):
        return self.flat.get(sig, {}).get(fid)

    def add_nested(self, chain, sig, fid, header, subs):
        """A record that lives inside a CELL/WRLD GRUP chain (ACHR, REFR)."""
        self.nested.setdefault(chain, []).append((sig, fid, header, subs))

    def add_parent(self, sig, fid, header, subs):
        """A CELL or WRLD override that has to exist so a chain can hang off it.

        xEdit writes these whenever a child reference is copied as an override,
        and they are pure copies -- no field of the cell itself is changed.
        """
        self.parents[(sig, fid)] = (header, subs)

    # -- writing -----------------------------------------------------------
    def _overridden_temporary(self):
        """FormIDs this patch overrides inside a master's TEMPORARY cell group.

        These MUST be announced in the header's ONAM array. Skyrim loads a
        cell's temporary children on demand and discovers a plugin's overrides
        of them from ONAM alone -- xEdit puts it plainly: "the game engine will
        ignore the override that is missing from ONAM". Leaving it out is
        exactly the failure where a disabled reference keeps spawning anyway.

        Only group type 9 counts; persistent children (8) are always resident,
        and a record the patch defines itself is not an override, so only
        FormIDs at a master's index qualify.
        """
        out = set()
        for chain, records in self.nested.items():
            if not any(gtype == GT_TEMPORARY for gtype, _label in chain):
                continue
            for _sig, fid, _hdr, _subs in records:
                if (fid >> 24) < self.own_index:
                    out.add(fid)
        return sorted(out)

    def _header_bytes(self, record_count):
        subs = []
        hedr = struct.pack('<fII', HEDR_VERSION, record_count,
                           self.next_object_id)
        subs.append(('HEDR', hedr))
        subs.append(('CNAM', self.author.encode('cp1252') + b'\0'))
        if self.description:
            subs.append(('SNAM', self.description.encode('cp1252') + b'\0'))
        for name in self.masters:
            subs.append(('MAST', name.encode('cp1252') + b'\0'))
            subs.append(('DATA', b'\0' * 8))
        # ONAM follows the master array, where xEdit places it.
        onam = self._overridden_temporary()
        if onam:
            subs.append(('ONAM', b''.join(struct.pack('<I', f) for f in onam)))
        subs.append(('INTV', struct.pack('<I', 1)))
        data = build_subrecords(subs)
        hdr = bytearray(b'TES4')
        hdr += struct.pack('<III', len(data), 0, 0)
        hdr += struct.pack('<IHH', 0, TES4_FORM_VERSION, 0)
        return bytes(hdr) + data

    @staticmethod
    def _record_bytes(fid, header, subs):
        data = build_subrecords(subs)
        rec = bytearray(header)
        struct.pack_into('<I', rec, 4, len(data))
        struct.pack_into('<I', rec, 12, fid)
        return bytes(rec) + data

    @staticmethod
    def _group(label, gtype, body, stamp=b'\0' * 8):
        out = bytearray(b'GRUP')
        out += struct.pack('<I', GRP_HDR + len(body))
        out += label if isinstance(label, bytes) else label.encode('ascii')
        out += struct.pack('<i', gtype)
        out += stamp
        out += body
        return bytes(out)

    def _build_nested(self):
        """Rebuild the CELL / WRLD trees from the recorded chains.

        The chains are grouped by successively longer prefixes, so two refs in
        the same cell share every group above them instead of each getting its
        own -- which is what the game (and xEdit) expect, and what keeps a
        cell's children in one place.
        """
        by_top = OrderedDict()
        for chain in self.nested:
            by_top.setdefault(chain[0], []).append(chain)
        out = OrderedDict()
        for top, chains in by_top.items():
            body = self._emit_level(chains, 1)
            out[top[1].decode('ascii', 'replace')] = (top[0], top[1], body)
        return out

    def _emit_level(self, chains, depth):
        """Serialize every chain at `depth`, grouping by their shared prefix."""
        body = bytearray()
        groups = OrderedDict()
        for chain in chains:
            if depth >= len(chain):
                # This chain ends here: emit its records.
                for sig, fid, hdr, subs in self.nested[chain]:
                    body += self._record_bytes(fid, hdr, subs)
                continue
            groups.setdefault(chain[depth], []).append(chain)
        for entry, sub_chains in groups.items():
            gtype, label = entry
            inner = bytearray()
            # A cell-children group is preceded by the CELL record itself, and
            # a world-children group by its WRLD record.
            if gtype == GT_CELL_CHILDREN:
                parent = self.parents.get(('CELL', struct.unpack('<I', label)[0]))
                if parent is not None:
                    body += self._record_bytes(
                        struct.unpack('<I', label)[0], *parent)
            elif gtype == GT_WORLD_CHILDREN:
                parent = self.parents.get(('WRLD', struct.unpack('<I', label)[0]))
                if parent is not None:
                    body += self._record_bytes(
                        struct.unpack('<I', label)[0], *parent)
            inner += self._emit_level(sub_chains, depth + 1)
            body += self._group(label, gtype, bytes(inner))
        return bytes(body)

    def write(self, out_path):
        """Serialize the patch. Returns (size, records, groups)."""
        # label -> (group type, raw label, body). A top-level signature can get
        # records from BOTH sides: the ship patch overrides Tamriel's WRLD
        # record itself and hangs a reference under another worldspace, and the
        # two have to end up in ONE top-level WRLD group -- a second group with
        # the same label would silently replace the first.
        bodies = OrderedDict()
        for sig, table in self.flat.items():
            body = bytearray()
            for fid, (hdr, subs) in table.items():
                body += self._record_bytes(fid, hdr, subs)
            if body:
                bodies[sig] = (GT_TOP, sig.encode('ascii'), body)
        for label, (gtype, raw, body) in self._build_nested().items():
            if label in bodies:
                bodies[label][2].extend(body)
            else:
                bodies[label] = (gtype, raw, bytearray(body))
        groups = OrderedDict(
            (label, self._group(raw, gtype, bytes(body)))
            for label, (gtype, raw, body) in bodies.items())

        def rank(label):
            return (GROUP_ORDER.index(label) if label in GROUP_ORDER
                    else len(GROUP_ORDER))

        records = grups = 0
        for blob in groups.values():
            r, g = _count_group(blob)
            records += r
            grups += g

        out = bytearray(self._header_bytes(records + grups))
        for label in sorted(groups, key=rank):
            out += groups[label]

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(bytes(out))
        return len(out), records, grups


# ---------------------------------------------------------------------------
# Field insertion in canonical order
# ---------------------------------------------------------------------------

# `set_field` is `plugin_patch.insert_run`, aliased at the top of this module.
