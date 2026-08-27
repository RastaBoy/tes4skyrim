---
name: cosmetic-npc-patch
description: >-
  Build and extend MyCosmeticTamrielPatch.esp — the hand-authored ESP in
  patch_folder/ that restyles the converted Oblivion NPCs (outfits, hair, and
  whatever comes next) by writing NPC_ override records straight into a binary
  TES5 plugin. Covers the patch's architecture (tools/patch/plugin_patch.py plus one
  assign_*.py pass per feature, driven by patch_folder/pipeline.py), the
  measured binary facts an override plugin must respect (HEDR record count,
  top-level GRUP order, canonical NPC_ field order, the NPC_ FormID field map,
  VMAD property walking, the RACE FaceGen-head flag, HDPT type/flag layout), the
  census of this project's actual data, the recipe for adding a new pass, and
  the verification suite that must pass before shipping. Use when asked to
  change what NPCs in the converted plugin wear or look like, to add a pass to
  the cosmetic patch, to debug a record the patch writes, or to author any
  Skyrim ESP that overrides master records from Python.
---

# The cosmetic NPC patch

`patch_folder/` builds **MyCosmeticTamrielPatch.esp**: an ESP that restyles the
NPCs of the converted `output/Oblivion.esm/Oblivion.esm` by overriding their
`NPC_` records. It is authored in Python, directly on the binary — no Creation
Kit, no xEdit scripting.

```
patch_folder/
  pipeline.py         one command, all passes, reproducible from sources/
  sources/            INPUTS, never written to
    MyCosmeticTamrielPatch.esp   the hand-made ESP: OTFT + CELL/WRLD, no NPCs
    KS Hairdo's.esp              2,701 HDPT records
    Apachii_DivineEleganceStore.esm
    constants.py                 the curated EditorID lists
  output/             the built plugin
  reports/            per-pass TSV of every decision
tools/
  plugin_patch.py             shared library (read, override, remap, write)
  assign_female_outfits.py    pass: DOFT
  assign_npc_hair.py          pass: PNAM head parts
  assign_skin_tone.py         pass: QNAM texture lighting
  verify_npc_patch.py         the ship gate
```

Run it:

```bash
python patch_folder/pipeline.py                # full build
python patch_folder/pipeline.py --dry-run      # report only
python patch_folder/pipeline.py --only hair    # one pass, keeps the others' work
python patch_folder/pipeline.py --only skin    # outfits | hair | skin
python patch_folder/pipeline.py --seed 7       # a different random draw
```

Reference files — open the one you need:

- **`references/architecture.md`** — the override model, the composability
  contract every pass must honor, and how `Patch` / `SourcePlugin` work.
- **`references/binary-facts.md`** — every measured fact about the TES5 binary
  this code depends on. Do not re-derive these; they were measured, not guessed.
- **`references/data-census.md`** — the real numbers: races, NPC counts, what
  the converted NPCs' head parts actually contain, what KS Hairdo's ships.
- **`references/adding-a-pass.md`** — the recipe for a new cosmetic pass.
- **`references/verification.md`** — the checks that must pass before shipping,
  and the reusable verification script.

---

## The three rules

### 1. A pass writes ONLY its own fields

Every pass copies the master's record byte for byte (xEdit's "copy as
override"), remaps FormID master indexes into the patch's load order, and
substitutes only the subrecords it owns. A field a pass never touches cannot
drift, so there is no class of "our pass re-derived it differently" bug.

Concretely: the outfit pass owns `DOFT`, the hair pass `PNAM`, the skin-tone
pass `QNAM`. None of them knows the others exist, and running all three leaves
every edit intact.

### 2. Passes compose, and every pass is idempotent

`Patch` (in `tools/patch/plugin_patch.py`) loads the patch's existing `NPC_` group and
hands each pass the record that is already there, if there is one. So:

- running pass B after pass A keeps A's edits;
- running the same pass twice produces a **byte-identical** file.

Idempotence is not free — a pass that *adds* something must also strip its own
previous addition. The hair pass removes every head part owned by the hair
plugin before writing the new one, which is why re-running it replaces its
choice instead of stacking hairstyles.

**Verify both properties after every change.** `cmp` the file against a re-run.

### 3. Random means seeded, never `random.random()`

Choices come from `sha256(f'{tag}:{seed}:{formid:08X}')`, so a build is
reproducible and a re-run never reshuffles the whole world.

Seed the RNG from that **hash**, not from the raw FormID: NPCs of one town have
consecutive FormIDs, and a Mersenne twister seeded with consecutive small ints
is visibly correlated over a short list — the raw-FormID version put 12 of
Bruma's 21 women in the same outfit out of three.

---

## Load order and FormID spaces

The patch's masters, in order — the index is the FormID's high byte:

| idx | master |
|---|---|
| `00` | Skyrim.esm |
| `01` | Update.esm |
| `02` | Apachii_DivineEleganceStore.esm |
| `03` | **Oblivion.esm** (the converted plugin — where the NPCs come from) |
| `04` | **KS Hairdo's.esp** (the hair HDPT) |
| `05` | ElsweyrAnequina.esp |
| `06` | the patch's own records (its OTFT) |

`Oblivion.esm` itself lists only `Skyrim.esm`, so inside it index `00` is
Skyrim and `01` is itself. Copying a record into the patch therefore rewrites
`01xxxxxx` → `03xxxxxx` and leaves `00xxxxxx` alone. `make_remap()` derives this
from the two master lists; never hardcode it.

**A blind byte scan for `01`-prefixed words would corrupt the record.** The
remap walks a per-subrecord FormID map (`NPC_FORMID_FIELDS`) and a real VMAD
property walker. An unknown subrecord signature **aborts the run** rather than
shipping a stale master index — that guard is the point, do not relax it.

---

## What each pass currently does

### Outfits — `assign_female_outfits.py`

Every **female** NPC (`ACBS` flags bit 0) gets a random `OTFT` from a list in
`constants.py`, resolved to the patch's own OTFT records by EditorID.

Which list depends on **where the NPC is placed**: every `ACHR` pointing at the
NPC contributes its parent cell, and the cell's EditorID/FULL plus its
worldspace's EditorID/FULL are matched against `--match-outfits` keywords.
`bruma=BRUMA_OUTFITS_TO_CHOOSE` therefore catches `BrumaWorld` and every
`Bruma*` interior without naming a single cell.

### Hair — `assign_npc_hair.py`

Every NPC on a **FaceGen-head race** gets a random hair from `MALE_HAIRCUTS` or
`FEMALE_HAIRCUTS` (by the same `ACBS` female bit), plus the hair's
`<name>HL` companion part.

The head-part run is rebuilt as `[hair, hairHL, ...everything that was not
hair]`, which in practice means the eyes survive and the converted Oblivion hair
is dropped.

### Skin tone — `assign_skin_tone.py`

`QNAM` (texture lighting) and the skin-tone tint layer are the same colour
written twice; the engine lights the body from one and paints the face from the
other. The converter derived QNAM by blending the tint toward **white**, but the
engine's base is **mid-grey 127**, so every converted NPC's body came out a flat
26/255 paler than its face. This pass re-derives QNAM from the layer the record
already carries, via `tes5_import.npc_face_mapper.skin_tone_qnam()` — shared with
the converter so the two cannot drift.

Which layer is the skin tone is authored too: the RACE record's tint masks carry
`TINP == 6` for Skin Tone, in a male set and a female set. See
`references/binary-facts.md`.

**Humanoid-vs-creature is decided by the engine's own flag**, not a race-name
list: `RACE.DATA` flags word at offset 32, bit `0x02` = *FaceGen Head*. See
`references/binary-facts.md`. Race-name lists and "does it have head parts"
heuristics both get this wrong — `WispRace`, `SkeletonRace` and `DraugrRace` are
vanilla Skyrim races and would pass a "race comes from Skyrim.esm" test.

---

## Before you ship

Run `references/verification.md`'s checks. The short version: the file must tile
byte-exactly, `HEDR` must match records+groups, every previous pass's field must
still be intact, every FormID must land on a master the patch actually lists,
and every subrecord the pass does not own must be byte-identical to the source
after remapping.

SSEEdit lives at `references/SSEEdit 4.1.5f`, but loading this patch needs the
user's live modded `Data/` folder — **off-limits per CLAUDE.md**. The Python
verification above is stricter structurally; the final "it loads clean" check is
the user's to run.

---

## Open points

Track anything unresolved here so the next session does not rediscover it.

- **The converter still ships the old QNAM formula on the branch that actually
  builds `output/Oblivion.esm`.** That plugin comes from `upstream/master`
  (commit `e3779f8`), which this branch does not contain; the fix here is on
  `self-patches`' older copy of the same formula. The patch pass corrects the
  built plugin either way, so nothing is blocked — but the one-line change wants
  porting, and until it is, a fresh import re-introduces the mismatch.
- **`_SKIN_TINV = 80` is now a coherent knob.** It pulls the skin 20% toward
  mid-grey — face and body together, since the fix. 995 of 1,071 vanilla NPCs
  write `TINV=100` instead, which would give the raw reconstructed Oblivion
  colour. Worth trying if the tone still reads wrong.
- **Dremora (115 NPCs) currently get KS hairdos.** They carry a FaceGen head so
  they pass the humanoid test, and they are not creatures — but the look may be
  wrong. Excluded with `--exclude-race 000131F0`, or by adding that FormID to
  `EXCLUDE_RACES` in `patch_folder/pipeline.py`.
- **`_Elf` hair variants are not used.** KS ships `<name>_Elf` meshes shaped for
  elf head geometry; the passes pick whatever the constants list names, with no
  per-race variant substitution. If elf ears clip, that is the lead.
- **The HL part is added to the NPC on top of the hair's own `HNAM` extra-part
  list**, which already references it. That is what NPC-replacer mods do and it
  was explicitly requested, but it is a duplicate reference if a rendering
  oddity ever points here.
- **ElsweyrAnequina.esp's own 882 NPCs get nothing.** It overrides zero
  Oblivion.esm NPCs (measured), so there is no conflict — but its NPCs are
  outside every pass's source. `ELSW_OUTFITS_TO_CHOOSE` exists in
  `constants.py` unused; wiring it up is `--source .../ElsweyrAnequina.esp
  --default-outfits ELSW_OUTFITS_TO_CHOOSE`.
