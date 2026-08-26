# Verification

## The gate

```bash
python tools/verify_npc_patch.py \
    --patch    patch_folder/output/MyCosmeticTamrielPatch.esp \
    --original patch_folder/sources/MyCosmeticTamrielPatch.esp \
    --source   output/Oblivion.esm/Oblivion.esm \
    --hair-plugin "patch_folder/sources/KS Hairdo's.esp"
```

Non-zero exit if anything fails. Nine checks:

| check | what it proves |
|---|---|
| `structure` | every byte tiles — records and GRUPs nest exactly, and each uncompressed record's subrecords fill its data block |
| `hedr` | HEDR count == records (excluding the file header) + GRUPs |
| `groups` | top-level GRUPs are in canonical xEdit/CK order |
| `masters` | every FormID an NPC_ subrecord references (VMAD included) names a master the patch lists |
| `fidelity` | every subrecord the passes do **not** own is byte-identical to the source after remapping, in the same order |
| `order` | `DOFT` and `PNAM` sit where the canonical field order puts them, each as one unbroken run |
| `carried` | groups no pass touches are byte-identical to `--original` |
| `outfits` | every `DOFT` names a real OTFT — this patch's own (assigned) or the source's (carried) |
| `hair` | `PNAM` starts with a Hair-type part from the hair plugin followed by its Is-Extra-Part companion, gender flags agree with `ACBS`, no stray hair-plugin parts later in the run |

`--owns DOFT,PNAM` lists the fields the passes are allowed to change; extend it
when a new pass claims a field, or `fidelity` will (correctly) fail.

Current baseline, for comparison after a change:

```
PASS structure  2623 records, 27 groups, {NPC_:2597, CELL:10, WRLD:1, OTFT:15}
PASS hedr       2650
PASS groups     NPC_ CELL WRLD OTFT
PASS masters    00=Skyrim.esm:8484  03=Oblivion.esm:38862
                04=KS Hairdo's.esp:5194  06=MyCosmeticTamrielPatch.esp:778
PASS fidelity   91345/91345 subrecords identical to the source after remap
PASS order      DOFT and PNAM canonical in all 2597 records
PASS carried    3 untouched groups byte-identical (CELL WRLD OTFT)
PASS outfits    2418 with an outfit: 778 assigned here (11 distinct), 1640 carried
PASS hair       2597 NPCs, 9 distinct styles, hair+HL leading every run
```

## Reproducibility and idempotence

Not covered by the verifier — check with `cmp`:

```bash
python patch_folder/pipeline.py
cp patch_folder/output/MyCosmeticTamrielPatch.esp /tmp/a.esp
python patch_folder/pipeline.py                       # full rebuild
cmp /tmp/a.esp patch_folder/output/MyCosmeticTamrielPatch.esp   # reproducible
python patch_folder/pipeline.py --only hair           # re-run one pass
cmp /tmp/a.esp patch_folder/output/MyCosmeticTamrielPatch.esp   # idempotent
```

Both must be silent. A refactor of the tools should also reproduce the
*previous* build byte for byte — that is the strongest regression test available
here, and it is how the `plugin_patch.py` extraction was validated.

## What this does NOT cover

**Loading the plugin in SSEEdit or the CK.** Both need the user's live modded
`Data/` folder, which is off-limits (CLAUDE.md). The structural checks above are
stricter than what a load would catch, but a real load is still the user's final
word — as is in-game appearance.

Trust the user's in-game result over any file-based reasoning.

## When a check fails

- `structure` / `hedr` — a bug in `Patch.write()` or in a subrecord payload
  length. Print the offset it names and dump the record.
- `masters` — the remap missed a field. Find the signature and add it to
  `NPC_FORMID_FIELDS` (or to `NPC_PLAIN_FIELDS` if it genuinely holds none) with
  a measurement, not a guess.
- `fidelity` — a pass wrote outside its lane. Diff the record against
  `SourcePlugin`'s copy subrecord by subrecord to find which.
- `order` — the successor tuple for the field is incomplete. Rebuild it from the
  canonical order in `binary-facts.md` and re-validate against records that
  already carry the field.
- `carried` — `Patch` rebuilt a group it should have passed through raw.
