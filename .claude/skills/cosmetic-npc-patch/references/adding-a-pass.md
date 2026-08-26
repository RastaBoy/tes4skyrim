# Adding a pass

A pass owns one field family. Copy `tools/assign_npc_hair.py` — it is the more
complete of the two — and change the middle.

## 1. Decide what the pass OWNS

Name the exact subrecord signatures. If two passes would write the same field,
they are one pass, not two.

Already owned: `DOFT` (outfits), `PNAM` (hair).

## 2. Find the AUTHORED indicator, not a heuristic

Before writing selection logic, census the data and find the flag or reference
that already encodes the distinction. Two worked examples:

- *"NPCs of standard races, not creatures"* → `RACE.DATA` flags bit `0x02`
  (FaceGen Head). A race-name list and a "race comes from Skyrim.esm" test both
  admit Wisp/Skeleton/Draugr.
- *"NPCs in the Bruma region"* → the parent cell and worldspace of every `ACHR`
  pointing at the NPC. No coordinate maths, no cell list.

If you find yourself writing a substring match against EditorIDs to decide
*semantics* (as opposed to matching a user-supplied keyword, which is a
different thing), stop and look for the flag.

## 3. Resolve names to FormIDs, loudly

Curated lists in `constants.py` hold EditorIDs. Resolve them against the plugin
that defines the records, remap into patch space, and **abort** on a name that
does not resolve or a companion part that is missing. `--allow-missing-*` style
escapes are fine; silently dropping an entry is not.

## 4. Be idempotent

Strip what the pass itself may have written before writing again. The hair pass
removes every head part owned by the hair plugin, not just "the one I wrote
last time" — it has no memory of last time.

Then prove it:

```bash
python patch_folder/pipeline.py
cp patch_folder/output/MyCosmeticTamrielPatch.esp /tmp/a.esp
python patch_folder/pipeline.py --only <pass>
cmp /tmp/a.esp patch_folder/output/MyCosmeticTamrielPatch.esp
```

## 5. Place new fields in canonical order

Use `insert_run(subs, sig, payloads, successors)` with a successor tuple drawn
from the canonical NPC_ field order in `binary-facts.md`. Validate the tuple by
reconstructing the position of the field on records that already have it and
comparing against reality — that is how `AFTER_DOFT` was checked against 2,463
records.

## 6. Wire it into the pipeline

Add the block to `patch_folder/pipeline.py`, extend `--only`'s choices, put
patch-specific knobs at the top of the file next to `OUTFIT_RULES`.

## 7. Document it

- `docs/python_tools_reference.md` — the CLI entry, in the same pass.
- `references/data-census.md` here — the counts the pass reports.
- `SKILL.md`'s **Open points** — anything left unresolved.

## If a pass needs a record type the patch does not have

`Patch` rebuilds only the `NPC_` group. Writing a *new* record type (a new
`OTFT`, an `FLST`, an `ARMO`) means teaching `Patch` to rebuild that group too:
generalize `npcs` into a dict of `{signature: OrderedDict}`, and allocate new
FormIDs from the header's `nextObjectID` (`HEDR` offset 8), bumping it as you
go. The patch's own index is `06`; its highest authored FormID today is
`06000D70` against a `nextObjectID` of `0x1AAA`.

Do **not** derive new FormIDs with the converter's `derive_formid()` — that is
the conversion pipeline's save-game contract and has nothing to do with this
plugin.
