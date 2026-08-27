#!/usr/bin/env python3
"""Census a TES4 plugin's creatures and check them against the patch swap table.

`patch_folder/sources/creature_changes.py` decides, per distinct creature, which
vanilla Skyrim race replaces it. That table is hand-maintained, so the question
that keeps coming back is "which creatures in this plugin does it not cover
yet?" -- after a new mod is added to the conversion, or after a new Skyrim
creature mod is installed and rows can be upgraded from `near` to `exact`.

This reads `export/<plugin>/CREA.txt`, groups the records the same way the table
does (via the table's own group_key_* functions, so the two can never drift),
and prints coverage plus every group with no row. With `--refs` it also counts
what a removal or a swap would actually have to touch -- placed ACRE/ACHR
references and leveled-list entries -- which is the measurement that stops a
"just delete the base records" removal from leaving null refs behind.

    python tools/creature/creature_patch_census.py -f Oblivion.esm
    python tools/creature/creature_patch_census.py -f ElsweyrAnequina.esp --missing
    python tools/creature/creature_patch_census.py -f ElsweyrAnequina.esp \
        --group mountainlion/alfiq --refs
    python tools/creature/creature_patch_census.py -f Knights.esp --json out.json

A plugin with no table of its own (anything but Oblivion.esm and
ElsweyrAnequina.esp) is still censused -- every group simply reports as
unmapped, which is exactly the list needed to write its table.
"""
import argparse
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TABLE = os.path.join(REPO, 'patch_folder', 'sources', 'creature_changes.py')

# TES4 CREA DATA.Type. 4 is the authored mount flag -- see the horse section of
# docs/creature_race_equivalence.md.
CREA_TYPE = {0: 'Creature', 1: 'Daedra', 2: 'Undead', 3: 'Humanoid',
             4: 'Horse', 5: 'Giant'}


def load_table():
    spec = importlib.util.spec_from_file_location('creature_changes', TABLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def records(path):
    """Yield each ---RECORD_BEGIN--- block as {key: [values]}."""
    rec = None
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if line == '---RECORD_BEGIN---':
                if rec is not None:
                    yield rec
                rec = defaultdict(list)
                continue
            if rec is None or '=' not in line:
                continue
            key, _, val = line.partition('=')
            rec[key].append(val)
    if rec is not None:
        yield rec


def one(rec, key, default=''):
    vals = rec.get(key)
    return vals[0] if vals else default


def read_crea(export_dir, table):
    """[{formid, edid, full, folder, nifz, type, group}] for one plugin."""
    path = os.path.join(export_dir, 'CREA.txt')
    if not os.path.isfile(path):
        return None
    plugin = os.path.basename(export_dir)
    elsweyr = 'elsweyr' in plugin.lower()
    out = []
    for rec in records(path):
        model = one(rec, 'Model.MODL').replace(chr(92) * 2, chr(92))
        folder = table._folder_of(model)
        nifz = sorted({v.lower() for k, vs in rec.items()
                       if k.startswith('NIFZ[') for v in vs})
        try:
            dtype = int(one(rec, 'DATA.Type', '0') or 0)
        except ValueError:
            dtype = 0
        full = one(rec, 'FULL')
        if elsweyr:
            group = table.group_key_elsweyr(folder, nifz, dtype, full)
        else:
            group = table.group_key_oblivion(folder, nifz, dtype)
        out.append({'formid': one(rec, 'FormID'), 'edid': one(rec, 'EditorID'),
                    'full': full, 'folder': folder, 'nifz': nifz,
                    'type': dtype, 'group': group})
    return out


def count_refs(export_dir, formids):
    """How many placed refs and leveled-list entries name these base records.

    Deleting or swapping a creature has to reach all three layers; counting only
    the base records is the failure mode that leaves null references.
    """
    result = {'placed': 0, 'leveled_lists': 0, 'leveled_entries': 0,
              'lists': [], 'other_files': {}}
    wanted = set(formids)
    for fn in ('ACRE.txt', 'ACHR.txt'):
        path = os.path.join(export_dir, fn)
        if not os.path.isfile(path):
            continue
        for rec in records(path):
            if one(rec, 'NAME') in wanted:
                result['placed'] += 1
    path = os.path.join(export_dir, 'LVLC.txt')
    if os.path.isfile(path):
        for rec in records(path):
            hits = [v for k, vs in rec.items()
                    if k.startswith('Entry[') and k.endswith('].FormID')
                    for v in vs if v in wanted]
            if hits:
                result['leveled_lists'] += 1
                result['leveled_entries'] += len(hits)
                result['lists'].append((one(rec, 'EditorID'), len(hits)))
    # Anything else that names them -- scripts, quests, dialogue, packages.
    # A plain substring count, so it over-reports; it is a "look here" signal,
    # not a measurement. Verify each hit before acting on it.
    skip = {'CREA.txt', 'ACRE.txt', 'ACHR.txt', 'LVLC.txt', 'CELL.txt',
            'LAND.txt'}
    for fn in sorted(os.listdir(export_dir)):
        if not fn.endswith('.txt') or fn in skip:
            continue
        try:
            text = open(os.path.join(export_dir, fn), encoding='utf-8',
                        errors='replace').read()
        except OSError:
            continue
        n = sum(text.count(f) for f in wanted)
        if n:
            result['other_files'][fn] = n
    return result


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-f', '--plugin', required=True,
                    help='plugin name as it appears under export/')
    ap.add_argument('--missing', action='store_true',
                    help='only groups the swap table does not cover')
    ap.add_argument('--group', help='drill into one group: list every record')
    ap.add_argument('--refs', action='store_true',
                    help='also count placed refs and leveled-list entries')
    ap.add_argument('--json', help='write the census here as JSON')
    args = ap.parse_args()

    table = load_table()
    export_dir = os.path.join(REPO, 'export', args.plugin)
    crea = read_crea(export_dir, table)
    if crea is None:
        print('no export/%s/CREA.txt -- run the export stage first' % args.plugin)
        return 2

    swaps = {'Oblivion.esm': table.OBLIVION_SWAPS,
             'ElsweyrAnequina.esp': table.ELSWEYR_SWAPS}.get(args.plugin, {})
    if not swaps:
        print('NOTE: %s has no swap table yet -- every group reports unmapped, '
              'which is the list to start from.\n' % args.plugin)

    by_group = defaultdict(list)
    for c in crea:
        by_group[c['group']].append(c)

    if args.group:
        rows = by_group.get(args.group)
        if not rows:
            print('no group %r in %s. Known groups: %s'
                  % (args.group, args.plugin, ', '.join(sorted(by_group))))
            return 2
        swap = swaps.get(args.group)
        print('=== %s / %s -- %d records ===' % (args.plugin, args.group,
                                                 len(rows)))
        if swap is not None:
            print('    %s -> %s' % (swap.tier, swap.target or 'keep converted'))
            if swap.note:
                print('    %s' % swap.note)
        for c in sorted(rows, key=lambda r: (r['full'], r['edid'])):
            mount = ' MOUNT' if c['type'] == 4 else ''
            print('  %s %-34s %-30s %s%s'
                  % (c['formid'], c['edid'], c['full'],
                     CREA_TYPE.get(c['type'], c['type']), mount))
        if args.refs:
            refs = count_refs(export_dir, [c['formid'] for c in rows])
            print('\n  placed refs (ACRE/ACHR): %d' % refs['placed'])
            print('  leveled lists: %d, entries: %d'
                  % (refs['leveled_lists'], refs['leveled_entries']))
            for name, n in sorted(refs['lists']):
                print('     %-40s %d' % (name, n))
            if refs['other_files']:
                print('  ALSO NAMED IN (substring match -- verify each):')
                for fn, n in sorted(refs['other_files'].items()):
                    print('     %-14s %d' % (fn, n))
            else:
                print('  nothing else names them: no script, quest, dialogue '
                      'or package dependency')
        return 0

    tally = Counter()
    unmapped = []
    print('=== %s -- %d CREA in %d groups ==='
          % (args.plugin, len(crea), len(by_group)))
    for key in sorted(by_group, key=lambda k: -len(by_group[k])):
        rows = by_group[key]
        swap = swaps.get(key)
        mounts = sum(1 for c in rows if c['type'] == 4)
        if swap is None:
            tally['unmapped'] += len(rows)
            unmapped.append((key, len(rows), rows[0]['full']))
            tier, target = '?', '(unmapped)'
        else:
            tally[swap.tier] += len(rows)
            tier = swap.tier
            target = ('DELETE' if swap.tier == table.REMOVE
                      else swap.target or 'keep converted')
        if args.missing and swap is not None:
            continue
        print('  %-28s %4d%-9s %-7s %-34s %s'
              % (key, len(rows), ' MOUNT:%d' % mounts if mounts else '',
                 tier, target,
                 Counter(c['full'] for c in rows).most_common(1)[0][0]))

    print('\n  exact %d | near %d | keep %d | remove %d | unmapped %d'
          % (tally[table.EXACT], tally[table.NEAR], tally[table.NONE],
             tally[table.REMOVE], tally['unmapped']))
    if unmapped:
        print('\n  %d group(s) need a row in creature_changes.py:' % len(unmapped))
        for key, n, sample in unmapped:
            print('     %-28s %4d  e.g. %s' % (key, n, sample))

    if args.json:
        payload = {'plugin': args.plugin, 'records': len(crea),
                   'groups': {k: {'count': len(v),
                                  'mounts': sum(1 for c in v if c['type'] == 4),
                                  'sample': [c['full'] for c in v[:5]],
                                  'swap': (swaps[k].target
                                           if k in swaps else None),
                                  'tier': (swaps[k].tier
                                           if k in swaps else 'unmapped')}
                              for k, v in by_group.items()}}
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2)
        print('\nwrote %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
