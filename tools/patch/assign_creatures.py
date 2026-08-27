#!/usr/bin/env python3
"""Swap converted Oblivion creatures for vanilla Skyrim ones, in an override ESP.

Reads the decisions in `patch_folder/sources/creature_changes.py` and writes
`MyOwnTamrielCreaturePatch.esp`: one `NPC_` override per creature that has a
vanilla stand-in, plus the `LVLN` and `ACHR` overrides a deletion needs.

    python tools/patch/assign_creatures.py --plugins Oblivion.esm
    python tools/patch/assign_creatures.py --plugins Oblivion.esm ElsweyrAnequina.esp \\
        --out patch_folder/output/MyOwnTamrielCreaturePatch.esp --report r.tsv
    python tools/patch/assign_creatures.py --plugins Oblivion.esm --exact-only --dry-run

WHAT IT WRITES, AND WHY THAT IS ENOUGH
--------------------------------------
A swap replaces the actor's visual/animation shell and nothing else. The shell
is the race PLUS the AI fields the vanilla actors of that race use, each voted
for in `creature_changes.py`:

    RNAM  the vanilla race       -- brings its skeleton and behavior graph
    WNAM  the skin its vanilla actors wear -- and NO WNAM where they carry
          none, so the actor inherits the race's exactly as vanilla does
    ATKR  the vanilla race       -- so attack data comes from it too
    VTCK  the race's own voice   -- the vanilla graph fires vanilla sound
          events, which the converted voice type has no entries for
    ZNAM  the race's combat style
    CNAM  the race's class
    DPLT  the race's default package list
    DOFT  the race's default outfit, where it has one -- a creature's kit,
          e.g. the frostbite spider's SpiderSpitOutfit

CLONE MODE IS THE DEFAULT (2026-08-27, second in-game round)
------------------------------------------------------------
Shipping only the shell above fixed the goblins and left the spiders standing.
Measured cause: a converted spider carries ONE Oblivion faction where a vanilla
frostbite spider has three, plus converted paralysis lesser-powers and an
Oblivion inventory. A creature that belongs to no hostile faction has nobody to
attack. So the default is now to CLONE the vanilla donor actor wholesale
(`--no-clone` falls back to the shell swap), keeping only:

    EDID / FULL / SHRT   identity and the Oblivion name -- free, and losing
                         "Giant Tarantula" would be a regression nobody asked for
    NAM6 / NAM7          the size, which was explicitly to be kept
    VMAD                 converter-attached scripts; dropping one silently
                         breaks whatever quest logic hangs off the creature

Everything else -- factions, level, stats, spells, inventory, AI data, combat
style, keywords, sounds, death item -- comes from the donor. Verified: all 955
cloned records are byte-identical to their donor outside that keep-list, across
33 races. What that costs is real and deliberate: 798 creatures lose their
Oblivion abilities, 904 their Oblivion loot, 1,168 their Oblivion factions, and
levels become the vanilla creature's.

The donor is the most TYPICAL vanilla actor of the race -- the one agreeing with
the majority vote on the most fields, tie-broken towards an `Enc*` EditorID.
It is recorded per race in creature_changes.py, so it can be read and argued
with rather than guessed at.

WHY THE COMBAT STYLE MATTERS (2026-08-27, first in-game round)
-------------------------------------------------------------
The first build swapped only race/skin/attack-race/voice. In game the wolves
behaved and everything else stood still. Cause, measured: the converter stamps
`csWolf` on nearly every creature -- 646 of 914 in Oblivion.esm, 245 of 255 in
ElsweyrAnequina.esp, the rest `DefaultCombatstyle`. That is the correct vanilla
style for exactly one creature. On a wolf body it works; on a spider, a giant
or a skeleton it is a combat style the body cannot perform, and the actor never
engages. The class, package list and outfit were wrong for the same reason.

and for a mount (TES4 `CREA DATA.Type == 4`) also:

    KSIZ/KWDA  ActorTypeHorse    -- on the NPC_, never on the RACE
    CNAM       EncClassHorse
    DOFT       HorseSaddleOutfit, when the Oblivion record wore a saddle

Health, level, factions, inventory, packages, scripts and dialogue are NOT
touched: they stay in the record exactly as the converter wrote them, so a
level-40 Oblivion boss stays a level-40 boss wearing a vanilla body.

A REMOVAL IS THREE LAYERS
-------------------------
`remove`-tier creatures (the alfiq) need all three or the game is left with
null references:

  1. the placed `ACHR` references get the Initially Disabled record flag;
  2. every `LVLN` entry naming them is dropped from an override of that list;
  3. the base `NPC_` records are left alone -- deleting a record another
     plugin may reference is what breaks load orders, and a disabled,
     unlisted actor never appears anyway.

The one alfiq a script summons is kept by default (`ALFIQ_SUMMON_EXCEPTION`);
`--remove-summon` deletes it too and leaves the spell summoning nothing.
"""

import argparse
import csv
import importlib.util
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from tools.patch.patch_builder import (              # noqa: E402
    AFTER_ATKR, AFTER_CNAM, AFTER_DPLT, AFTER_KSIZ, AFTER_KWDA,
    AFTER_VTCK, AFTER_WNAM, AFTER_ZNAM,
    FLAG_INITIALLY_DISABLED, ChainedSource, PatchPlugin, locate_plugin,
    order_masters, remap_chain, remap_record, set_field,
)
from tools.patch.plugin_patch import (               # noqa: E402
    AFTER_DOFT, first, read_masters, zstring,
)
from tools.creature.creature_patch_census import read_crea   # noqa: E402

TABLE = os.path.join(REPO, 'patch_folder', 'sources', 'creature_changes.py')
OUT_DIR = os.path.join(REPO, 'patch_folder', 'output')
# One plugin per scope. Mounts ship separately because a rideable horse is the
# change a player notices first and must be able to install on its own.
SCOPE_PLUGIN = {
    'creatures': 'MyOwnTamrielCreaturePatch.esp',
    'mounts': 'MyOwnTamrielHorsePatch.esp',
    'all': 'MyOwnTamrielCreaturePatch.esp',
}

# Skyrim.esm records the mount plumbing needs. Verified on WhiterunPlayerHorse
# 00109E3D / EncHorseSaddledBrown 00023AB2; see creature_changes.py.
KW_ACTOR_TYPE_HORSE = 0x00026110
CLASS_HORSE = 0x0010F71E
OUTFIT_HORSE_SADDLE = 0x00060798


def load_table():
    spec = importlib.util.spec_from_file_location('creature_changes', TABLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_converted(output_dir, plugin):
    """The built plugin file for `plugin`, wherever output/ put it.

    A plugin converted on its own lands in `output/<plugin>/<plugin>`; one that
    came in as part of a mod lands in `output/<mod>/<plugin>`, which is why this
    searches rather than assuming.
    """
    direct = os.path.join(output_dir, plugin, plugin)
    if os.path.isfile(direct):
        return direct
    if not os.path.isdir(output_dir):
        return None
    for name in sorted(os.listdir(output_dir)):
        candidate = os.path.join(output_dir, name, plugin)
        if os.path.isfile(candidate):
            return candidate
    return None


class Decision:
    """What happens to one converted creature."""

    __slots__ = ('plugin', 'fid', 'edid', 'full', 'group', 'action', 'target',
                 'tier', 'coat', 'skin', 'saddled', 'is_mount', 'note')

    def __init__(self, plugin, fid, edid, full, group, action, target='',
                 tier='', coat='', skin=0, saddled=False, is_mount=False,
                 note=''):
        self.plugin = plugin
        self.fid = fid
        self.edid = edid
        self.full = full
        self.group = group
        self.action = action        # swap | remove | keep
        self.target = target
        self.tier = tier
        self.coat = coat            # skin EditorID, for the report
        self.skin = skin            # Skyrim.esm skin ARMO, overriding the
                                    # race's own WNAM (horse coats)
        self.saddled = saddled
        self.is_mount = is_mount
        self.note = note


def in_scope(table, decision, scope):
    """Does this decision belong in the patch being built?

    Mounts ship as their own plugin: a horse swap is the one change a player is
    guaranteed to notice immediately (it is what makes them rideable again), so
    it has to be installable and removable without dragging 900 other creatures
    along. The split is by TARGET family, not by the TES4 mount flag -- the
    Elsweyr wild horses and zebras are DATA.Type=Creature yet obviously belong
    with the horses, while the Slarjei mount becomes a DOG and belongs with the
    creatures.
    """
    if scope == 'all':
        return True
    if decision.action == 'remove':
        return scope == 'creatures'
    if decision.action != 'swap':
        return False
    family = table.SKYRIM_CREATURES[decision.target].family
    return (family == 'mount') if scope == 'mounts' else (family != 'mount')


def plan(table, plugins, output_dir, allow_near, do_remove):
    """Decide, per creature, before anything is read for writing.

    Returns (decisions, sources) where `sources` maps plugin name -> the census
    rows keyed by the converted FormID, so the writer does not census twice.
    """
    swaps_for = {'Oblivion.esm': table.OBLIVION_SWAPS,
                 'ElsweyrAnequina.esp': table.ELSWEYR_SWAPS}
    decisions = []
    census = {}
    for plugin in plugins:
        swaps = swaps_for.get(plugin)
        export_dir = os.path.join(REPO, 'export', plugin)
        rows = read_crea(export_dir, table)
        if rows is None:
            print(f'  {plugin}: no export/{plugin}/CREA.txt -- skipped')
            continue
        if swaps is None:
            print(f'  {plugin}: no swap table in creature_changes.py -- '
                  f'{len(rows)} creatures left converted')
            continue
        # The converter keeps the source FormID's low 24 bits, so the converted
        # NPC_ and the TES4 CREA are the same record. Verified 2026-08-27:
        # 914/914 for Oblivion.esm and 255/255 for ElsweyrAnequina.esp, with
        # every EditorID agreeing too.
        by_low = {}
        for row in rows:
            by_low[int(row['formid'], 16) & 0xFFFFFF] = row
        census[plugin] = by_low
        for low, row in by_low.items():
            swap = swaps.get(row['group'])
            if swap is None:
                decisions.append(Decision(plugin, low, row['edid'], row['full'],
                                          row['group'], 'keep',
                                          note='no row in the swap table'))
                continue
            if swap.tier == table.REMOVE:
                decisions.append(Decision(
                    plugin, low, row['edid'], row['full'], row['group'],
                    'remove' if do_remove else 'keep', tier=swap.tier,
                    note='' if do_remove else 'removal disabled with --no-remove'))
                continue
            if swap.target is None:
                decisions.append(Decision(plugin, low, row['edid'], row['full'],
                                          row['group'], 'keep', tier=swap.tier,
                                          note=swap.note[:80]))
                continue
            if swap.tier == table.NEAR and not allow_near:
                decisions.append(Decision(plugin, low, row['edid'], row['full'],
                                          row['group'], 'keep', swap.target,
                                          swap.tier, note='near, --exact-only'))
                continue
            is_mount = row['type'] == 4
            coat, skin, saddled = '', 0, False
            if swap.target == 'HorseRace':
                special = table.HORSE_SPECIALS.get(row['edid'])
                if special is not None:
                    # Shadowmere exists in both games; the unicorn does not, so
                    # the table names the coat to fall back on.
                    skin, coat = special[0], special[1]
                elif row['folder'] == 'horse':
                    # The AUTHORED coat is the body NIF, not the FULL name.
                    skin, coat, _actor = table.horse_coat(row['nifz'])
                else:
                    # Camels have no horse coat of their own: draw one keyed on
                    # the source FormID so it never moves between builds.
                    skin, coat, _actor = table.random_coat(low)
                saddled = any('saddle' in n for n in row['nifz'])
            decisions.append(Decision(plugin, low, row['edid'], row['full'],
                                      row['group'], 'swap', swap.target,
                                      swap.tier, coat, skin, saddled,
                                      is_mount))
    return decisions, census


def required_masters(table, plugins, decisions, output_dir, clone=True):
    """Every plugin the finished patch has to master, in load order.

    Computed from what the records actually reference. A patch that masters a
    DLC it never uses stops loading for everyone without that DLC.
    """
    names = ['Skyrim.esm']
    for plugin in plugins:
        path = find_converted(output_dir, plugin)
        if path is None:
            raise SystemExit(f'{plugin} is not built in {output_dir} -- convert '
                             'it first')
        # A converted plugin's own masters come first (ElsweyrAnequina.esp
        # rests on Oblivion.esm), then the plugin itself.
        with open(path, 'rb') as fh:
            names += read_masters(fh.read(4096))
        names.append(plugin)
    for d in decisions:
        if d.action != 'swap':
            continue
        creature = table.SKYRIM_CREATURES[d.target]
        names.append(creature.plugin)
        # Every field the swap writes has to name a master the patch lists.
        for value in (creature.skin, creature.voice, creature.combat_style,
                      creature.npc_class, creature.package_list,
                      creature.outfit):
            if value:
                names.append('Skyrim.esm' if (value >> 24) == 0
                             else creature.plugin)
        if clone and creature.donor:
            # A cloned record carries the donor's own references, so every
            # master the DONOR plugin lists has to be listed here too.
            path = locate_plugin(creature.plugin, output_dir)
            if path:
                with open(path, 'rb') as fh:
                    names += read_masters(fh.read(8192))
    return order_masters(names, lambda n: locate_plugin(n, output_dir))


def _fid_bytes(value):
    return struct.pack('<I', value)


def _plugin_of(patch, value, home):
    """Which master a FormID read out of the vanilla plugins belongs to.

    A field voted for by the actors of a DLC race is often a Skyrim.esm record
    (the riekling's package list, the burnt spriggan's voice), so the high byte
    decides rather than the race's own plugin.
    """
    return 'Skyrim.esm' if (value >> 24) == 0 else home


# Fields kept from the CONVERTED record when cloning a vanilla actor.
# Everything else -- factions, stats, level, spells, inventory, AI data, combat
# style, keywords, sounds -- comes from the donor, because "behaves exactly like
# the vanilla creature" is the whole point.
#   EDID/FULL/SHRT  identity and the Oblivion name, which cost nothing
#   NAM6/NAM7       the size, which the user asked to keep
#   VMAD            converter-attached scripts; dropping one silently breaks
#                   whatever quest logic the converter hung on the creature
CLONE_KEEP = ('EDID', 'FULL', 'SHRT', 'NAM6', 'NAM7', 'VMAD')

# Where a kept field goes when the donor does not have one of its own.
CLONE_SUCCESSORS = {
    'EDID': ('VMAD', 'OBND', 'ACBS'),
    'VMAD': ('OBND', 'ACBS'),
    'FULL': ('SHRT', 'DATA', 'DNAM'),
    'SHRT': ('DATA', 'DNAM'),
    'NAM6': ('NAM7', 'NAM8', 'CSDT', 'CSDI', 'CSDC', 'CSCR', 'DOFT'),
    'NAM7': ('NAM8', 'CSDT', 'CSDI', 'CSDC', 'CSCR', 'DOFT'),
}


def load_donors(patch, table, decisions, output_dir):
    """{race plugin: (ChainedSource, remap)} for every donor the build needs."""
    need = set()
    for d in decisions:
        if d.action != 'swap':
            continue
        creature = table.SKYRIM_CREATURES[d.target]
        if creature.donor:
            need.add(creature.plugin)
    donors = {}
    for plugin in sorted(need):
        path = locate_plugin(plugin, output_dir)
        if path is None:
            raise SystemExit(f'cannot find {plugin}, which the clone needs to '
                             'read its vanilla creatures from')
        src = ChainedSource(path, {'NPC_'})
        donors[plugin] = (src, patch.remap_from(src))
    return donors


def apply_clone(patch, table, decision, header, subs, donors):
    """Replace the record with the vanilla actor, keeping only CLONE_KEEP.

    The shell-only swap was not enough: it left our spiders carrying ONE
    Oblivion faction where a vanilla frostbite spider has three, plus converted
    paralysis lesser-powers and an Oblivion inventory. A creature that belongs
    to no hostile faction has nobody to attack, which is what standing still
    looked like.
    """
    creature = table.SKYRIM_CREATURES[decision.target]
    src, mapping = donors[creature.plugin]
    donor = src.by_type['NPC_'].get(creature.donor)
    if donor is None:
        raise SystemExit(f'donor {creature.donor_edid} '
                         f'(0x{creature.donor:08X}) is not in {creature.plugin}')
    _dhdr, dsubs = remap_record('NPC_', *donor, mapping)

    mine = {}
    for sig, payload in subs:
        if sig in CLONE_KEEP:
            mine.setdefault(sig, []).append(payload)
    out = []
    for sig, payload in dsubs:
        if sig in mine:
            if mine[sig] is not None:           # substitute the run once
                out += [(sig, p) for p in mine[sig]]
                mine[sig] = None
            continue
        out.append((sig, payload))
    for sig, payloads in mine.items():
        if payloads:                            # the donor had no such field
            out = set_field(out, sig, payloads, CLONE_SUCCESSORS.get(sig, ()))
    return header, out


def apply_swap(patch, table, decision, header, subs):
    """Rewrite one NPC_ into its vanilla shell. Only the shell fields move.

    The shell is race + skin + the AI fields the vanilla actors of that race
    use. Race alone is not enough: the converter stamps `csWolf` on nearly
    every creature, which is right for a wolf and wrong for a spider -- and a
    combat style the body cannot perform is the difference between a creature
    that hunts and one that stands there. Stats, level, factions, inventory,
    packages, scripts and dialogue are still the Oblivion record's own.
    """
    creature = table.SKYRIM_CREATURES[decision.target]
    home = creature.plugin
    race = patch.fid(home, creature.formid)

    # A horse's coat is per-ACTOR in Skyrim, so a per-record skin wins. Where
    # the table says 0 the vanilla actors carry no WNAM at all and inherit the
    # race's -- the frostbite spider does exactly that, and writing one anyway
    # is how the elytra ended up wearing a skin no ARMA maps to its race.
    if decision.skin:
        skin = patch.fid('Skyrim.esm', decision.skin)
    else:
        skin = patch.fid(_plugin_of(patch, creature.skin, home),
                         creature.skin) if creature.skin else 0

    subs = set_field(subs, 'RNAM', [_fid_bytes(race)],
                     ('WNAM',) + AFTER_WNAM)
    subs = set_field(subs, 'WNAM', [_fid_bytes(skin)] if skin else [],
                     AFTER_WNAM)
    subs = set_field(subs, 'ATKR', [_fid_bytes(race)], AFTER_ATKR)
    for value, sig, successors in (
            (creature.voice, 'VTCK', AFTER_VTCK),
            (creature.combat_style, 'ZNAM', AFTER_ZNAM),
            (creature.npc_class, 'CNAM', AFTER_CNAM),
            (creature.package_list, 'DPLT', AFTER_DPLT),
            (creature.outfit, 'DOFT', AFTER_DOFT)):
        if not value:
            continue    # the vanilla actors disagree; leave the converted one
        subs = set_field(
            subs, sig,
            [_fid_bytes(patch.fid(_plugin_of(patch, value, home), value))],
            successors)

    if decision.is_mount and decision.target == 'HorseRace':
        # ActorTypeHorse is what makes the activate prompt read "Mount", and it
        # lives on the actor, not the race.
        kw = patch.fid('Skyrim.esm', KW_ACTOR_TYPE_HORSE)
        subs = set_field(subs, 'KSIZ', [struct.pack('<I', 1)], AFTER_KSIZ)
        subs = set_field(subs, 'KWDA', [_fid_bytes(kw)], AFTER_KWDA)
        subs = set_field(subs, 'CNAM',
                         [_fid_bytes(patch.fid('Skyrim.esm', CLASS_HORSE))],
                         AFTER_KWDA[1:])
    return header, subs


def apply_saddle(patch, subs):
    return set_field(subs, 'DOFT',
                     [_fid_bytes(patch.fid('Skyrim.esm', OUTFIT_HORSE_SADDLE))],
                     AFTER_DOFT)


def build(table, plugins, decisions, census, output_dir, scope='all',
          keep_summon=True, clone=True, quiet=False):
    decisions = [d for d in decisions if in_scope(table, d, scope)]
    masters = required_masters(table, plugins, decisions, output_dir,
                               clone=clone)
    patch = PatchPlugin(
        masters, author='TES4-to-TES5 converter',
        description='Vanilla Skyrim creatures for the converted Oblivion actors')
    if not quiet:
        print('  masters: ' + ', '.join(masters))
    donors = load_donors(patch, table, decisions, output_dir) if clone else {}
    if clone and not quiet:
        print('  cloning %d vanilla donor actor(s) from %s'
              % (len({(c.plugin, c.donor)
                      for c in (table.SKYRIM_CREATURES[d.target]
                                for d in decisions if d.action == 'swap')
                      if c.donor}), ', '.join(sorted(donors))))

    swapped = removed = disabled = relisted = 0
    by_plugin = {}
    for d in decisions:
        by_plugin.setdefault(d.plugin, []).append(d)

    summon_keep = set()
    if keep_summon:
        summon_keep.add(table.ALFIQ_SUMMON_EXCEPTION['base'] & 0xFFFFFF)

    for plugin in plugins:
        rows = by_plugin.get(plugin)
        if not rows:
            continue
        path = find_converted(output_dir, plugin)
        src = ChainedSource(path, {'NPC_', 'ACHR', 'LVLN', 'CELL', 'WRLD'})
        mapping = patch.remap_from(src)
        own = src.own_index
        local = {}                       # low 24 bits -> the plugin's own FormID
        for fid in src.by_type['NPC_']:
            if (fid >> 24) == own:
                local[fid & 0xFFFFFF] = fid

        removing = set()
        for d in rows:
            fid = local.get(d.fid)
            if fid is None:
                continue
            if d.action == 'swap':
                header, subs = remap_record('NPC_', *src.by_type['NPC_'][fid],
                                            mapping)
                creature = table.SKYRIM_CREATURES[d.target]
                if clone and creature.donor:
                    header, subs = apply_clone(patch, table, d, header, subs,
                                               donors)
                    # A cloned mount still needs its own coat and saddle.
                    if d.is_mount or d.skin:
                        header, subs = apply_swap(patch, table, d, header, subs)
                else:
                    header, subs = apply_swap(patch, table, d, header, subs)
                if d.saddled:
                    subs = apply_saddle(patch, subs)
                patch.add('NPC_', struct.unpack_from('<I', header, 12)[0],
                          header, subs)
                swapped += 1
            elif d.action == 'remove':
                if d.fid in summon_keep:
                    continue
                removing.add(fid)
                removed += 1

        if not removing:
            continue

        # --- layer 1: switch off every placed reference -------------------
        for fid, (hdr, subs) in src.by_type['ACHR'].items():
            name = first(subs, 'NAME')
            if not name or struct.unpack('<I', name)[0] not in removing:
                continue
            chain = src.chains[('ACHR', fid)]
            new_hdr, new_subs = remap_record('ACHR', hdr, subs, mapping)
            flags = struct.unpack_from('<I', new_hdr, 8)[0]
            hdr2 = bytearray(new_hdr)
            struct.pack_into('<I', hdr2, 8, flags | FLAG_INITIALLY_DISABLED)
            patch.add_nested(remap_chain(chain, mapping), 'ACHR',
                             struct.unpack_from('<I', hdr2, 12)[0],
                             bytes(hdr2), new_subs)
            disabled += 1
            # The chain only resolves if the cell (and its worldspace) exist as
            # overrides too, which is what xEdit writes for a copied child ref.
            for gtype, label in chain:
                target = struct.unpack('<I', label)[0]
                if gtype == 6 and target in src.by_type['CELL']:
                    patch.add_parent('CELL', *_parent('CELL', src, target,
                                                      mapping))
                elif gtype == 1 and target in src.by_type['WRLD']:
                    patch.add_parent('WRLD', *_parent('WRLD', src, target,
                                                      mapping))

        # --- layer 2: take them out of the leveled lists ------------------
        for fid, (hdr, subs) in src.by_type['LVLN'].items():
            kept = []
            dropped = 0
            for sig, payload in subs:
                if sig == 'LVLO' and struct.unpack_from('<I', payload, 4)[0] in removing:
                    dropped += 1
                    continue
                kept.append((sig, payload))
            if not dropped:
                continue
            kept = [(s, struct.pack('<I', sum(1 for k, _ in kept if k == 'LVLO'))
                     if s == 'LLCT' else p) for s, p in kept]
            new_hdr, new_subs = remap_record('LVLN', hdr, kept, mapping)
            patch.add('LVLN', struct.unpack_from('<I', new_hdr, 12)[0],
                      new_hdr, new_subs)
            relisted += 1

    return patch, {'swapped': swapped, 'removed': removed,
                   'disabled_refs': disabled, 'leveled_lists': relisted}


def _parent(sig, src, fid, mapping):
    """(patch_fid, header, subs) for a CELL/WRLD copied as a plain override."""
    hdr, subs = src.by_type[sig][fid]
    new_hdr, new_subs = remap_record(sig, hdr, subs, mapping)
    return (struct.unpack_from('<I', new_hdr, 12)[0], new_hdr, new_subs)


def write_report(path, decisions):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh, delimiter='\t')
        w.writerow(['plugin', 'formid', 'editorid', 'name', 'group', 'action',
                    'tier', 'target', 'coat', 'saddled', 'mount', 'note'])
        for d in sorted(decisions, key=lambda x: (x.plugin, x.group, x.edid)):
            w.writerow([d.plugin, '%06X' % d.fid, d.edid, d.full, d.group,
                        d.action, d.tier, d.target, d.coat,
                        'yes' if d.saddled else '',
                        'yes' if d.is_mount else '', d.note])


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugins', nargs='+', required=True,
                    help='converted plugins to patch, in load order')
    ap.add_argument('--output-dir', default=os.path.join(REPO, 'output'),
                    help='where the converted plugins live (default output/)')
    ap.add_argument('--scope', choices=('creatures', 'mounts', 'all'),
                    default='all',
                    help='which half to build: "mounts" is every creature whose '
                         'stand-in is a horse, "creatures" is everything else '
                         'plus the removals (default: all, one combined ESP)')
    ap.add_argument('--out', help='ESP to write (default: named for the scope)')
    ap.add_argument('--exact-only', action='store_true',
                    help='apply only exact-tier swaps, skipping every near one')
    ap.add_argument('--no-clone', action='store_true',
                    help='swap only the AI shell instead of cloning the vanilla '
                         'actor wholesale -- keeps the Oblivion level, stats, '
                         'factions, spells and inventory')
    ap.add_argument('--no-remove', action='store_true',
                    help='keep the remove-tier creatures (the alfiq) in place')
    ap.add_argument('--remove-summon', action='store_true',
                    help='also remove the one alfiq a script summons, leaving '
                         'the spell summoning nothing')
    ap.add_argument('--report', help='write a TSV of every decision here')
    ap.add_argument('--dry-run', action='store_true',
                    help='report only; write no ESP')
    args = ap.parse_args()

    table = load_table()
    out_path = args.out or os.path.join(OUT_DIR, SCOPE_PLUGIN[args.scope])
    print('%s patch (%s): %s'
          % (args.scope, os.path.basename(out_path), ', '.join(args.plugins)))
    decisions, census = plan(table, args.plugins, args.output_dir,
                             allow_near=not args.exact_only,
                             do_remove=not args.no_remove)
    scoped = [d for d in decisions if in_scope(table, d, args.scope)]
    counts = {}
    for d in scoped:
        counts[d.action] = counts.get(d.action, 0) + 1
    print('  %d of %d creatures in scope: %s' % (
        len(scoped), len(decisions),
        ', '.join(f'{k} {v}' for k, v in sorted(counts.items())) or 'none'))

    if args.report:
        write_report(args.report, decisions)
        print(f'  report: {args.report}')

    if args.dry_run:
        print('  DRY RUN -- nothing written')
        return 0

    patch, stats = build(table, args.plugins, decisions, census,
                         args.output_dir, scope=args.scope,
                         keep_summon=not args.remove_summon,
                         clone=not args.no_clone)
    size, records, groups = patch.write(out_path)
    print('  %d NPC_ swapped, %d creatures removed '
          '(%d placed refs disabled, %d leveled lists rewritten)'
          % (stats['swapped'], stats['removed'], stats['disabled_refs'],
             stats['leveled_lists']))
    print(f'  wrote {out_path}  ({size:,} bytes, {records} records, '
          f'{groups} groups)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
