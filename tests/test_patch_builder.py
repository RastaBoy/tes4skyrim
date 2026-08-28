"""The binary contract of tools/patch/patch_builder.py.

These are the invariants a patch ESP has to satisfy or the game quietly ignores
it. Everything here is synthetic -- no converted plugin is read -- so the whole
file runs in well under a second.
"""

import contextlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.patch.patch_builder import (          # noqa: E402
    FLAG_INITIALLY_DISABLED, GT_CELL_CHILDREN, GT_INTERIOR_BLOCK,
    GT_INTERIOR_SUBBLOCK, GT_PERSISTENT, GT_TEMPORARY, GT_TOP,
    GT_WORLD_CHILDREN, PatchPlugin, SourceStack, expand_masters,
    order_masters, overlay_contributors, remap_chain, remap_record, set_field,
)
from tools.patch.patch_builder import iter_records_chained   # noqa: E402
from tools.patch.plugin_patch import (           # noqa: E402
    GRP_HDR, REC_HDR, read_masters, read_subrecords,
)

MASTERS = ['Skyrim.esm', 'Oblivion.esm', 'ElsweyrAnequina.esp']


def _header(sig, fid, flags=0):
    hdr = bytearray(sig.encode('ascii'))
    hdr += struct.pack('<III', 0, flags, fid)
    hdr += struct.pack('<IHH', 0, 44, 0)
    return bytes(hdr)


def _achr(fid, base, flags=0):
    return _header('ACHR', fid, flags), [
        ('NAME', struct.pack('<I', base)),
        ('DATA', b'\0' * 24),
    ]


def _cell(fid):
    return _header('CELL', fid), [('EDID', b'TestCell\0'), ('DATA', b'\x01\x00')]


def _wrld(fid):
    return _header('WRLD', fid), [('EDID', b'TestWorld\0'),
                                  ('CNAM', struct.pack('<I', 0x0000015F))]


def _interior_chain(cell_fid, temporary=True):
    return ((GT_TOP, b'CELL'),
            (GT_INTERIOR_BLOCK, struct.pack('<i', 0)),
            (GT_INTERIOR_SUBBLOCK, struct.pack('<i', 1)),
            (GT_CELL_CHILDREN, struct.pack('<I', cell_fid)),
            (GT_TEMPORARY if temporary else GT_PERSISTENT,
             struct.pack('<I', cell_fid)))


def _exterior_chain(wrld_fid, cell_fid):
    return ((GT_TOP, b'WRLD'),
            (GT_WORLD_CHILDREN, struct.pack('<I', wrld_fid)),
            (4, struct.pack('<hh', 0, -2)),
            (5, struct.pack('<hh', 0, -6)),
            (GT_CELL_CHILDREN, struct.pack('<I', cell_fid)),
            (GT_TEMPORARY, struct.pack('<I', cell_fid)))


def _tiles(buf):
    """Every byte after the file header is accounted for by a record or GRUP."""
    def walk(pos, end):
        while pos < end:
            if buf[pos:pos + 4] == b'GRUP':
                size = struct.unpack_from('<I', buf, pos + 4)[0]
                if size < GRP_HDR or pos + size > end:
                    return False
                if not walk(pos + GRP_HDR, pos + size):
                    return False
                pos += size
            else:
                dsize = struct.unpack_from('<I', buf, pos + 4)[0]
                if pos + REC_HDR + dsize > end:
                    return False
                pos += REC_HDR + dsize
        return pos == end
    hsize = struct.unpack_from('<I', buf, 4)[0]
    return walk(REC_HDR + hsize, len(buf))


def _header_field(buf, sig):
    hsize = struct.unpack_from('<I', buf, 4)[0]
    for s, payload in read_subrecords(buf[REC_HDR:REC_HDR + hsize]):
        if s == sig:
            return payload
    return None


@contextlib.contextmanager
def _fake_plugins(parents):
    """Make open() return a TES4 header whose MAST list is `parents[path]`.

    Cheaper and more legible than writing throwaway plugin files, and it keeps
    the master-expansion tests independent of the filesystem.
    """
    import builtins
    import io
    real_open = builtins.open
    ZERO = bytes(1)

    def fake_open(path, mode='rb', *a, **k):
        if path not in parents:
            return real_open(path, mode, *a, **k)
        subs = b''
        for m in parents[path]:
            subs += b'MAST' + struct.pack('<H', len(m) + 1) + m.encode() + ZERO
            subs += b'DATA' + struct.pack('<H', 8) + ZERO * 8
        hdr = b'TES4' + struct.pack('<III', len(subs), 0, 0)
        hdr += struct.pack('<IHH', 0, 44, 0)
        return io.BytesIO(hdr + subs)

    builtins.open = fake_open
    try:
        yield
    finally:
        builtins.open = real_open


@pytest.fixture
def built(tmp_path):
    """A patch with one swapped NPC, two disabled refs and their parents."""
    patch = PatchPlugin(MASTERS, description='test')
    npc_fid = patch.fid('Oblivion.esm', 0x00CF22)
    patch.add('NPC_', npc_fid, _header('NPC_', npc_fid),
              [('EDID', b'HorseBay\0'), ('RNAM', struct.pack('<I', 0x000131FD))])

    cell = patch.fid('ElsweyrAnequina.esp', 0x01262E)
    wrld = patch.fid('Oblivion.esm', 0x00003C)
    ext_cell = patch.fid('Oblivion.esm', 0x006282)
    base = patch.fid('ElsweyrAnequina.esp', 0x012CF8)

    patch.add_parent('CELL', cell, *_cell(cell))
    patch.add_parent('WRLD', wrld, *_wrld(wrld))
    patch.add_parent('CELL', ext_cell, *_cell(ext_cell))

    interior = patch.fid('ElsweyrAnequina.esp', 0x012CFB)
    hdr, subs = _achr(interior, base, FLAG_INITIALLY_DISABLED)
    patch.add_nested(_interior_chain(cell), 'ACHR', interior, hdr, subs)

    exterior = patch.fid('ElsweyrAnequina.esp', 0x0228B2)
    hdr, subs = _achr(exterior, base, FLAG_INITIALLY_DISABLED)
    patch.add_nested(_exterior_chain(wrld, ext_cell), 'ACHR', exterior, hdr, subs)

    out = tmp_path / 'Test.esp'
    size, records, groups = patch.write(out)
    return out, out.read_bytes(), records, groups


def test_file_tiles_exactly(built):
    _path, buf, _r, _g = built
    assert _tiles(buf)


def test_masters_are_written_in_order(built):
    _path, buf, _r, _g = built
    assert read_masters(buf) == MASTERS


def test_hedr_counts_records_plus_groups(built):
    _path, buf, records, groups = built
    hedr = _header_field(buf, 'HEDR')
    assert struct.unpack_from('<I', hedr, 4)[0] == records + groups


def test_onam_lists_every_temporary_override(built):
    """Without ONAM the engine ignores an override of a temporary cell child."""
    _path, buf, _r, _g = built
    onam = _header_field(buf, 'ONAM')
    assert onam is not None
    listed = {struct.unpack_from('<I', onam, i)[0]
              for i in range(0, len(onam), 4)}
    temporary = {fid for _s, fid, _f, _h, _d, chain
                 in iter_records_chained(buf, {'ACHR'})
                 if any(t == GT_TEMPORARY for t, _l in chain)}
    assert temporary and listed == temporary


def test_persistent_refs_stay_out_of_onam(tmp_path):
    """Persistent children are always resident; xEdit omits them too."""
    patch = PatchPlugin(MASTERS)
    cell = patch.fid('ElsweyrAnequina.esp', 0x06B013)
    ref = patch.fid('ElsweyrAnequina.esp', 0x080FA0)
    patch.add_parent('CELL', cell, *_cell(cell))
    patch.add_nested(_interior_chain(cell, temporary=False), 'ACHR', ref,
                     *_achr(ref, cell))
    out = tmp_path / 'P.esp'
    patch.write(out)
    assert _header_field(out.read_bytes(), 'ONAM') is None


def test_parent_record_precedes_its_children_group(built):
    """A cell-children group must be preceded by its own CELL record."""
    _path, buf, _r, _g = built
    seen = []

    def walk(pos, end):
        last = None
        while pos < end:
            if buf[pos:pos + 4] == b'GRUP':
                size, label, gtype = struct.unpack_from('<I4si', buf, pos + 4)
                if gtype in (GT_CELL_CHILDREN, GT_WORLD_CHILDREN):
                    seen.append((gtype, struct.unpack('<I', label)[0], last))
                walk(pos + GRP_HDR, pos + size)
                pos += size
            else:
                dsize = struct.unpack_from('<I', buf, pos + 4)[0]
                last = (buf[pos:pos + 4].decode(),
                        struct.unpack_from('<I', buf, pos + 12)[0])
                pos += REC_HDR + dsize

    hsize = struct.unpack_from('<I', buf, 4)[0]
    walk(REC_HDR + hsize, len(buf))
    assert seen
    for gtype, owner, previous in seen:
        want = 'CELL' if gtype == GT_CELL_CHILDREN else 'WRLD'
        assert previous == (want, owner)


def test_two_refs_in_one_cell_share_the_group(tmp_path):
    """Chains with a shared prefix must collapse, not duplicate the tree."""
    patch = PatchPlugin(MASTERS)
    cell = patch.fid('ElsweyrAnequina.esp', 0x01262E)
    patch.add_parent('CELL', cell, *_cell(cell))
    chain = _interior_chain(cell)
    for low in (0x012CFB, 0x012CFC):
        fid = patch.fid('ElsweyrAnequina.esp', low)
        patch.add_nested(chain, 'ACHR', fid, *_achr(fid, cell))
    out = tmp_path / 'P.esp'
    patch.write(out)
    buf = out.read_bytes()
    cells = [fid for sig, fid, _f, _h, _d, _c
             in iter_records_chained(buf, {'CELL'})]
    assert cells == [cell]          # one CELL override, not two


def test_flat_and_nested_records_share_one_top_level_group(tmp_path):
    """A WRLD override plus a ref hanging under another WRLD is ONE group.

    The ship patch needs both at once: it re-asserts Tamriel's object bounds as
    a plain top-level WRLD record, and nests the sea gate under the ocean
    worldspace. Two GRUPs with the same label would leave only one of them --
    they collide on the label -- and the record that vanished is the one nobody
    would think to check.
    """
    patch = PatchPlugin(MASTERS)
    bounded = patch.fid('Skyrim.esm', 0x00003C)
    patch.add('WRLD', bounded, *_wrld(bounded))

    wrld = patch.fid('ElsweyrAnequina.esp', 0x0009B7)
    cell = patch.fid('ElsweyrAnequina.esp', 0x01262E)
    patch.add_parent('WRLD', wrld, *_wrld(wrld))
    patch.add_parent('CELL', cell, *_cell(cell))
    ref = patch.fid('ElsweyrAnequina.esp', 0x0228B2)
    patch.add_nested(_exterior_chain(wrld, cell), 'ACHR', ref,
                     *_achr(ref, cell))

    out = tmp_path / 'P.esp'
    patch.write(out)
    buf = out.read_bytes()

    hsize = struct.unpack_from('<I', buf, 4)[0]
    pos = REC_HDR + hsize
    tops = []
    while pos < len(buf):
        size, label, gtype = struct.unpack_from('<I4si', buf, pos + 4)
        tops.append((label, gtype))
        pos += size
    assert tops.count((b'WRLD', GT_TOP)) == 1, tops

    worlds = [fid for _s, fid, _f, _h, _d, _c
              in iter_records_chained(buf, {'WRLD'})]
    assert sorted(worlds) == sorted([bounded, wrld])
    assert _tiles(buf)


def test_remap_moves_master_indexes_and_chain_labels():
    mapping = {0: 0, 1: 4, 2: 5}
    header, subs = _achr(0x0200ABCD, 0x0100BEEF)
    new_header, new_subs = remap_record('ACHR', header, subs, mapping)
    assert struct.unpack_from('<I', new_header, 12)[0] == 0x0500ABCD
    assert struct.unpack('<I', dict(new_subs)['NAME'])[0] == 0x0400BEEF
    chain = _interior_chain(0x0201262E)
    moved = remap_chain(chain, mapping)
    # Block/sub-block labels are numbers, not FormIDs -- they must not move.
    assert moved[1] == chain[1] and moved[2] == chain[2]
    assert struct.unpack('<I', moved[3][1])[0] == 0x0501262E


def test_unknown_subrecord_aborts_rather_than_shipping_a_stale_index():
    with pytest.raises(SystemExit):
        remap_record('ACHR', _header('ACHR', 1), [('ZZZZ', b'\0\0\0\0')],
                     {0: 0})


def test_order_masters_puts_officials_first():
    got = order_masters(['ElsweyrAnequina.esp', 'Oblivion.esm', 'Dragonborn.esm',
                         'Skyrim.esm', 'ccbgssse025-advdsgs.esm', 'Update.esm'])
    assert got[:4] == ['Skyrim.esm', 'Update.esm', 'Dragonborn.esm',
                       'ccbgssse025-advdsgs.esm']
    # Without a locator the caller's order for non-officials is kept verbatim.
    assert got[4:] == ['ElsweyrAnequina.esp', 'Oblivion.esm']


def test_order_masters_with_a_locator_fixes_a_bad_input_order():
    """The index IS the FormID high byte, so a master must precede its dependent."""
    parents = {'ElsweyrAnequina.esp': ['Skyrim.esm', 'Oblivion.esm'],
               'Oblivion.esm': ['Skyrim.esm']}
    with _fake_plugins(parents):
        got = order_masters(['ElsweyrAnequina.esp', 'Oblivion.esm', 'Skyrim.esm'],
                            lambda n: n if n in parents else None)
    assert got.index('Oblivion.esm') < got.index('ElsweyrAnequina.esp')


def test_expand_masters_pulls_in_a_masters_own_masters():
    parents = {'B.esp': ['A.esm'], 'A.esm': []}

    def locate(name):
        return name if name in parents else None

    real_open = open

    def fake_open(path, mode='rb'):        # noqa: ANN001 - test shim
        import io
        subs = b''
        for m in parents.get(path, []):
            subs += b'MAST' + struct.pack('<H', len(m) + 1) + m.encode() + b'\0'
            subs += b'DATA' + struct.pack('<H', 8) + b'\0' * 8
        hdr = b'TES4' + struct.pack('<III', len(subs), 0, 0)
        hdr += struct.pack('<IHH', 0, 44, 0)
        return io.BytesIO(hdr + subs)

    import builtins
    builtins.open = fake_open
    try:
        got = expand_masters(['B.esp'], locate)
    finally:
        builtins.open = real_open
    assert got == ['A.esm', 'B.esp']


def test_set_field_places_a_new_subrecord_in_canonical_order():
    subs = [('EDID', b'x\0'), ('RNAM', b'\1\0\0\0'), ('AIDT', b'\0'),
            ('CNAM', b'\2\0\0\0')]
    got = set_field(subs, 'WNAM', [b'\3\0\0\0'], ('ATKR', 'AIDT', 'CNAM'))
    assert [s for s, _p in got] == ['EDID', 'RNAM', 'WNAM', 'AIDT', 'CNAM']


# ---------------------------------------------------------------------------
# The FormID maps, re-measured against Skyrim.esm on 2026-08-27
# ---------------------------------------------------------------------------

def test_cell_xwem_is_a_texture_path_not_a_formid():
    """XWEM holds a cubemap texture PATH; remapping it would corrupt it."""
    path = rb'Data\Textures\Cubemaps\BluePalaceCube_e.dds' + b'\x00'
    _hdr, subs = remap_record('CELL', _header('CELL', 0x01000800),
                              [('XWEM', path)], {0: 0, 1: 1, 2: 2, 3: 3})
    assert subs[0][1] == path


def test_cell_xezn_is_remapped():
    """XEZN is the encounter zone -- a FormID, and it moves with its master."""
    _hdr, subs = remap_record('CELL', _header('CELL', 0x01000800),
                              [('XEZN', struct.pack('<I', 0x01001234))],
                              {0: 0, 1: 2, 2: 3})
    assert struct.unpack('<I', subs[0][1])[0] == 0x02001234


def test_achr_vmad_properties_are_remapped():
    """A placed actor's script properties carry FormIDs like any other field."""
    vmad = bytearray(struct.pack('<hhH', 5, 2, 1))       # version, objfmt, count
    vmad += struct.pack('<H', 4) + b'Test'               # script name
    vmad += b'\x00'                                      # script flags
    vmad += struct.pack('<H', 1)                         # one property
    vmad += struct.pack('<H', 3) + b'Ref'                # property name
    vmad += bytes([1, 1])                                # type Object, status
    vmad += struct.pack('<HHI', 0, 1, 0x01000ABC)        # unused, alias, FormID
    _hdr, subs = remap_record('ACHR', _header('ACHR', 0x02000800),
                              [('VMAD', bytes(vmad))], {0: 0, 1: 2, 2: 3})
    assert struct.unpack_from('<I', subs[0][1], len(vmad) - 4)[0] == 0x02000ABC


def test_rela_data_has_formids_at_0_4_and_12():
    data = struct.pack('<IIHHI', 0x01000101, 0x00000007, 3, 0, 0x01000202)
    _hdr, subs = remap_record('RELA', _header('RELA', 0x02000800),
                              [('DATA', data)], {0: 0, 1: 2, 2: 3})
    parent, child, rank, pad, astp = struct.unpack('<IIHHI', subs[0][1])
    assert (parent, child, astp) == (0x02000101, 0x00000007, 0x02000202)
    assert (rank, pad) == (3, 0)


def test_wrld_rnam_large_references_are_remapped():
    rnam = struct.pack('<hhI', 4, 20, 2)
    rnam += struct.pack('<Ihh', 0x01000111, 4, 20)
    rnam += struct.pack('<Ihh', 0x01000222, 3, 19)
    _hdr, subs = remap_record('WRLD', _header('WRLD', 0x01000800),
                              [('RNAM', rnam)], {0: 0, 1: 2, 2: 3})
    got = [struct.unpack_from('<I', subs[0][1], 8 + i * 8)[0] for i in range(2)]
    assert got == [0x02000111, 0x02000222]
    assert subs[0][1][:8] == rnam[:8]


def test_refr_xloc_key_is_at_offset_four():
    """Offset 0 is the lock LEVEL; treating it as a FormID corrupts the lock."""
    xloc = struct.pack('<IIII', 25, 0x01000555, 0, 0) + b'\x00' * 4
    _hdr, subs = remap_record('REFR', _header('REFR', 0x01000800),
                              [('XLOC', xloc)], {0: 0, 1: 2, 2: 3})
    level, key = struct.unpack_from('<II', subs[0][1], 0)
    assert (level, key) == (25, 0x02000555)


def test_hdpt_part_type_is_an_enum_not_a_formid():
    """PNAM 3 means Hair. It resolves against Skyrim.esm only by coincidence."""
    _hdr, subs = remap_record('HDPT', _header('HDPT', 0x02000800),
                              [('PNAM', struct.pack('<I', 3)),
                               ('TNAM', struct.pack('<I', 0x01000777))],
                              {0: 0, 1: 2, 2: 3})
    assert struct.unpack('<I', subs[0][1])[0] == 3
    assert struct.unpack('<I', subs[1][1])[0] == 0x02000777


# ---------------------------------------------------------------------------
# Stacking one patch on another
#
# Two plugins that override the same record do NOT merge: the later one wins
# the whole record. The cosmetic patch and the iNeed patch shared 220
# merchants, and the one that loaded second erased the other's work on all of
# them -- in game, every faction and every item of vendor stock. A later patch
# has to COPY the earlier one's version, which is what SourceStack is for.
# ---------------------------------------------------------------------------

def _npc(fid, snam):
    """One NPC_ carrying a single faction, so a copy is easy to tell apart."""
    return _header('NPC_', fid), [('EDID', b'TestNPC\0'),
                                  ('SNAM', struct.pack('<Ii', snam, 0))]


def _plugin(path, masters, records):
    patch = PatchPlugin(masters)
    for fid, snam in records:
        patch.add('NPC_', fid, *_npc(fid, snam))
    patch.write(path)
    return path


@pytest.fixture
def stacked(tmp_path):
    """A source plugin, a patch over it, and a patch that shares nothing."""
    src = _plugin(tmp_path / 'Src.esm', ['Skyrim.esm'],
                  [(0x01000ABC, 0x00000111), (0x01000DEF, 0x00000111)])
    # Overrides the FIRST record only. Its own index for Src.esm is 1 as well,
    # which is exactly the trap: the same FormID means different things here.
    over = _plugin(tmp_path / 'Over.esp', ['Skyrim.esm', 'Src.esm'],
                   [(0x01000ABC, 0x00000222)])
    other = _plugin(tmp_path / 'Other.esp', ['Skyrim.esm', 'Src.esm'],
                    [(0x01000999, 0x00000333)])
    return src, over, other


def _snam(layer, fid):
    subs = layer.by_type['NPC_'][fid][1]
    return struct.unpack_from('<I', dict(subs)['SNAM'], 0)[0]


def test_stack_takes_the_last_override_of_a_shared_record(stacked):
    src, over, _other = stacked
    stack = SourceStack(src, [over], {'NPC_'})
    layer, fid = stack.latest('NPC_', 'Src.esm', 0xABC)
    assert layer.name == 'Over.esp'
    assert _snam(layer, fid) == 0x00000222


def test_stack_falls_back_to_the_base_plugin(stacked):
    src, over, _other = stacked
    stack = SourceStack(src, [over], {'NPC_'})
    layer, fid = stack.latest('NPC_', 'Src.esm', 0xDEF)
    assert layer.name == 'Src.esm'
    assert _snam(layer, fid) == 0x00000111


def test_stack_keys_by_owner_not_by_formid(stacked):
    """0x01000ABC is Src.esm's own record in one file and a master's in the
    other. Keying by the raw FormID would confuse the two."""
    src, over, _other = stacked
    stack = SourceStack(src, [over], {'NPC_'})
    assert stack.latest('NPC_', 'Skyrim.esm', 0xABC) is None
    assert stack.latest('NPC_', 'Src.esm', 0xABC) is not None


def test_an_overlay_that_shares_nothing_is_not_mastered(stacked):
    """Mastering a file the patch never reads makes it refuse to load for
    everyone who does not have that file."""
    _src, over, other = stacked
    keys = {('src.esm', 0xABC)}
    assert overlay_contributors([over, other], {'NPC_'}, keys) == [over]
