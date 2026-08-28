#!/usr/bin/env python3
"""Teach iNeed about the converted world: food, drink, and who sells water.

Writes `MyOwnTamrieliNeedPatch.esp` -- an override plugin with two halves, both
of which turn out to need no scripting at all.

    python tools/patch/assign_ineed.py --plugins Oblivion.esm
    python tools/patch/assign_ineed.py --plugins Oblivion.esm --report r.tsv --dry-run

HALF 1 -- THE FOOD LISTS
------------------------
iNeed decides what an item does to hunger by looking it up in a FormList, and it
has NO classifier: no keywords, no value or weight heuristic. It ships those
lists EMPTY and fills them at runtime from its own `_SNFood_Initial_*` seeds plus
a 76 KB hand-written per-mod table. Anything in neither is invisible, which is
every item we convert.

The fix is to OVERRIDE the eight lists with our items as BASE entries. That is
better than the script route every other food mod uses, for a measured reason:
`_SNDLCQuestScript` calls `FormList.Revert()` on all eight lists whenever it
re-seeds, and Revert drops runtime-added forms while keeping the ones the
plugins define. Script-added entries can be reverted away; ours cannot.

The mapping is `patch_folder/sources/food_changes.py`, keyed on the item's FULL
NAME because Oblivion carries 173 ingredients under 163 names and same-named
records always want the same category.

HALF 2 -- WHO REFILLS YOUR WATERSKIN
------------------------------------
iNeed's innkeeper and merchant water services are plain dialogue, and their
conditions are pure vanilla faction membership -- read out of the INFO records:

    _SNInnRefillTopic       GetInFaction JobInnkeeperFaction == 1
                         OR GetInFaction JobInnServer == 1
                            + player gold > 5, + a refillable skin
                            -> refills every skin for 5 gold each
    _SNTravelerRefillTopic  GetInFaction JobMerchantFaction
                            + an EMPTY waterskin, + 50 gold
                            -> the merchant gives water from their own supply

Converted Oblivion innkeepers are in none of those factions, so the options
never appear. Adding the factions is the entire fix -- no dialogue is authored
here, iNeed's own topics attach themselves.

Who is an innkeeper is AUTHORED: Oblivion gives them the class `MerchPublican`
("Publican"). Measured on Oblivion.esm: 37 of them, and all 37 are also vendors.
Who is a merchant is authored too -- `AIDT.Services` buy/sell bits, 145 NPCs.
Vanilla innkeepers (Hulda, Orgnar, Valga Vinicia, Corpulus Vinius) carry BOTH
JobInnkeeperFaction and JobMerchantFaction, so publicans get both here too.

STACKING ON THE PATCHES ALREADY BUILT
-------------------------------------
Two plugins that override the same record do not merge: the later one wins the
WHOLE record. The cosmetic patch overrides 220 of these same merchants, so
copying them off the converted master meant one of the two patches was always
thrown away -- with the load order as shipped, every faction and every item of
stock this tool writes. `--overlay` names the patches already built over the
same plugins; their version of a shared record is what gets copied, and each
one that contributes becomes a master, which is what stops the load order
putting them after this patch.

    python tools/patch/assign_ineed.py --plugins Oblivion.esm \
        --overlay patch_folder/output/MyOwnTamrielCosmeticPatch.esp
"""

import argparse
import csv
import importlib.util
import os
import struct
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from tools.patch.patch_builder import (              # noqa: E402
    TES4_FORM_VERSION, ChainedSource, PatchPlugin, SourceStack, locate_plugin,
    order_masters, overlay_contributors, remap_record,
)
from tools.patch.plugin_patch import (                # noqa: E402
    first, iter_records, read_masters, read_subrecords, zstring,
)
from tools.patch.assign_creatures import find_converted   # noqa: E402

TABLE = os.path.join(REPO, 'patch_folder', 'sources', 'food_changes.py')
OUT_DIR = os.path.join(REPO, 'patch_folder', 'output')
PLUGIN_NAME = 'MyOwnTamrieliNeedPatch.esp'

INEED = 'iNeed.esp'

# Vanilla Skyrim.esm factions iNeed's dialogue conditions on. Verified against
# Skyrim.esm: JobInnkeeperFaction 0005091B, JobInnServer 000DEE93,
# JobMerchantFaction 00051596.
JOB_INNKEEPER = 0x0005091B
JOB_MERCHANT = 0x00051596

# TES4 AIDT.Services buy/sell bits. Bit 14 is training and bit 15+ are other
# services, so masking to the low 14 keeps this to actual trade.
VENDOR_BITS = 0x3FFF

PUBLICAN_CLASS = 'MerchPublican'

# --- half 3: the vendor base stock ----------------------------------------
# Vanilla keyword FormIDs, read out of Skyrim.esm.
KW_VENDOR_FOOD = 0x0008CDEA
KW_VENDOR_INGREDIENT = 0x0008CDEB
# iNeed's FULL waterskin (ALCH, "3/3"). It already carries VendorItemFood,
# which is why the whole base set rides on one keyword.
INEED_WATERSKIN_FULL = 0x05004376
WATERSKINS_PER_VENDOR = 2

FACT_VENDOR_FLAG = 0x4000
VENDOR_LIST_PREFIX = 'TES4VendorList_'
# TES4 AIDT.Services bit 4 -- "Ingredients". tes5_import maps it to
# VendorItemIngredient + VendorItemFoodRaw + VendorItemFood, so a merchant
# carrying it ALREADY admits everything in the base stock: this is the
# authored answer to "does this shop sell food", and it means the stock needs
# no keyword widening at all. All 37 of Oblivion's publicans carry it; so do
# 47 of its other 108 merchants and 50 of Anequina's 75.
TES4_SERVICE_FOOD = 1 << 4
# Vanilla's innkeeper chest is SaltPile + LItemFoodInnCommon +
# LItemInnRuralDrink + VendorGoldInn: one FOOD list, one DRINK list, flat
# items alongside. Ours mirrors that shape with the plugin's own items.
STOCK_FOOD_CATS = ('heavy', 'med', 'light')
STOCK_DRINK_CATS = ('drink', 'drink_noalc')


def _fresh_header(sig, fid):
    """A 24-byte record header for a record this patch mints itself."""
    return sig.encode('ascii') + struct.pack('<IIIIHH', 0, 0, fid, 0,
                                             TES4_FORM_VERSION, 0)


def lvli_subrecords(edid, entries):
    """A leveled item list shaped like vanilla LItemFoodInnCommon.

    chanceNone 0 and flags 3 (Calculate from all levels + Calculate for each
    item in count) are what every vanilla inn list uses, so the container
    resolves one of the entries every time it restocks.
    """
    subs = [('EDID', edid.encode('ascii') + bytes(1)),
            ('OBND', bytes(12)),
            ('LVLD', bytes(1)),
            ('LVLF', bytes([3])),
            ('LLCT', bytes([min(len(entries), 255)]))]
    for item in entries:
        subs.append(('LVLO', struct.pack('<HHIHH', 1, 0, item, 1, 0)))
    return subs


def _owners(path):
    """Plugin names a file's FormID index byte can name, index-aligned."""
    with open(path, 'rb') as fh:
        head = fh.read(8192)
    return ([m.lower() for m in read_masters(head)]
            + [os.path.basename(path).lower()])


def sellable_items(plugins, output_dir):
    """(plugin, low FormID) for every edible a widened vendor list admits.

    The VEND list is a filter, not a source: an item whose base object carries
    none of its keywords never reaches the barter menu however it got into the
    stock. Since the widening adds exactly VendorItemFood and
    VendorItemIngredient, those two are the whole test.
    """
    want = {KW_VENDOR_FOOD, KW_VENDOR_INGREDIENT}
    out = set()
    for plugin in plugins:
        path = find_converted(str(output_dir), plugin)
        if path is None:
            continue
        with open(path, 'rb') as fh:
            buf = fh.read()
        own = len(read_masters(buf))
        for sig, fid, hdr, data, c, w in iter_records(buf, {'ALCH', 'INGR'}):
            if (fid >> 24) != own:
                continue
            for k, pl in read_subrecords(data):
                if k != 'KWDA':
                    continue
                kws = {struct.unpack_from('<I', pl, i)[0]
                       for i in range(0, len(pl), 4)}
                # keywords are Skyrim.esm's, index 00 in every converted plugin
                if {x & 0xFFFFFF for x in kws if (x >> 24) == 0} & want:
                    out.add((plugin, fid & 0xFFFFFF))
    return out


def scan_vendor_factions(paths):
    """Every vendor faction across the selected plugins, keyed by OWNER.

    Keyed by (owning plugin, low 24 bits) rather than by FormID, because a
    dependent plugin sees its master's factions under a different index --
    ElsweyrAnequina's merchants sit in factions Oblivion.esm defines, and a
    per-file table simply cannot see them. Missing that left 58 of Anequina's
    75 merchants out of the stock pass entirely.
    """
    table, chests = {}, {}
    for path in paths:
        owners = _owners(path)
        with open(path, 'rb') as fh:
            buf = fh.read()
        want_refr = {}
        for sig, fid, hdr, data, c, w in iter_records(buf, {'FACT'}):
            subs = read_subrecords(data)
            d = first(subs, 'DATA')
            if not (d and len(d) == 4
                    and struct.unpack('<I', d)[0] & FACT_VENDOR_FLAG):
                continue
            idx = fid >> 24
            if idx >= len(owners):
                continue
            venc = first(subs, 'VENC')
            vend = first(subs, 'VEND')
            venc = struct.unpack('<I', venc)[0] if venc else 0
            vend = struct.unpack('<I', vend)[0] if vend else 0
            table[(owners[idx], fid & 0xFFFFFF)] = (venc, vend, owners)
            if venc:
                want_refr.setdefault(venc, (owners[idx], fid & 0xFFFFFF))
        if not want_refr:
            continue
        for sig, fid, hdr, data, c, w in iter_records(buf, {'REFR'}):
            key = want_refr.get(fid)
            if key is None:
                continue
            nm = first(read_subrecords(data), 'NAME')
            if nm and len(nm) == 4:
                base = struct.unpack('<I', nm)[0]
                i = base >> 24
                if i < len(owners):
                    chests[key] = (owners[i], base & 0xFFFFFF)
    return table, chests


def scan_vendors(path, table, chests):
    """This plugin's vendor actors, split by where their stock has to go.

    Returns {NPC FormID: (chest key or None, redundant faction FormIDs)}. A
    merchant sells its vendor faction's VENC container; the ones whose faction
    has none sell what they carry, so the base stock goes into the actor
    instead. Both are vanilla-legal -- `CurrentFollowerFaction` and
    `WEServicesHunterFaction` are chest-less vendor factions too.
    """
    owners = _owners(path)
    with open(path, 'rb') as fh:
        buf = fh.read()
    plan = {}
    for sig, fid, hdr, data, c, w in iter_records(buf, {'NPC_'}):
        subs = read_subrecords(data)
        mine = []
        for sg, pl in subs:
            if sg != 'SNAM':
                continue
            x = struct.unpack_from('<I', pl, 0)[0]
            i = x >> 24
            key = (owners[i], x & 0xFFFFFF) if i < len(owners) else None
            if key in table:
                mine.append((key, x))
        if not mine:
            continue
        # The engine resolves ONE vendor faction and takes the FIRST. A
        # merchant carrying both its dedicated chest faction and the shared
        # chest-less one therefore trades out of its pockets -- which is the
        # bug the converter fix addresses, and which this patch repeats here
        # so it works against a master that has NOT been re-imported.
        backed = [(k, x) for k, x in mine if chests.get(k)]
        drop = []
        if backed:
            keep = backed[0]
            drop = [x for k, x in mine if (k, x) != keep]
            chest = chests[keep[0]]
        else:
            chest = None
        plan[fid] = (chest, drop)
    return plan


def append_cnto(subs, entries, before):
    """Append CNTO entries after the existing run, keeping COCT in step."""
    out, at = [], None
    for i, (sg, pl) in enumerate(subs):
        out.append((sg, pl))
    last = max((i for i, (sg, _p) in enumerate(out) if sg == 'CNTO'),
               default=None)
    if last is None:
        at = next((i for i, (sg, _p) in enumerate(out) if sg in before),
                  len(out))
    else:
        at = last + 1
    new = [('CNTO', struct.pack('<Ii', fid, n)) for fid, n in entries]
    out = out[:at] + new + out[at:]
    total = sum(1 for sg, _p in out if sg == 'CNTO')
    out = [(sg, struct.pack('<I', total) if sg == 'COCT' else pl)
           for sg, pl in out]
    return out


def load_table():
    spec = importlib.util.spec_from_file_location('food_changes', TABLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def export_records(plugin, sig):
    """Every record of one type from the plugin's export dump."""
    path = os.path.join(REPO, 'export', plugin, '%s.txt' % sig)
    if not os.path.isfile(path):
        return []
    out = []
    rec = None
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if line == '---RECORD_BEGIN---':
                if rec is not None:
                    out.append(rec)
                rec = defaultdict(list)
                continue
            if rec is None or '=' not in line:
                continue
            key, _, val = line.partition('=')
            rec[key].append(val)
    if rec is not None:
        out.append(rec)
    return out


def one(rec, key, default=''):
    vals = rec.get(key)
    return vals[0] if vals else default


def plan_food(table, plugins):
    """[(plugin, low_fid, name, signature, category)] for every edible."""
    rows = []
    covered = set(getattr(table, 'COVERED_PLUGINS', ()))
    for plugin in plugins:
        if plugin not in covered:
            print('  %s: not covered by food_changes.py -- its food and drink '
                  'are left alone' % plugin)
            continue
        for sig in ('INGR', 'ALCH'):
            for rec in export_records(plugin, sig):
                name = one(rec, 'FULL')
                if not name:
                    continue
                cat = table.category_of(name, sig)
                if cat is None:
                    continue        # an ALCH that is a potion, not a drink
                rows.append((plugin, int(one(rec, 'FormID'), 16) & 0xFFFFFF,
                             name, sig, cat))
    return rows


def plan_actors(plugins):
    """[(plugin, low_fid, edid, is_publican, services)] for every vendor NPC.

    The class table is built across ALL the selected plugins, not per plugin:
    an ElsweyrAnequina innkeeper's `CNAM.Class` names Oblivion.esm's
    `MerchPublican`, which a per-plugin table cannot resolve. That blindness
    hid **16 of Anequina's innkeepers**, leaving them out of
    JobInnkeeperFaction and so out of iNeed's waterskin-refill dialogue.
    """
    classes = {}
    for plugin in plugins:
        for rec in export_records(plugin, 'CLAS'):
            classes.setdefault(one(rec, 'FormID'), one(rec, 'EditorID'))
    rows = []
    for plugin in plugins:
        for rec in export_records(plugin, 'NPC_'):
            services = int(one(rec, 'AIDT.Services', '0') or 0)
            publican = classes.get(one(rec, 'CNAM.Class')) == PUBLICAN_CLASS
            if not (services & VENDOR_BITS) and not publican:
                continue
            rows.append((plugin, int(one(rec, 'FormID'), 16) & 0xFFFFFF,
                         one(rec, 'EditorID'), publican, services))
    return rows


def locator(output_dir, overlays):
    """`locate_plugin`, plus the already-built patches this one stacks on.

    They live in `patch_folder/output/`, which nothing else has a reason to
    search -- and the master list cannot be ordered without reading their own
    masters first.
    """
    extra = {os.path.basename(p).lower(): p for p in overlays}

    def locate(name):
        return extra.get(name.lower()) or locate_plugin(name, output_dir)
    return locate


def required_masters(plugins, output_dir, overlays=()):
    names = ['Skyrim.esm', INEED]
    for plugin in plugins:
        path = find_converted(str(output_dir), plugin)
        if path is None:
            raise SystemExit('%s is not built in %s -- convert it first'
                             % (plugin, output_dir))
        with open(path, 'rb') as fh:
            names += read_masters(fh.read(8192))
        names.append(plugin)
    # An overlay is MASTERED so the game cannot load it after this patch: the
    # records carried out of it would otherwise be overwritten by the very
    # plugin they were copied from.
    names += [os.path.basename(p) for p in overlays]
    return order_masters(names, locator(output_dir, overlays))


class Stack:
    """The winning version of every record, remapped into the patch's space.

    A record this patch overrides may already have been overridden by an
    EARLIER patch of ours -- the cosmetic one restyles 220 of the same
    merchants. Overrides do not merge: the later plugin wins the WHOLE record,
    so the copy has to start from the last override, not from the converted
    master. Reading the master instead is what silently reverted every
    outfit, hair and skin-tone change on those 220 actors (or, with the load
    order the other way round, every faction and every item of stock).
    """

    def __init__(self, patch, plugins, overlays, output_dir, types):
        self.patch = patch
        self.stacks = {}
        self._maps = {}
        for plugin in plugins:
            path = find_converted(str(output_dir), plugin)
            if path is not None:
                self.stacks[plugin] = SourceStack(path, overlays, types)

    def base(self, plugin):
        return self.stacks[plugin].base

    def mapping(self, layer):
        key = layer.name.lower()
        if key not in self._maps:
            self._maps[key] = self.patch.remap_from(layer)
        return self._maps[key]

    def record(self, plugin, sig, owner, low):
        """(header, subs) for the winning record, in the patch's ID space."""
        stack = self.stacks.get(plugin)
        if stack is None:
            return None
        hit = stack.latest(sig, owner, low)
        if hit is None:
            return None
        layer, fid = hit
        return remap_record(sig, *layer.by_type[sig][fid], self.mapping(layer))


def build(table, plugins, food, actors, overlays, output_dir, quiet=False):
    masters = required_masters(plugins, output_dir, overlays)
    patch = PatchPlugin(masters,
                        description='Oblivion food, drink and water sellers '
                                    'for iNeed')
    if not quiet:
        print('  masters: ' + ', '.join(masters))
    # ONE read of each converted plugin, shared by both halves that copy
    # records out of it -- and the only place the overlays are consulted.
    stack = Stack(patch, plugins, overlays, output_dir, {'NPC_', 'CONT'})

    ineed_path = locate_plugin(INEED, output_dir)
    if ineed_path is None:
        raise SystemExit('cannot find %s -- it must be installed, or sitting '
                         'in patch_folder/sources/iNeed/' % INEED)
    ineed = ChainedSource(ineed_path, {'FLST'})
    ineed_map = patch.remap_from(ineed)

    # --- half 1: the food lists ------------------------------------------
    # Every classified edible goes in, sellable or not: these lists are what
    # iNeed reads to decide what EATING an item does, which has nothing to do
    # with whether a merchant is allowed to stock it.
    by_cat = defaultdict(list)
    for plugin, low, _name, _sig, cat in food:
        by_cat[cat].append(patch.fid(plugin, low))

    lists_written = 0
    for cat, entries in sorted(by_cat.items()):
        target = table.INEED_LISTS.get(cat)
        if target is None:
            continue
        local = target[0] & 0xFFFFFF
        source = None
        for fid, rec in ineed.by_type['FLST'].items():
            if (fid & 0xFFFFFF) == local:
                source = (fid, rec)
                break
        if source is None:
            raise SystemExit('%s (0x%08X) is not in %s'
                             % (target[1], target[0], INEED))
        header, subs = remap_record('FLST', *source[1], ineed_map)
        # iNeed ships these lists EMPTY and fills them at runtime, so anything
        # already here would be a surprise; keep it either way and append.
        kept = [(s, p) for s, p in subs if s != 'LNAM']
        existing = [p for s, p in subs if s == 'LNAM']
        payloads = existing + [struct.pack('<I', f) for f in entries]
        out = []
        for s, p in kept:
            out.append((s, p))
        out += [('LNAM', p) for p in payloads]
        patch.add('FLST', struct.unpack_from('<I', header, 12)[0], header, out)
        lists_written += 1
        if not quiet:
            print('    %-22s %-26s +%d' % (cat, target[1], len(entries)))

    # --- half 2: the water sellers ---------------------------------------
    innkeepers = merchants = 0
    for plugin in plugins:
        rows = [r for r in actors if r[0] == plugin]
        if not rows:
            continue
        for _plugin, low, _edid, publican, _services in rows:
            got = stack.record(plugin, 'NPC_', plugin, low)
            if got is None:
                continue
            header, subs = got
            want = [JOB_MERCHANT]
            if publican:
                want.insert(0, JOB_INNKEEPER)
            have = {struct.unpack_from('<I', p, 0)[0]
                    for s, p in subs if s == 'SNAM'}
            add = [patch.fid('Skyrim.esm', f) for f in want
                   if patch.fid('Skyrim.esm', f) not in have]
            if not add:
                continue
            # SNAM is faction + rank; append rather than replace, or the actor
            # loses every faction the conversion gave it.
            out = []
            placed = False
            for s, p in subs:
                out.append((s, p))
                if s == 'SNAM':
                    placed = True
            run_end = max(i for i, (s, _p) in enumerate(out)
                          if s == 'SNAM') + 1 if placed else None
            new = [('SNAM', struct.pack('<Ii', f, 0)) for f in add]
            if run_end is None:
                # No factions at all: SNAM sits right after ACBS.
                at = next((i for i, (s, _p) in enumerate(out)
                           if s not in ('EDID', 'VMAD', 'OBND', 'ACBS')),
                          len(out))
                out = out[:at] + new + out[at:]
            else:
                out = out[:run_end] + new + out[run_end:]
            patch.add('NPC_', struct.unpack_from('<I', header, 12)[0],
                      header, out)
            if publican:
                innkeepers += 1
            else:
                merchants += 1

    # --- half 3: the vendor base stock -----------------------------------
    stock = add_vendor_stock(patch, stack, plugins, food, actors, output_dir,
                             quiet)

    return patch, {'lists': lists_written, 'items': len(food),
                   'innkeepers': innkeepers, 'merchants': merchants,
                   **stock}


def add_vendor_stock(patch, stack, plugins, food, actors, output_dir,
                     quiet=False):
    """Give the shops that sell food a base stock, the way a Skyrim inn does.

    Vanilla's innkeeper chest is exactly four entries -- SaltPile,
    `LItemFoodInnCommon`, `LItemInnRuralDrink`, `VendorGoldInn` -- so this
    mirrors that shape with the plugin's OWN items: one food list and one
    drink list built from `food_changes.py`, plus iNeed's full waterskin.

    WHO GETS WHAT is authored, not chosen here:

    | shop            | signal                       | stock                  |
    |-----------------|------------------------------|------------------------|
    | inn             | class `MerchPublican`        | food + drink + 2 skins |
    | food/general    | `AIDT.Services` bit 4        | food + drink           |
    | everyone else   | --                           | nothing                |

    A blacksmith has no business selling bread, and the engine agrees: its
    vendor faction's VEND keyword list would filter the food out anyway. That
    list is a FILTER, not a source. Both groups above carry service bit 4,
    which `tes5_import` maps to VendorItemIngredient + FoodRaw + Food, so
    every item of the base stock is admitted with NO keyword widening -- an
    earlier revision widened all 21 vendor lists instead, which handed every
    smith and bookseller the whole larder.

    The stock itself goes where the engine looks: the vendor faction's VENC
    container when it has one, the actor's inventory when it does not. Both
    are vanilla-legal -- `CurrentFollowerFaction` and
    `WEServicesHunterFaction` are chest-less vendor factions too.
    """
    admits = sellable_items(plugins, output_dir)
    by_cat = defaultdict(list)
    dropped = 0
    for plugin, low, _name, _sig, cat in food:
        # An item the vendor filter cannot admit is dead weight in the stock:
        # the barter menu would never show it. 3 of Oblivion's 21 drinks are
        # ALCH without the food flag, so they carry VendorItemPotion instead
        # of VendorItemFood -- and adding VendorItemPotion to every vendor
        # list to rescue them would hand every merchant the potion catalogue.
        if (plugin, low) in admits:
            by_cat[cat].append(patch.fid(plugin, low))
        elif cat in STOCK_FOOD_CATS or cat in STOCK_DRINK_CATS:
            dropped += 1
    if dropped and not quiet:
        print('    %d edibles left out of the base stock: no VendorItemFood '
              'or VendorItemIngredient keyword' % dropped)

    # who is entitled to a base stock, and to how much of it
    tavern, larder = set(), set()
    for plugin, low, _edid, publican, services in actors:
        if publican:
            tavern.add((plugin, low))
        elif services & TES4_SERVICE_FOOD:
            larder.add((plugin, low))

    n_chest = n_actor = 0
    next_id = patch.next_object_id

    # ONE food list and ONE drink list for the whole patch, not one per
    # plugin: a plugin `food_changes.py` does not cover yet (Anequina) would
    # otherwise stock water and nothing else, and its merchants sit next door
    # to Cyrodiil -- Cyrodiil's larder is the right answer for them until the
    # table grows to cover their own.
    entries = []
    for label, wanted in (('Food', STOCK_FOOD_CATS),
                          ('Drink', STOCK_DRINK_CATS)):
        items = sorted({f for c in wanted for f in by_cat.get(c, ())})
        if not items:
            continue
        fid = (patch.own_index << 24) | next_id
        next_id += 1
        edid = 'TES4iNeedVendor%s' % label
        patch.add('LVLI', fid, _fresh_header('LVLI', fid),
                  lvli_subrecords(edid, items))
        entries.append((fid, 1))
        if not quiet:
            print('    %-26s %d items' % (edid, len(items)))
    waterskin = patch.fid(INEED, INEED_WATERSKIN_FULL)
    entries.append((waterskin, WATERSKINS_PER_VENDOR))

    paths = [find_converted(str(output_dir), pl) for pl in plugins]
    paths = [x for x in paths if x]
    table, chest_map = scan_vendor_factions(paths)
    done_chests = set()
    n_fixed = 0
    n_plvd = repair_vendor_locations(patch, plugins, output_dir, quiet)

    for plugin in plugins:
        path = find_converted(str(output_dir), plugin)
        if path is None:
            continue
        plan = scan_vendors(path, table, chest_map)
        mapping = stack.mapping(stack.base(plugin))
        own = os.path.basename(path).lower()
        chest_needs_stock = {}

        for nfid, (chest, drop) in sorted(plan.items()):
            low = nfid & 0xFFFFFF
            entitled = ((plugin, low) in tavern or (plugin, low) in larder)
            skins = (plugin, low) in tavern
            if not drop and not entitled:
                continue
            pfid = _remapped(nfid, mapping)
            got = patch.get('NPC_', pfid)
            if got is None:
                got = stack.record(plugin, 'NPC_', plugin, low)
                if got is None:
                    continue
            header, subs = got
            if drop:
                # Keep the chest-backed faction, drop the chest-less ones.
                gone = {_remapped(x, mapping) for x in drop}
                subs = [(sg, pl) for sg, pl in subs
                        if not (sg == 'SNAM'
                                and struct.unpack_from('<I', pl, 0)[0] in gone)]
                n_fixed += 1
            if entitled and chest is None:
                mine = list(entries)
                if not skins:
                    mine = [e for e in mine if e[0] != waterskin]
                # Canonical NPC_ order is ... PRKR, COCT, CNTO, AIDT, PKID ...
                # so an actor carrying nothing gets its first CNTO right
                # before AIDT, never ahead of the spell/perk run.
                subs = append_cnto(subs, mine, before={'AIDT'})
                n_actor += 1
            patch.add('NPC_', pfid, header, subs)
            if entitled and chest is not None:
                got = chest_needs_stock.get(chest)
                chest_needs_stock[chest] = bool(got) or skins

        for chest, skins in sorted(chest_needs_stock.items()):
            owner, low = chest
            if owner != own or chest in done_chests:
                continue        # a master's record; handled with that master
            done_chests.add(chest)
            got = stack.record(plugin, 'CONT', owner, low)
            if got is None:
                continue
            header, subs = got
            mine = list(entries)
            if not skins:
                mine = [e for e in mine if e[0] != waterskin]
            subs = append_cnto(subs, mine, before={'DATA'})
            patch.add('CONT', struct.unpack_from('<I', header, 12)[0],
                      header, subs)
            n_chest += 1

    patch.next_object_id = next_id
    if not quiet:
        print('    base stock -> %d vendor chests, %d carried inventories'
              % (n_chest, n_actor))
        print('    %d merchants had a redundant chest-less vendor faction '
              'removed' % n_fixed)
    return {'chests': n_chest, 'carried': n_actor, 'faction_fixed': n_fixed,
            'vendor_locations': n_plvd}


def repair_vendor_locations(patch, plugins, output_dir, quiet=False):
    """Give every vendor faction a Vendor Location, if its plugin lacks one.

    A vendor faction with no PLVD sells NOTHING: the barter menu opens and is
    empty, because the engine has no place to measure the vendor against. All
    145 of Skyrim.esm's vendor factions carry one. `tes5_import` now writes it
    too, but this repeats the repair UNCONDITIONALLY so the patch keeps
    working against any vintage of the converted master -- a merchant starts
    trading from the small ESP alone, with no 615 MB file to re-deploy. On a
    master that already has the field the override is simply identical.

    Type 12 / value 0 is "near self, no fixed place", what the roaming Khajiit
    caravans use; the radius is cleared with it, because a radius measured
    from nowhere is the bug being fixed.
    """
    PLVD = struct.pack('<iIi', 12, 0, 0)
    fixed = 0
    for plugin in plugins:
        path = find_converted(str(output_dir), plugin)
        if path is None:
            continue
        src = ChainedSource(path, {'FACT'})
        mapping = patch.remap_from(src)
        for fid, rec in src.by_type['FACT'].items():
            if (fid >> 24) != src.own_index:
                continue
            # Decide BEFORE remapping: the non-vendor factions carry XNAM
            # relations this pass has no business rewriting, and remapping a
            # record only to throw it away is wasted work either way.
            raw = rec[1]
            d = first(raw, 'DATA')
            if not (d and len(d) == 4
                    and struct.unpack('<I', d)[0] & FACT_VENDOR_FLAG):
                continue
            header, subs = remap_record('FACT', *rec, mapping)
            out = []
            for sg, pl in subs:
                if sg == 'PLVD':
                    continue                 # rewritten below, in order
                if sg == 'VENV' and len(pl) >= 12:
                    pl = bytearray(pl)
                    struct.pack_into('<HHH', pl, 0, 0, 24, 0)
                    pl = bytes(pl)
                out.append((sg, pl))
            out.append(('PLVD', PLVD))       # vanilla order: ... VENV, PLVD
            patch.add('FACT', struct.unpack_from('<I', header, 12)[0],
                      header, out)
            fixed += 1
    if fixed and not quiet:
        print('    %d vendor factions given a Vendor Location (without one a '
              'merchant cannot trade at all)' % fixed)
    return fixed


def _remapped(fid, mapping):
    idx = fid >> 24
    return ((mapping.get(idx, idx)) << 24) | (fid & 0xFFFFFF)


def write_report(path, food, actors):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh, delimiter='\t')
        w.writerow(['kind', 'plugin', 'formid', 'name', 'record', 'category'])
        for plugin, low, name, sig, cat in sorted(food,
                                                  key=lambda r: (r[4], r[2])):
            w.writerow(['item', plugin, '%06X' % low, name, sig, cat])
        for plugin, low, edid, publican, services in sorted(
                actors, key=lambda r: r[2]):
            w.writerow(['actor', plugin, '%06X' % low, edid, 'NPC_',
                        'innkeeper+merchant' if publican
                        else ('food merchant' if services & TES4_SERVICE_FOOD
                              else 'merchant')])


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugins', nargs='+', required=True)
    ap.add_argument('--output-dir', default=os.path.join(REPO, 'output'))
    ap.add_argument('--out', help='ESP to write')
    ap.add_argument('--report', help='TSV of every decision')
    ap.add_argument('--overlay', action='append', default=[],
                    metavar='ESP',
                    help='a patch of ours already built over the same plugins, '
                         'in load order. Its version of a shared record is what '
                         'gets copied, and it becomes a master -- without that '
                         'the two patches simply overwrite each other')
    ap.add_argument('--no-factions', action='store_true',
                    help='food lists only; leave innkeepers and merchants alone')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    table = load_table()
    out_path = args.out or os.path.join(OUT_DIR, PLUGIN_NAME)
    print('iNeed patch (%s): %s' % (os.path.basename(out_path),
                                    ', '.join(args.plugins)))

    food = plan_food(table, args.plugins)
    actors = [] if args.no_factions else plan_actors(args.plugins)
    cats = Counter(c for _p, _f, _n, _s, c in food)
    print('  %d edibles: %s' % (
        len(food), ', '.join('%s %d' % (k, v) for k, v in sorted(cats.items()))))
    print('  %d vendors: %d publicans, %d other merchants'
          % (len(actors), sum(1 for a in actors if a[3]),
             sum(1 for a in actors if not a[3])))

    # An overlay is only worth mastering if it actually overrides one of the
    # records this patch writes; mastering one it never reads would make the
    # patch refuse to load for anyone who does not have that file.
    keys = {(plugin.lower(), low) for plugin, low, _e, _p, _s in actors}
    overlays = overlay_contributors(
        [o for o in args.overlay if os.path.isfile(o)], {'NPC_', 'CONT'}, keys)
    for path in overlays:
        print('  stacking on %s -- its version of a shared record is the one '
              'copied' % os.path.basename(path))

    if args.report:
        write_report(args.report, food, actors)
        print('  report: %s' % args.report)
    if args.dry_run:
        print('  DRY RUN -- nothing written')
        return 0

    patch, stats = build(table, args.plugins, food, actors, overlays,
                         args.output_dir)
    size, records, groups = patch.write(out_path)
    print('  %d form lists, %d innkeepers, %d merchants'
          % (stats['lists'], stats['innkeepers'], stats['merchants']))
    print('  wrote %s  (%s bytes, %d records, %d groups)'
          % (out_path, format(size, ','), records, groups))
    return 0


if __name__ == '__main__':
    sys.exit(main())
