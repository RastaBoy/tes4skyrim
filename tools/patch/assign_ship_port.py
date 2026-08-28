#!/usr/bin/env python3
"""Point Sailable Ship's Cyrodiil sea route at OUR converted Cyrodiil.

Writes `MyOwnTamrielShipPatch.esp` plus one replacement script, which together
move the mod's "Cyrodiil Route" from the Rigmor of Cyrodiil worldspace onto the
converted plugin's own overworld. The ship then sails out of the Southwest
Padomaic Ocean and arrives in Topal Bay.

    python tools/patch/assign_ship_port.py --plugins Oblivion.esm
    python tools/patch/assign_ship_port.py --plugins Oblivion.esm --landing 93877 -183808
    python tools/patch/assign_ship_port.py --plugins Oblivion.esm --dry-run

WHAT SAILABLE SHIP KEYS ON
--------------------------
A sea gate is a placed `aaaTeleport` activator carrying `aaaShipTeleportScript`,
whose properties are the whole destination:

    LandingWorldSpace       a console command, "CenterOnWorld <EditorID> x y"
    Xpos, Ypos              where the ship is put down, in that worldspace
    ZWaterHeight            that worldspace's sea level
    LandingWorldspaceIndex  the slot in aaaShipUtilityScript's addon table

Only two things in the whole mod name Rigmor. One is that string property. The
other is a hardcoded pair in `aaaShipUtilityScript.MakeWorldspaceArrays()` --
`(0x2F4DB2, "RigmorCyrodiil.esm")` -- which `IsWorldspaceActive()` feeds to
`Game.GetFormFromFile` to decide whether the port is switched on at all. Change
both and the route is ours; everything else the mod already calls "Cyrodiil"
(the map port activator, the marker name, the route's FULL) and needs no edit.

The RETURN gate is deliberately untouched. It is a second activator sitting
beside this one, pointing back at the sea, which the mod discovers by proximity
and physically moves into the destination on arrival -- it does not care which
worldspace that turned out to be.

WHAT IS READ, NOT ASSUMED
-------------------------
The gate is found by SEARCHING for the script property that names the worldspace
being replaced, so a Sailable Ship update that moves the record does not break
this. The destination's EditorID and sea level are read out of the converted
plugin's own WRLD record, and the landing point is checked against that
worldspace's LAND: a spot where the terrain is above the water line is a beach,
not an anchorage, and aborts the build.
"""

import argparse
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from tools.patch.patch_builder import (              # noqa: E402
    GT_WORLD_CHILDREN, ChainedSource, PatchPlugin, locate_plugin,
    order_masters, remap_chain, remap_record,
)
from tools.patch.plugin_patch import vmad_set_properties     # noqa: E402
from tools.patch.assign_creatures import find_converted      # noqa: E402

OUT_DIR = os.path.join(REPO, 'patch_folder', 'output')
PLUGIN_NAME = 'MyOwnTamrielShipPatch.esp'
SCRIPT_SUBDIR = 'ship_scripts'

SHIP_PLUGIN = 'Sailable Ship.esm'
SHIP_BSA = 'Sailable Ship.bsa'
TELEPORT_SCRIPT = 'aaaShipTeleportScript'
UTILITY_SCRIPT = 'aaaShipUtilityScript'
WORLDSPACE_FUNC = 'MakeWorldspaceArrays'

# The optional cargo-mission addon. It supplies `aaaSMUtilityScript`, the type
# every one of Sailable Ship's own scripts declares a property of -- without it
# the whole mod fails to LINK -- and it places one port marker per route, whose
# script properties carry that route's dock coordinates.
MISSIONS_PLUGIN = 'Sailable Ship Missions.esp'
MISSIONS_BSA = 'Sailable Ship Missions.bsa'
PORT_MARKER_SCRIPT = 'aaaSMPortMarkerScript'
# aaaShipTeleportScript picks the port marker with
# FindClosestReferenceOfTypeFromRef(..., 4000), so the marker belonging to a
# gate is defined by distance, not by name. Match that rule exactly.
PORT_MARKER_RADIUS = 4000.0

# The activator every sea gate is placed from.
GATE_ACTIVATOR = 'aaaTeleport'
# Two cells of rim around the outermost gate, so a reference sitting exactly on
# the boundary is inside it rather than on it.
BOUNDS_MARGIN = 8192.0

# Skyrim's border wall is a REGN with this record-header flag ("Border Region"
# in the CK's region dialog), and NOTHING in a plugin switches it off -- only
# `bBorderRegionsEnabled=0` does. Sailable Ship ships `Data/Sailable Ship.ini`
# saying exactly that; this patch ships its own copy so the requirement travels
# with it. See docs/sailable_ship_port.md for why the region is not overridden
# instead (its RDMP map name is an lstring into Skyrim.esm's STRINGS, which a
# non-localized patch cannot carry without baking one language in).
PATCH_INI = '[General]\nbBorderRegionsEnabled=0\n'

# The addon slot this patch takes over, as `MakeWorldspaceArrays()` declares it.
# Read out of the shipped source (scripts/source/aaashiputilityscript.psc, the
# entry commented ";14"), and re-verified against the compiled script every run:
# pex_patch refuses to touch a literal that is not there exactly once.
REPLACES_WORLDSPACE = 'RigmorCyrodiil'
REPLACES_PLUGIN = 'RigmorCyrodiil.esm'
REPLACES_FORMID = 0x2F4DB2

# TES4 gives its overworld the FormID 003C in every master, and the converter
# keeps a record's source id, so this resolves whatever the plugin renamed it
# to. `--worldspace` overrides it for a plugin whose sea route belongs
# somewhere else.
TES4_OVERWORLD = 0x00003C

CELL_SIZE = 4096.0


def zstring(payload):
    return payload.split(b'\0', 1)[0].decode('cp1252', 'replace')


def first(subs, sig):
    for s, payload in subs:
        if s == sig:
            return payload
    return None


# ---------------------------------------------------------------------------
# The destination, read out of the converted plugin
# ---------------------------------------------------------------------------

class Destination:
    """The converted worldspace a sea route can land in."""

    def __init__(self, plugin, path, fid, edid, water):
        self.plugin = plugin
        self.path = path
        self.fid = fid
        self.edid = edid
        self.water = water


def read_destination(plugin, path, want_edid=None):
    """The overworld WRLD of a converted plugin: its EditorID and sea level."""
    from tools.esm.tes5_esm_reader import read_tes5_file
    result = read_tes5_file(path, parse_types={'WRLD'})
    records = [x for x in result if isinstance(x, list)][0]
    chosen = None
    for rec in records:
        if rec.type != 'WRLD':
            continue
        subs = {s.type: s.data for s in rec.subrecords}
        edid = zstring(subs.get('EDID', b'\0'))
        if want_edid:
            if edid != want_edid:
                continue
        elif (rec.form_id & 0xFFFFFF) != TES4_OVERWORLD:
            continue
        water = 0.0
        if len(subs.get('DNAM', b'')) == 8:
            water = struct.unpack('<ff', subs['DNAM'])[1]
        chosen = Destination(plugin, path, rec.form_id, edid, water)
        break
    if chosen is None:
        raise SystemExit(
            f'{plugin} has no worldspace ' +
            (f'called "{want_edid}"' if want_edid else
             f'at local FormID {TES4_OVERWORLD:06X} -- name one with '
             '--worldspace'))
    return chosen


def land_heights(path, worldspace_fid, cells):
    """{(cx, cy): (min, max)} terrain height for the cells asked for."""
    from tools.esm.tes5_esm_reader import read_tes5_file
    result = read_tes5_file(path, parse_types={'CELL', 'LAND'})
    records = [x for x in result if isinstance(x, list)][0]
    grid = {}
    for rec in records:
        if rec.type != 'CELL' or rec.parent_wrld != worldspace_fid:
            continue
        subs = {s.type: s.data for s in rec.subrecords}
        if 'XCLC' not in subs:
            continue
        coord = struct.unpack_from('<ii', subs['XCLC'], 0)
        if coord in cells:
            grid[rec.form_id] = coord
    out = {}
    for rec in records:
        if rec.type != 'LAND' or rec.parent_cell not in grid:
            continue
        for sub in rec.subrecords:
            if sub.type != 'VHGT' or len(sub.data) < 4 + 1089:
                continue
            offset = struct.unpack_from('<f', sub.data, 0)[0]
            deltas = struct.unpack_from('<1089b', sub.data, 4)
            values = []
            row = offset
            for j in range(33):
                row += deltas[j * 33]
                point = row
                for i in range(1, 33):
                    point += deltas[j * 33 + i]
                    values.append(point * 8.0)
                values.append(row * 8.0)
            out[grid[rec.parent_cell]] = (min(values), max(values))
    return out


def check_anchorage(dest, x, y):
    """Verify the landing point is open water. Returns (cell_x, cell_y)."""
    cell = (int(x // CELL_SIZE), int(y // CELL_SIZE))
    heights = land_heights(dest.path, dest.fid, {cell})
    if cell not in heights:
        raise SystemExit(
            f'{dest.edid} has no terrain at cell {cell} -- the ship would '
            'arrive outside the worldspace. Pick another --landing')
    low, high = heights[cell]
    print(f'  anchorage: cell {cell}, terrain {low:.0f}..{high:.0f}, '
          f'sea level {dest.water:.0f}')
    if high >= dest.water:
        raise SystemExit(
            f'the terrain at cell {cell} reaches {high:.0f}, at or above the '
            f'{dest.water:.0f} sea level -- that is land, not an anchorage. '
            'Pick another --landing')
    return cell


# ---------------------------------------------------------------------------
# The gate, found in Sailable Ship by what it points at
# ---------------------------------------------------------------------------

def find_gate(source, worldspace):
    """(fid, header, subs, command) of the sea gate landing in `worldspace`."""
    needle = f'CenterOnWorld {worldspace} '.lower()
    hits = []
    for fid, (header, subs) in source.by_type['REFR'].items():
        vmad = first(subs, 'VMAD')
        if not vmad:
            continue
        for name, props in read_vmad(vmad):
            if name.lower() != TELEPORT_SCRIPT.lower():
                continue
            command = props.get('LandingWorldSpace')
            if isinstance(command, str) and command.lower().startswith(needle):
                hits.append((fid, header, subs, command))
    if len(hits) != 1:
        raise SystemExit(
            f'{len(hits)} sea gates land in "{worldspace}"; expected exactly '
            'one. Sailable Ship may have changed -- check which reference '
            'carries the route before rerunning')
    return hits[0]


def read_vmad(vmad):
    """[(script name, {property: value})] -- scalars only, arrays skipped."""
    ver, objfmt = struct.unpack_from('<hh', vmad, 0)
    pos = 4
    out = []

    def wstring(p):
        length = struct.unpack_from('<H', vmad, p)[0]
        return vmad[p + 2:p + 2 + length].decode('cp1252'), p + 2 + length

    def scalar(p, ptype):
        if ptype == 1:
            return None, p + 8
        if ptype == 2:
            return wstring(p)
        if ptype == 3:
            return struct.unpack_from('<i', vmad, p)[0], p + 4
        if ptype == 4:
            return struct.unpack_from('<f', vmad, p)[0], p + 4
        if ptype == 5:
            return bool(vmad[p]), p + 1
        raise SystemExit(f'VMAD property type {ptype} not understood')

    count = struct.unpack_from('<H', vmad, pos)[0]
    pos += 2
    for _ in range(count):
        name, pos = wstring(pos)
        if ver >= 4:
            pos += 1
        nprops = struct.unpack_from('<H', vmad, pos)[0]
        pos += 2
        props = {}
        for _ in range(nprops):
            pname, pos = wstring(pos)
            ptype = vmad[pos]
            pos += 2
            if ptype <= 5:
                props[pname], pos = scalar(pos, ptype)
            elif 11 <= ptype <= 15:
                n = struct.unpack_from('<I', vmad, pos)[0]
                pos += 4
                for _ in range(n):
                    _v, pos = scalar(pos, ptype - 10)
            else:
                raise SystemExit(f'VMAD property type {ptype} not understood')
        out.append((name, props))
    return out


# ---------------------------------------------------------------------------
# What stops a ship from ever REACHING a gate
# ---------------------------------------------------------------------------
#
# Two separate barriers sit between the player and the sea gates, and both are
# outside anything this patch used to touch. Measured 2026-08-28:
#
#  * BORDER REGION. Skyrim.esm has exactly one REGN carrying record-header flag
#    0x40 -- `BorderRegionSkyrim` (000C5859), a 173-point polygon over Tamriel
#    spanning X[-188714..213174] Y[-132575..169851]. Every one of Sailable
#    Ship's eight Tamriel gates is NORTH of it (the nearest is Y 174372), so
#    with border regions on, none of them can be sailed to: the player gets
#    "You cannot go that way". Only `bBorderRegionsEnabled=0` turns it off.
#
#  * WORLDSPACE OBJECT BOUNDS. Vanilla Tamriel is NAM0 (-233472, -176128) ..
#    NAM9 (253952, 208896); six of the eight gates are outside that, up to
#    Y 289334 and X -277223. Sailable Ship therefore overrides the Tamriel WRLD
#    with widened bounds -- and ANY later plugin that also overrides Tamriel
#    puts the vanilla numbers back, because two plugins overriding one record
#    do not merge. A CK-saved personal patch does this by accident constantly.
#
# The bounds are re-asserted here so the route survives that; the border region
# cannot be (see PATCH_INI).

def gate_worldspaces(source):
    """{worldspace FormID: [(x, y), ...]} for every sea gate the mod places."""
    base = None
    for fid, (_hdr, subs) in source.by_type['ACTI'].items():
        if zstring(first(subs, 'EDID') or b'\0') == GATE_ACTIVATOR:
            base = fid
            break
    if base is None:
        raise SystemExit(f'{SHIP_PLUGIN} has no "{GATE_ACTIVATOR}" activator; '
                         'the mod has changed too much for this patch')
    out = {}
    for fid, (_hdr, subs) in source.by_type['REFR'].items():
        name = first(subs, 'NAME')
        data = first(subs, 'DATA')
        if not name or not data or struct.unpack('<I', name)[0] != base:
            continue
        world = None
        for gtype, label in source.chains[('REFR', fid)]:
            if gtype == GT_WORLD_CHILDREN:
                world = struct.unpack('<I', label)[0]
        if world is not None:
            out.setdefault(world, []).append(struct.unpack_from('<ff', data, 0))
    return out


def local_worldspace_names():
    """{worldspace FormID: FULL payload} as the patches next to us name them.

    Vanilla's Tamriel FULL is an lstring, so it reads in the player's language;
    Sailable Ship's override replaces it with the literal "Skyrim", and a
    personal patch that puts the translated name back is the usual answer. This
    patch overrides the same record to re-assert the bounds, so it has to carry
    that name through or it silently un-translates the world. FULL holds no
    FormID, so carrying it needs no extra master.
    """
    import glob
    names = {}
    for folder in ('output', 'sources'):
        for path in sorted(glob.glob(os.path.join(REPO, 'patch_folder', folder,
                                                  '*.es[pm]'))):
            if os.path.basename(path) == PLUGIN_NAME:
                continue
            try:
                other = ChainedSource(path, {'WRLD'})
            except Exception:
                continue
            for fid, (_hdr, subs) in other.by_type['WRLD'].items():
                full = first(subs, 'FULL')
                if full is not None:
                    names[fid] = (full, os.path.basename(path))
    return names


def widen_world_bounds(patch, source, mapping, quiet=False):
    """Re-assert the object bounds of every VANILLA worldspace holding a gate.

    Only worldspaces the mod does not own itself: nobody else overrides its
    five oceans, while Tamriel is one of the most-overridden records in Skyrim.
    The record copied is Sailable Ship's own, which is not localized, so its
    FULL is a literal and nothing has to be resolved through a STRINGS file.
    """
    written = []
    local_names = local_worldspace_names()
    for world, gates in sorted(gate_worldspaces(source).items()):
        if (world >> 24) >= source.own_index:
            continue
        record = source.by_type['WRLD'].get(world)
        if record is None:
            continue
        subs = dict(record[1])
        if 'NAM0' not in subs or 'NAM9' not in subs:
            continue
        minx, miny = struct.unpack('<ff', subs['NAM0'])
        maxx, maxy = struct.unpack('<ff', subs['NAM9'])
        want = (min([minx] + [x for x, _y in gates]) - BOUNDS_MARGIN,
                min([miny] + [y for _x, y in gates]) - BOUNDS_MARGIN,
                max([maxx] + [x for x, _y in gates]) + BOUNDS_MARGIN,
                max([maxy] + [y for _x, y in gates]) + BOUNDS_MARGIN)
        hdr, out_subs = remap_record('WRLD', *record, mapping)
        keep_name, from_plugin = local_names.get(world, (None, None))
        if keep_name == subs.get('FULL'):
            keep_name = None
        out_subs = [(sig, struct.pack('<ff', *want[:2]) if sig == 'NAM0' else
                     struct.pack('<ff', *want[2:]) if sig == 'NAM9' else
                     keep_name if sig == 'FULL' and keep_name else payload)
                    for sig, payload in out_subs]
        patch.add('WRLD', struct.unpack_from('<I', hdr, 12)[0], hdr, out_subs)
        edid = zstring(subs.get('EDID', b'\0'))
        written.append((world, edid, len(gates), (minx, miny, maxx, maxy), want))
        if not quiet:
            print(f'  bounds:  {edid} ({world:08X}) holds {len(gates)} gates, '
                  f'X {want[0]:.0f}..{want[2]:.0f} Y {want[1]:.0f}..{want[3]:.0f}'
                  + ('' if (minx, miny, maxx, maxy) == want else
                     f' (was {minx:.0f}..{maxx:.0f} / {miny:.0f}..{maxy:.0f})'))
            if keep_name:
                # A translated name is UTF-8 in the file; fall back to the
                # single-byte codepage the rest of the format uses.
                raw = keep_name.split(b'\0', 1)[0]
                try:
                    shown = raw.decode('utf-8')
                except UnicodeDecodeError:
                    shown = raw.decode('cp1252', 'replace')
                print(f'           keeping the name {from_plugin} gives it: '
                      f'"{shown}"'.encode(sys.stdout.encoding or 'ascii',
                                          'replace')
                      .decode(sys.stdout.encoding or 'ascii'))
    return written


# ---------------------------------------------------------------------------
# The cargo-mission addon's port marker
# ---------------------------------------------------------------------------

def find_port_marker(missions, gate_pos):
    """(fid, header, subs) of the Missions port marker belonging to one gate.

    Chosen the way the mod itself chooses it -- the closest marker within 4000
    units -- rather than by EditorID, so a renamed record still resolves.
    """
    best = None
    for fid, (header, subs) in missions.by_type['REFR'].items():
        vmad = first(subs, 'VMAD')
        data = first(subs, 'DATA')
        if not vmad or not data:
            continue
        if not any(name.lower() == PORT_MARKER_SCRIPT.lower()
                   for name, _props in read_vmad(vmad)):
            continue
        x, y, _z = struct.unpack_from('<fff', data, 0)
        far = ((x - gate_pos[0]) ** 2 + (y - gate_pos[1]) ** 2) ** 0.5
        if far <= PORT_MARKER_RADIUS and (best is None or far < best[0]):
            best = (far, fid, header, subs)
    if best is None:
        return None
    return best[1], best[2], best[3]

def missing_script_types(*bsas):
    """Types the mod's own scripts reference but do not ship.

    Papyrus resolves a property's TYPE at link time even when the property is
    never assigned, so a script naming a type it cannot find fails to link --
    and every script holding a property of THAT type fails with it. One missing
    file therefore takes down a whole mod's script graph.

    Sailable Ship walks straight into this: `aaaShipUtilityScript`,
    `aaaShipMapShipScript` and `aaaShipSailInteriorScript` all name
    `aaaSMUtilityScript`, which lives in the optional `Sailable Ship
    Missions.esp` and is in neither its BSA nor the base download. The mod
    treats Missions as optional at RUNTIME (`CheckAddons()` handles its
    absence) but not at LINK time. Diagnosed 2026-08-28 from the Papyrus log,
    after the whole mod went script-dead in game.

    Every archive given is searched, so installing the addon that supplies a
    type clears the warning instead of leaving a permanent false alarm.
    """
    from tools.patch.pex_patch import Pex
    from asset_convert.bsa_extract import read_bsa_files, list_bsa_files
    per_bsa = {}
    shipped = set()
    for bsa in bsas:
        if bsa is None:
            continue
        names = [n for n in list_bsa_files(str(bsa))
                 if n.lower().endswith('.pex')]
        if not names:
            continue
        per_bsa[str(bsa)] = names
        shipped |= {n.split(chr(92))[-1][:-4].lower() for n in names}
    missing = {}
    for bsa, names in per_bsa.items():
        for name, blob in read_bsa_files(bsa, names).items():
            short = name.split(chr(92))[-1]
            for text in Pex(blob).strings:
                low = text.lower()
                if (low.startswith('aaa') and 'script' in low
                        and low not in shipped):
                    missing.setdefault(low, []).append(short)
    return missing


def warn_missing_types(*bsas):
    missing = missing_script_types(*bsas)
    if not missing:
        print('  script types: all resolvable from the installed BSAs')
        return
    print()
    print('  !! MISSING PAPYRUS TYPES -- the mod cannot link without these:')
    for kind, users in sorted(missing.items()):
        print(f'     {kind}  <- referenced by {", ".join(sorted(users))}')
    print('     Papyrus resolves property TYPES at link time even when the')
    print('     property is never used, so every script holding one of these')
    print('     fails to link -- and so does everything holding a property of')
    print('     THOSE. In game that means the whole mod goes dead: no cabin,')
    print('     no helm, no transitions, and this patch cannot run either.')
    print('     Install the addon that supplies them (for aaaSMUtilityScript')
    print('     that is "Sailable Ship Missions"), or drop a compiled stub of')
    print('     the type into Data/Scripts/.')
    print()


def patch_utility_script(dest, out_path, dry_run=False):
    """Extract aaaShipUtilityScript.pex from the mod's BSA and retarget it."""
    import subprocess
    bsa = locate_plugin(SHIP_BSA)
    if bsa is None:
        raise SystemExit(f'cannot find {SHIP_BSA}; it ships the compiled '
                         'script this patch has to replace')
    from asset_convert.bsa_extract import read_bsa_files
    member = 'scripts' + chr(92) + UTILITY_SCRIPT.lower() + '.pex'
    found = read_bsa_files(str(bsa), [member])
    if not found:
        raise SystemExit(f'{member} is not in {bsa}')
    raw = list(found.values())[0]

    scratch = out_path + '.orig'
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(scratch, 'wb') as fh:
        fh.write(raw)
    argv = [sys.executable, '-u',
            os.path.join(REPO, 'tools', 'patch', 'pex_patch.py'), scratch,
            '--set-string', f'{REPLACES_PLUGIN}={dest.plugin}',
            '--set-int', f'{REPLACES_FORMID}={dest.fid & 0xFFFFFF}',
            '--expect-string', WORLDSPACE_FUNC,
            '--expect-string', UTILITY_SCRIPT]
    if dry_run:
        argv.append('--dry-run')
    else:
        argv += ['--out', out_path]
    result = subprocess.run(argv, cwd=REPO)
    os.remove(scratch)
    if result.returncode != 0:
        raise SystemExit('retargeting the compiled script failed')
    return out_path


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------

def required_masters(output_dir):
    """Sailable Ship's own masters, then Sailable Ship.

    Every one of them is already forced by Sailable Ship itself, so listing
    them costs a user nothing they do not already have -- and `remap_from`
    needs the full list, because it maps every index the source declares.
    """
    ship = locate_plugin(SHIP_PLUGIN, output_dir)
    if ship is None:
        raise SystemExit(f'cannot find {SHIP_PLUGIN}; put the mod in '
                         'patch_folder/sources/Sailable Ship/')
    from tools.patch.plugin_patch import read_masters
    with open(ship, 'rb') as fh:
        names = read_masters(fh.read(8192))
    names.append(SHIP_PLUGIN)
    # Missions is mastered only when it is actually installed: the patch reads
    # a record out of it, and a patch that masters a file the player does not
    # have simply refuses to load.
    if locate_plugin(MISSIONS_PLUGIN, output_dir) is not None:
        names.append(MISSIONS_PLUGIN)
    return order_masters(names, lambda n: locate_plugin(n, output_dir))


def build(dest, landing, cell, output_dir, quiet=False):
    masters = required_masters(output_dir)
    patch = PatchPlugin(masters,
                        description=f'Sailable Ship route to {dest.edid}')
    if not quiet:
        print('  masters: ' + ', '.join(masters))

    ship_path = locate_plugin(SHIP_PLUGIN, output_dir)
    source = ChainedSource(ship_path, {'REFR', 'CELL', 'WRLD', 'ACTI'})
    mapping = patch.remap_from(source)

    fid, header, subs, old_command = find_gate(source, REPLACES_WORLDSPACE)
    if not quiet:
        print(f'  gate: {fid:08X}  "{old_command}"')

    command = f'CenterOnWorld {dest.edid} {cell[0]} {cell[1]}'
    header, subs = remap_record('REFR', header, subs, mapping)
    subs = [(sig, vmad_set_properties(payload, TELEPORT_SCRIPT, {
                'LandingWorldSpace': command,
                'Xpos': int(landing[0]),
                'Ypos': int(landing[1]),
                'ZWaterHeight': int(round(dest.water)),
            }) if sig == 'VMAD' else payload)
            for sig, payload in subs]

    chain = remap_chain(source.chains[('REFR', fid)], mapping)
    patch.add_nested(chain, 'REFR', struct.unpack_from('<I', header, 12)[0],
                     header, subs)
    # A nested reference only resolves if its cell -- and that cell's
    # worldspace -- exist in the patch as plain overrides.
    parents = []
    for gtype, label in source.chains[('REFR', fid)]:
        target = struct.unpack('<I', label)[0]
        sig = 'CELL' if gtype == 6 else 'WRLD' if gtype == 1 else None
        if sig and target in source.by_type[sig]:
            phdr, psubs = remap_record(sig, *source.by_type[sig][target],
                                       mapping)
            patch.add_parent(sig, struct.unpack_from('<I', phdr, 12)[0],
                             phdr, psubs)
            parents.append(f'{sig} {target:08X}')
    if not quiet:
        print(f'  parents: {", ".join(parents)}')
        print(f'  route:   "{command}"')
        print(f'  landing: {int(landing[0])}, {int(landing[1])}, '
              f'water {int(round(dest.water))}')

    widen_world_bounds(patch, source, mapping, quiet)
    add_port_marker(patch, source, fid, landing, dest, output_dir, quiet)
    return patch, command


def add_port_marker(patch, source, gate_fid, landing, dest, output_dir,
                    quiet=False):
    """Point the cargo addon's port marker at the same landing as the gate.

    `Sailable Ship Missions.esp` puts one `aaaSMPortMarkerScript` reference
    beside every route's gate, and its PosX/PosY/PosZ properties are the dock
    it teleports itself onto once the ship arrives. For this route those are
    still Rigmor's dock -- a THIRD thing in the mod family that carries Rigmor
    geometry, on top of the two literals the base plugin has -- so a cargo run
    to Cyrodiil would drop its port somewhere in the middle of our map, below
    the water line. Skipped entirely when Missions is not installed.
    """
    path = locate_plugin(MISSIONS_PLUGIN, output_dir)
    if path is None:
        if not quiet:
            print(f'  missions: {MISSIONS_PLUGIN} not installed, port marker '
                  'left alone')
        return None
    gate_data = first(source.by_type['REFR'][gate_fid][1], 'DATA')
    gate_pos = struct.unpack_from('<ff', gate_data, 0)
    missions = ChainedSource(path, {'REFR', 'CELL', 'WRLD'})
    mapping = patch.remap_from(missions)
    found = find_port_marker(missions, gate_pos)
    if found is None:
        if not quiet:
            print(f'  missions: no {PORT_MARKER_SCRIPT} within '
                  f'{PORT_MARKER_RADIUS:.0f} units of the gate')
        return None
    fid, header, subs = found
    before = dict(read_vmad(first(subs, 'VMAD'))[0][1])
    values = {'PosX': int(landing[0]), 'PosY': int(landing[1]),
              'PosZ': int(round(dest.water))}
    header, subs = remap_record('REFR', header, subs, mapping)
    subs = [(sig, vmad_set_properties(payload, PORT_MARKER_SCRIPT, values)
             if sig == 'VMAD' else payload) for sig, payload in subs]
    chain = remap_chain(missions.chains[('REFR', fid)], mapping)
    patch.add_nested(chain, 'REFR', struct.unpack_from('<I', header, 12)[0],
                     header, subs)
    if not quiet:
        print(f'  missions: port marker {fid:08X} '
              f'({missions.edid("REFR", fid)}) '
              f'{before.get("PosX")},{before.get("PosY")},'
              f'{before.get("PosZ")} -> '
              f'{values["PosX"]},{values["PosY"]},{values["PosZ"]}')
    return fid


# ---------------------------------------------------------------------------
# Verification -- the structural gate barely covers a three-record patch
# ---------------------------------------------------------------------------

def verify(out_path, script_path, dest, landing, cell, output_dir):
    """Prove the patch changed the route and NOTHING else.

    `verify_npc_patch.py` gates the file's structure, but its fidelity and
    master checks only look at NPC_ records, so for this patch they pass
    vacuously. These are the checks that actually bite.
    """
    ship_path = locate_plugin(SHIP_PLUGIN, output_dir)
    missions_path = locate_plugin(MISSIONS_PLUGIN, output_dir)
    source = ChainedSource(ship_path, {'REFR', 'CELL', 'WRLD', 'ACTI'})
    patch_src = ChainedSource(out_path, {'REFR', 'CELL', 'WRLD'})
    mapping = {i: i for i in range(source.own_index + 1)}
    # The patch lists Sailable Ship's masters then Sailable Ship, in that
    # order, so indexes are unchanged -- assert that rather than assume it.
    expect_masters = source.masters + [SHIP_PLUGIN]
    if missions_path is not None:
        expect_masters = expect_masters + [MISSIONS_PLUGIN]
    if patch_src.masters != expect_masters:
        mapping = None

    failures = []

    def check(name, ok, detail=''):
        print(f'  {"PASS" if ok else "FAIL"}  {name:12} {detail}')
        if not ok:
            failures.append(name)

    check('masters', mapping is not None,
          ', '.join(patch_src.masters))
    if mapping is None:
        raise SystemExit('master order changed; the checks below cannot run')

    gate_fid, _h, src_subs, _c = find_gate(source, REPLACES_WORLDSPACE)
    gate_pos = struct.unpack_from('<ff', first(src_subs, 'DATA'), 0)
    marker_fid = None
    if missions_path is not None:
        missions = ChainedSource(missions_path, {'REFR', 'CELL', 'WRLD'})
        found = find_port_marker(missions, gate_pos)
        marker_fid = found[0] if found else None
    refrs = list(patch_src.by_type['REFR'])
    expect_refrs = [gate_fid] + ([marker_fid] if marker_fid else [])
    check('references', sorted(refrs) == sorted(expect_refrs),
          ' '.join('%08X' % f for f in refrs))

    _hdr, out_subs = patch_src.by_type['REFR'][gate_fid]
    src_map = dict(src_subs)
    same = [sig for sig, payload in out_subs
            if sig != 'VMAD' and src_map.get(sig) == payload]
    other = [sig for sig, payload in out_subs
             if sig != 'VMAD' and src_map.get(sig) != payload]
    check('untouched', not other,
          f'{len(same)} subrecords byte-identical' +
          (f'; CHANGED {other}' if other else ''))
    check('field order', [s for s, _p in out_subs] == [s for s, _p in src_subs],
          ', '.join(s for s, _p in out_subs))

    before = dict(read_vmad(src_map['VMAD'])[0][1])
    after = dict(read_vmad(dict(out_subs)['VMAD'])[0][1])
    check('properties', sorted(before) == sorted(after),
          ', '.join(sorted(after)))
    expected = {
        'LandingWorldSpace': f'CenterOnWorld {dest.edid} {cell[0]} {cell[1]}',
        'Xpos': int(landing[0]), 'Ypos': int(landing[1]),
        'ZWaterHeight': int(round(dest.water)),
    }
    wrong = {k: (before.get(k), after.get(k)) for k in before
             if after.get(k) != expected.get(k, before.get(k))}
    check('route', not wrong, str(expected) if not wrong else f'wrong: {wrong}')

    if marker_fid is not None:
        _mh, msubs = patch_src.by_type['REFR'][marker_fid]
        got = dict(read_vmad(first(msubs, 'VMAD'))[0][1])
        want = {'PosX': int(landing[0]), 'PosY': int(landing[1]),
                'PosZ': int(round(dest.water))}
        check('port marker',
              all(got.get(k) == v for k, v in want.items()),
              f'{marker_fid:08X} -> ' + ', '.join(f'{k}={got.get(k)}'
                                                  for k in sorted(want)))

    # The worldspaces the bounds pass re-asserts, and everything it did not.
    widened = {w for w, _e, _n, _was, _now in
               widen_world_bounds(PatchPlugin(patch_src.masters), source,
                                  mapping, quiet=True)}
    for sig in ('CELL', 'WRLD'):
        bad = [f'{f:08X}' for f, (_h2, subs) in patch_src.by_type[sig].items()
               if f not in widened
               and source.by_type[sig].get(f, (None, None))[1] != subs]
        check(f'{sig.lower()} parent', not bad,
              f'{len(patch_src.by_type[sig]) - len(widened & set(patch_src.by_type[sig]))}'
              ' copied verbatim' + (f'; CHANGED {bad}' if bad else ''))

    gates = gate_worldspaces(source)
    outside = []
    for world in sorted(widened):
        subs = dict(patch_src.by_type['WRLD'][world][1])
        minx, miny = struct.unpack('<ff', subs['NAM0'])
        maxx, maxy = struct.unpack('<ff', subs['NAM9'])
        outside += [f'{world:08X} ({x:.0f},{y:.0f})' for x, y in gates[world]
                    if not (minx <= x <= maxx and miny <= y <= maxy)]
    check('gate bounds', widened and not outside,
          f'{len(widened)} worldspace(s), every gate inside' if not outside
          else f'OUTSIDE: {outside}')

    # The script: everything outside the string table must be untouched except
    # the one 5-byte int operand.
    from tools.patch.pex_patch import Pex
    from asset_convert.bsa_extract import read_bsa_files
    bsa = locate_plugin(SHIP_BSA)
    member = 'scripts' + chr(92) + UTILITY_SCRIPT.lower() + '.pex'
    before_pex = Pex(list(read_bsa_files(str(bsa), [member]).values())[0])
    after_pex = Pex(open(script_path, 'rb').read())
    check('pex strings',
          REPLACES_PLUGIN not in after_pex.strings
          and dest.plugin in after_pex.strings
          and len(after_pex.strings) == len(before_pex.strings),
          f'{len(after_pex.strings)} entries, "{dest.plugin}" in, '
          f'"{REPLACES_PLUGIN}" out')
    a, b = before_pex.code, after_pex.code
    differing = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    span = (differing[-1] - differing[0] + 1) if differing else 0
    check('pex code', len(a) == len(b) and span <= 5,
          f'{len(differing)} bytes differ, all within {span} bytes '
          '(the one int operand)')

    if failures:
        raise SystemExit('verification failed: ' + ', '.join(failures))
    print('  all checks passed')


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugins', nargs='+', required=True,
                    help='converted plugins; the first one carrying an '
                         'overworld provides the destination')
    ap.add_argument('--worldspace',
                    help='destination WRLD EditorID (default: the plugin\'s '
                         'own TES4 overworld, local FormID 00003C)')
    ap.add_argument('--landing', nargs=2, type=float, metavar=('X', 'Y'),
                    help='where the ship is put down (default: the '
                         'coordinates the route already carries)')
    ap.add_argument('--output-dir', default=os.path.join(REPO, 'output'))
    ap.add_argument('--out', help='ESP to write')
    ap.add_argument('--script-dir',
                    help='where the replacement .pex goes (default: '
                         'patch_folder/output/%s/)' % SCRIPT_SUBDIR)
    ap.add_argument('--no-verify', action='store_true',
                    help='skip the post-build checks (they are cheap; '
                         'only for debugging)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    out_path = args.out or os.path.join(OUT_DIR, PLUGIN_NAME)
    script_dir = args.script_dir or os.path.join(OUT_DIR, SCRIPT_SUBDIR)
    print('ship port patch (%s): %s' % (os.path.basename(out_path),
                                        ', '.join(args.plugins)))

    # One route lands in one worldspace, so the first ticked plugin that has an
    # overworld provides it. The rest are ignored rather than refused: the GUI
    # ticks every converted plugin by default, and an ESP with no overworld is
    # a perfectly normal thing to have ticked.
    dest = None
    reasons = []
    for plugin in args.plugins:
        path = find_converted(str(args.output_dir), plugin)
        if path is None:
            raise SystemExit(f'{plugin} is not built in {args.output_dir} -- '
                             'convert it first')
        try:
            dest = read_destination(plugin, path, args.worldspace)
            break
        except SystemExit as why:
            reasons.append(str(why))
    if dest is None:
        raise SystemExit('no ticked plugin carries a landable worldspace:\n  '
                         + '\n  '.join(reasons))
    print(f'  destination: {dest.edid} ({dest.fid:08X}) in {dest.plugin}, '
          f'sea level {dest.water:.0f}')

    warn_missing_types(locate_plugin(SHIP_BSA),
                       locate_plugin(MISSIONS_BSA))

    ship_path = locate_plugin(SHIP_PLUGIN, args.output_dir)
    if ship_path is None:
        raise SystemExit(f'cannot find {SHIP_PLUGIN}; put the mod in '
                         'patch_folder/sources/Sailable Ship/')
    probe = ChainedSource(ship_path, {'REFR'})
    _fid, _hdr, subs, _cmd = find_gate(probe, REPLACES_WORLDSPACE)
    props = dict(read_vmad(first(subs, 'VMAD'))[0][1])
    landing = (args.landing if args.landing
               else (props['Xpos'], props['Ypos']))
    cell = check_anchorage(dest, landing[0], landing[1])

    if args.dry_run:
        patch_utility_script(dest, os.path.join(script_dir,
                                                UTILITY_SCRIPT + '.pex'),
                             dry_run=True)
        print('  DRY RUN -- nothing written')
        return 0

    patch, _command = build(dest, landing, cell, args.output_dir)
    size, records, groups = patch.write(out_path)
    print('  wrote %s  (%s bytes, %d records, %d groups)'
          % (out_path, format(size, ','), records, groups))
    # Skyrim reads Data/<plugin name>.ini for every plugin it loads, which is
    # how Sailable Ship itself turns border regions off. Shipping our own copy
    # means the route does not depend on the mod's file surviving deployment.
    ini_path = os.path.splitext(out_path)[0] + '.ini'
    with open(ini_path, 'w', encoding='ascii', newline='\r\n') as fh:
        fh.write(PATCH_INI)
    print('  wrote %s  (bBorderRegionsEnabled=0)' % ini_path)
    script = patch_utility_script(
        dest, os.path.join(script_dir, UTILITY_SCRIPT + '.pex'))
    if args.no_verify:
        return 0
    print()
    print('verifying')
    verify(out_path, script, dest, landing, cell, args.output_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
