#!/usr/bin/env python3
"""Give every humanoid NPC of a source plugin a random hairstyle, written as
NPC_ overrides into a patch plugin.

For each selected NPC the head-part run (PNAM) is rewritten:

  * every existing Hair-type head part is removed, along with any head part
    that came from the hair plugin -- so a re-run replaces its own previous
    choice instead of stacking on it;
  * the chosen hair goes in at that spot (the "Hair" base part);
  * its `<name><--hl-suffix>` companion part goes in right after it, as an
    additional head part -- KS Hairdo's ships each hair with a matching
    hairline part flagged "Is Extra Part".

Everything else in the NPC record -- eyes, tint layers, outfit, factions -- is
carried through untouched, so this composes with the other assign_* tools on
the same patch.

Which NPCs count as "humanoid" is not guessed: by default it is every NPC whose
RACE record comes from `--races-from` (Skyrim.esm), which is exactly the set the
converter gave FaceGen head parts to. Creature races are the converted plugin's
own RACE records and are never selected.

Usage:
    python tools/patch/assign_npc_hair.py \
        --source output/Oblivion.esm/Oblivion.esm \
        --patch  patch_folder/output/MyCosmeticTamrielPatch.esp \
        --out    patch_folder/output/MyCosmeticTamrielPatch.esp \
        --hair-plugin "patch_folder/sources/KS Hairdo's.esp" \
        --constants patch_folder/sources/constants.py \
        --hdpt-from "<SSE>/Data/Skyrim.esm" \
        --report temp/npc_hair.tsv
"""

import argparse
import hashlib
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.patch.plugin_patch import (          # noqa: E402
    ACBS_FEMALE, AFTER_PNAM, Patch, SourcePlugin, first, insert_run,
    make_remap, remap_fid, remap_npc_record, zstring,
)

HDPT_TYPE = {0: 'Misc', 1: 'Face', 2: 'Eyes', 3: 'Hair', 4: 'FacialHair',
             5: 'Scar', 6: 'Eyebrows'}
HDPT_TYPE_HAIR = 3
RACE_FLAG_FACEGEN = 0x00000002   # RACE.DATA flags offset 32: "FaceGen Head"
HDPT_FLAG_MALE = 0x02
HDPT_FLAG_FEMALE = 0x04


def _race_flags(data):
    """RACE.DATA flags word (offset 32), or None if the record is too short."""
    if not data or len(data) < 36:
        return None
    return struct.unpack_from('<I', data, 32)[0]


def load_constants(path):
    ns = {}
    exec(compile(Path(path).read_text(encoding='utf-8'), str(path), 'exec'),
         ns, ns)
    return {k: v for k, v in ns.items() if not k.startswith('_')}


def read_hdpt(path, patch_masters):
    """{patch-space FormID: (EditorID, type, flags)} for one plugin's HDPT.

    Also returns {editorid_lower: patch-space FormID}.
    """
    plugin = SourcePlugin(path, {'HDPT'})
    mapping = make_remap(plugin.masters, patch_masters, plugin.name)
    by_fid = {}
    by_edid = {}
    for fid, (_hdr, subs) in plugin.by_type['HDPT'].items():
        edid = zstring(first(subs, 'EDID'))
        data = first(subs, 'DATA')
        pnam = first(subs, 'PNAM')
        pfid = remap_fid(fid, mapping)
        by_fid[pfid] = (edid, struct.unpack('<I', pnam)[0] if pnam else None,
                        data[0] if data else 0)
        by_edid[edid.lower()] = pfid
    return by_fid, by_edid


def main():
    ap = argparse.ArgumentParser(
        description='Give humanoid NPCs a random hairstyle from a hair plugin, '
                    'written as NPC_ overrides into a patch plugin.')
    ap.add_argument('--source', required=True,
                    help='plugin the NPCs come from (must be a master of the patch)')
    ap.add_argument('--patch', required=True, help='patch plugin to extend')
    ap.add_argument('--out', help='output plugin path (default: overwrite --patch)')
    ap.add_argument('--hair-plugin', required=True,
                    help='plugin holding the hair HDPT records (a master of the patch)')
    ap.add_argument('--constants', required=True,
                    help='python file defining the haircut EditorID lists')
    ap.add_argument('--male-haircuts', default='MALE_HAIRCUTS',
                    help='constant name listing hairs for non-female NPCs')
    ap.add_argument('--female-haircuts', default='FEMALE_HAIRCUTS',
                    help='constant name listing hairs for female NPCs')
    ap.add_argument('--hl-suffix', default='HL',
                    help='suffix of the companion head part added alongside '
                         'each hair (default: HL)')
    ap.add_argument('--races-from', default='',
                    help='additionally require the RACE record to live in this '
                         'plugin (default: no restriction)')
    ap.add_argument('--exclude-race', action='append', default=[],
                    metavar='RACE',
                    help='skip every NPC on this race: either its EditorID '
                         '(ArgonianRace) or an 8-digit hex FormID in the '
                         'source plugin\'s own numbering; repeatable. An '
                         'EditorID that resolves to no loaded RACE aborts')
    ap.add_argument('--hdpt-from', action='append', default=[],
                    metavar='PLUGIN',
                    help='extra plugin to read HDPT types (and RACE names) from, '
                         'so existing head parts can be classified; repeatable')
    ap.add_argument('--allow-missing-hl', action='store_true',
                    help='use a hair that has no <name>HL companion instead of '
                         'aborting')
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

    # ---- hair plugin --------------------------------------------------------
    hair_by_fid, hair_by_edid = read_hdpt(args.hair_plugin, patch.masters)
    hair_fids = set(hair_by_fid)
    print(f'{Path(args.hair_plugin).name}: {len(hair_by_fid)} HDPT records')

    def resolve_list(const_name, gender_flag):
        names = consts.get(const_name)
        if names is None:
            derived = sorted(
                edid for edid, typ, flags in hair_by_fid.values()
                if typ == HDPT_TYPE_HAIR and flags & gender_flag
                and (edid + args.hl_suffix).lower() in hair_by_edid)
            print(f'!! {args.constants} has no list named {const_name}; '
                  f'falling back to every {"female" if gender_flag & HDPT_FLAG_FEMALE else "male"} '
                  f'hair in {Path(args.hair_plugin).name} that has a '
                  f'"{args.hl_suffix}" companion ({len(derived)} styles). '
                  f'Add {const_name} and re-run to use your own selection.')
            names = derived
        out, missing = [], []
        for n in names:
            fid = hair_by_edid.get(n.lower())
            if fid is None:
                raise SystemExit(f'{const_name}: no HDPT with EditorID "{n}" in '
                                 f'{Path(args.hair_plugin).name}')
            hl = hair_by_edid.get((n + args.hl_suffix).lower())
            if hl is None:
                missing.append(n)
            out.append((n, fid, hl))
        if missing and not args.allow_missing_hl:
            raise SystemExit(
                f'{const_name}: {len(missing)} hair(s) have no '
                f'"{args.hl_suffix}" companion head part: '
                f'{", ".join(missing[:10])}'
                + (' ...' if len(missing) > 10 else '')
                + '\nFix the list, or pass --allow-missing-hl to use the hair '
                  'on its own.')
        return out

    male_table = resolve_list(args.male_haircuts, HDPT_FLAG_MALE)
    female_table = resolve_list(args.female_haircuts, HDPT_FLAG_FEMALE)
    if not male_table or not female_table:
        raise SystemExit('both haircut lists must be non-empty')
    print(f'haircuts: {len(male_table)} male, {len(female_table)} female')

    # ---- source plugin ------------------------------------------------------
    src = SourcePlugin(args.source, {'NPC_', 'HDPT', 'RACE'})
    mapping = make_remap(src.masters, patch.masters, src.name)
    print(f'source masters: {src.masters}')
    print('master index remap: '
          + ', '.join(f'{k:02X}->{v:02X}' for k, v in sorted(mapping.items())))

    # Head-part types, keyed in the patch's FormID space, from every plugin we
    # can see. An unresolved head part is left alone and counted.
    hdpt_types = dict(hair_by_fid)
    for fid, (_hdr, subs) in src.by_type['HDPT'].items():
        pnam = first(subs, 'PNAM')
        data = first(subs, 'DATA')
        hdpt_types[remap_fid(fid, mapping)] = (
            zstring(first(subs, 'EDID')),
            struct.unpack('<I', pnam)[0] if pnam else None,
            data[0] if data else 0)
    race_names = {}
    race_flags = {}
    for path in args.hdpt_from:
        extra = SourcePlugin(path, {'HDPT', 'RACE'})
        emap = make_remap(extra.masters, patch.masters, extra.name)
        for fid, (_hdr, subs) in extra.by_type['HDPT'].items():
            pnam = first(subs, 'PNAM')
            data = first(subs, 'DATA')
            hdpt_types.setdefault(remap_fid(fid, emap), (
                zstring(first(subs, 'EDID')),
                struct.unpack('<I', pnam)[0] if pnam else None,
                data[0] if data else 0))
        for fid, (_hdr, subs) in extra.by_type['RACE'].items():
            pfid = remap_fid(fid, emap)
            race_names[pfid] = zstring(first(subs, 'EDID'))
            race_flags[pfid] = _race_flags(first(subs, 'DATA'))
        print(f'{Path(path).name}: +{len(extra.by_type["HDPT"])} HDPT, '
              f'{len(extra.by_type["RACE"])} RACE for classification')
    for fid, (_hdr, subs) in src.by_type['RACE'].items():
        pfid = remap_fid(fid, mapping)
        race_names.setdefault(pfid, zstring(first(subs, 'EDID')))
        race_flags.setdefault(pfid, _race_flags(first(subs, 'DATA')))

    # ---- pick the NPCs ------------------------------------------------------
    race_master_idx = None
    if args.races_from:
        try:
            race_master_idx = [m.lower() for m in src.masters].index(
                args.races_from.lower())
        except ValueError:
            raise SystemExit(f'{src.name} does not list "{args.races_from}" as '
                             'a master, so no race can come from it')
    # A race is named by EditorID or by FormID. The EditorID is what a human
    # reads in `EXCLUDE_RACES`, and it survives the converter pointing beast
    # NPCs at a different record; the hex form stays for a race with no name
    # in any loaded plugin. Eight hex digits is the FormID form, so a race
    # whose EditorID happens to be hex-shaped is still read as a name.
    by_name = {name.lower(): pfid for pfid, name in race_names.items() if name}
    excluded = set()          # source-plugin numbering
    excluded_patch = set()    # patch numbering, from EditorIDs
    unresolved = []
    for value in args.exclude_race:
        if re.fullmatch(r'[0-9A-Fa-f]{8}', value):
            excluded.add(int(value, 16))
        elif value.lower() in by_name:
            excluded_patch.add(by_name[value.lower()])
        else:
            unresolved.append(value)
    if unresolved:
        raise SystemExit(
            '--exclude-race names no RACE in any loaded plugin: '
            + ', '.join(unresolved)
            + '. Pass the plugin that defines it with --hdpt-from, or give an '
              '8-digit FormID instead')

    selected = []
    per_race = Counter()
    skipped_race = Counter()
    rejected = Counter()
    unknown_race = Counter()
    for fid, (_hdr, subs) in src.by_type['NPC_'].items():
        rnam = first(subs, 'RNAM')
        race = struct.unpack('<I', rnam)[0] if rnam else 0
        if not rnam or race in excluded or (
                remap_fid(race, mapping) in excluded_patch):
            rejected[race] += 1
            if rnam:
                skipped_race[race] += 1
            continue
        if race_master_idx is not None and race >> 24 != race_master_idx:
            rejected[race] += 1
            continue
        flags = race_flags.get(remap_fid(race, mapping))
        if flags is None:
            unknown_race[race] += 1
            rejected[race] += 1
            continue
        # "FaceGen Head" is the engine's own marker for a race that wears head
        # parts. Every creature race in both plugins has it clear; every
        # playable race plus Dremora has it set. No heuristic needed.
        if not flags & RACE_FLAG_FACEGEN:
            rejected[race] += 1
            continue
        selected.append(fid)
        per_race[race] += 1
    selected.sort()

    if skipped_race:
        print(f'excluded races: {sum(skipped_race.values())} NPCs left alone')
        for race, count in skipped_race.most_common():
            print(f'  {race:08X} '
                  f'{race_names.get(remap_fid(race, mapping), "?"):16} {count}')
    print(f'NPCs on a FaceGen-head race: {len(selected)} '
          f'(skipped {sum(rejected.values())} on races without one)')
    for race, count in per_race.most_common():
        print(f'  {race:08X} {race_names.get(remap_fid(race, mapping), "?"):16} '
              f'{count}')
    if unknown_race:
        print(f'  !! {sum(unknown_race.values())} NPCs skipped because their '
              f'RACE is defined in no loaded plugin '
              f'({", ".join(f"{r:08X}" for r in list(unknown_race)[:6])}); '
              'pass that plugin with --hdpt-from')

    # ---- assign -------------------------------------------------------------
    assignments = []
    for fid in selected:
        subs = src.by_type['NPC_'][fid][1]
        acbs = first(subs, 'ACBS')
        female = bool(acbs and struct.unpack_from('<I', acbs, 0)[0] & ACBS_FEMALE)
        table = female_table if female else male_table
        digest = hashlib.sha256(f'hair:{args.seed}:{fid:08X}'.encode()).digest()
        rng = Random(int.from_bytes(digest[:8], 'little'))
        name, hair_fid, hl_fid = table[rng.randrange(len(table))]
        assignments.append((fid, zstring(first(subs, 'EDID')),
                            zstring(first(subs, 'FULL')),
                            'F' if female else 'M', name, hair_fid, hl_fid))

    print(f'  female: {sum(1 for a in assignments if a[3] == "F")}, '
          f'male: {sum(1 for a in assignments if a[3] == "M")}')

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, 'w', encoding='utf-8') as fh:
            fh.write('SOURCE_FORMID\tPATCH_FORMID\tEDITORID\tNAME\tSEX\tHAIR\tHL\n')
            for fid, edid, full, sex, name, _h, hl in assignments:
                fh.write(f'{fid:08X}\t{remap_fid(fid, mapping):08X}\t{edid}\t'
                         f'{full}\t{sex}\t{name}\t'
                         f'{name + args.hl_suffix if hl else ""}\n')
        print(f'report: {args.report}')

    if args.dry_run:
        print('dry run: nothing written')
        return

    # ---- write --------------------------------------------------------------
    added = updated = 0
    removed = Counter()
    unresolved = Counter()
    kept_total = 0
    for fid, _edid, _full, _sex, _name, hair_fid, hl_fid in assignments:
        pfid = remap_fid(fid, mapping)
        if pfid in patch.npcs:
            header, subs = patch.npcs[pfid]
            updated += 1
        else:
            header, subs = remap_npc_record(*src.by_type['NPC_'][fid], mapping)
            added += 1

        kept = []
        for sig, payload in subs:
            if sig != 'PNAM':
                continue
            target = struct.unpack('<I', payload)[0]
            info = hdpt_types.get(target)
            if info is None:
                unresolved[target] += 1
                kept.append(payload)
                continue
            if info[1] == HDPT_TYPE_HAIR or target in hair_fids:
                removed[HDPT_TYPE.get(info[1], info[1])] += 1
                continue
            kept.append(payload)
        kept_total += len(kept)

        new_run = [struct.pack('<I', hair_fid)]
        if hl_fid:
            new_run.append(struct.pack('<I', hl_fid))
        subs = insert_run(subs, 'PNAM', new_run + kept, AFTER_PNAM)
        patch.set_npc(pfid, header, subs)

    print(f'head parts removed: {dict(removed)}; kept (eyes etc.): {kept_total}')
    if unresolved:
        print(f'head parts left in place because no loaded plugin defines them: '
              f'{sum(unresolved.values())} references, '
              f'{len(unresolved)} distinct '
              f'({", ".join(f"{f:08X}" for f in list(unresolved)[:6])})')

    size, records, groups = patch.write(out_path)
    print(f'NPC_ overrides: {added} added, {updated} updated, '
          f'{len(patch.npcs)} total')
    print(f'wrote {out_path} ({size:,} bytes, {records} records, {groups} groups)')


if __name__ == '__main__':
    main()
