---
name: cosmetic-npc-patch
description: >-
  Build and extend the MyOwnTamriel* patch plugins — the ESPs built from
  patch_folder/ that restyle the converted Oblivion NPCs (outfits, hair, skin
  tone) and swap their creatures and horses for vanilla Skyrim ones, by writing
  override records straight into a binary TES5 plugin. Covers the patches'
  architecture (tools/patch/plugin_patch.py and patch_builder.py plus one
  assign_*.py pass per feature, all driven by tools/patch/build_patch.py and
  the GUI's Patches section), the
  measured binary facts an override plugin must respect (HEDR record count,
  top-level GRUP order, canonical NPC_ field order, the NPC_ FormID field map,
  VMAD property walking, the RACE FaceGen-head flag, HDPT type/flag layout), the
  census of this project's actual data, the recipe for adding a new pass, and
  the verification suite that must pass before shipping. Use when asked to
  change what NPCs in the converted plugins wear or look like, to add a pass to
  the cosmetic patch, to build or change the creature/horse patches, to debug a
  record a patch writes, or to author any Skyrim ESP that overrides master
  records from Python.
---

# The cosmetic NPC patch

`patch_folder/` builds **MyOwnTamrielCosmeticPatch.esp**: an ESP that restyles
the NPCs of the converted plugins by overriding their `NPC_` records. It is
authored in Python, directly on the binary — no Creation Kit, no xEdit
scripting.

Its sibling patches (creatures, horses) share the same library and driver but
not this document's passes; see `docs/python_tools_reference.md` and
`patch_folder/sources/creature_changes.py`.

```
patch_folder/
  pipeline.py         shim over tools/patch/build_patch.py --patch cosmetic
  sources/            INPUTS, never written to
    MyCosmeticTamrielPatch.esp   the hand-made template; only its OTFT records
                                 are carried, its master list is discarded
    creature_changes.py          the creature/mount swap decisions
    KS Hairdo's.esp              2,701 HDPT records
    Apachii_DivineEleganceStore.esm
    constants.py                 the curated EditorID lists
  output/             the built plugin
  reports/            per-pass TSV of every decision
tools/patch/
  plugin_patch.py             shared library (read, override, remap, write)
  patch_builder.py            build an ESP from scratch: computed masters,
                              flat groups, cell-nested ACHR overrides, ONAM
  build_patch.py              the driver for all three patches, and the zip
  assign_female_outfits.py    pass: DOFT
  assign_npc_hair.py          pass: PNAM head parts
  assign_skin_tone.py         pass: QNAM texture lighting
  assign_creatures.py         the creature/mount patch (not a cosmetic pass)
  merge_plugins.py            fold several plugins into one; --drop-master
                              cuts a master loose with everything that needs it
  verify_npc_patch.py         the ship gate
```

Run it — through the GUI's **Patches** section, or on the command line:

```bash
python tools/patch/build_patch.py --patch cosmetic --plugins Oblivion.esm ElsweyrAnequina.esp
python tools/patch/build_patch.py --list          # every patch this app builds
python patch_folder/pipeline.py                   # shim: cosmetic, all plugins
python patch_folder/pipeline.py --dry-run
```

**The build moved (2026-08-27).** `tools/patch/build_patch.py` now drives all
three patches -- `cosmetic`, `creatures`, `horses` -- through one pipeline, and
`patch_folder/pipeline.py` is a thin shim over its cosmetic half. Two things
changed that this document's older model got wrong:

* **The master list is computed, not fixed.** The patch no longer starts from
  `sources/MyCosmeticTamrielPatch.esp` with its six baked-in masters; a seed is
  built from scratch carrying only that file's own `OTFT` records, mastering
  exactly what the chosen plugins need. The load-order table further down is
  therefore an EXAMPLE, not a constant -- `make_remap()` still derives the
  remap, which is what makes that safe.
* **A build can cover several source plugins.** Each pass runs once per plugin,
  which is what finally reaches ElsweyrAnequina's own NPCs (215 women, routed to
  `ELSW_OUTFITS_TO_CHOOSE` by `SOURCE_OUTFITS`). Measured 2026-08-27 over
  Oblivion.esm + ElsweyrAnequina.esp: **3,192 NPC_ overrides**, every check in
  `verify_npc_patch.py` passing.

The output plugin is now `MyOwnTamrielCosmeticPatch.esp`, and the driver zips it
into `output/Finished Mods/` like any converted mod.

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

### 🛑 Two patches over one NPC do not merge

The later plugin wins the **whole record**. `MyOwnTamrieliNeedPatch.esp`
overrides 220 of these same NPCs (every merchant is also somebody this patch
restyled), and copying them off the converted master meant one of the two
patches was always thrown away — measured, and the reason merchants shipped
with no stock. The iNeed patch now reads through `SourceStack` and MASTERS this
one (`STACK_ON` in `build_patch.py`), so it loads last and carries these
fields through.

**Consequence: rebuild the iNeed patch after rebuilding this one**, or its copy
of those 220 actors is stale and wins anyway. Any new patch that touches an NPC
this one touches needs the same treatment.

---

## What each pass currently does

### Outfits — `assign_female_outfits.py`

Every **female** NPC (`ACBS` flags bit 0) gets a random `OTFT` from a list in
`constants.py`, resolved to the patch's own OTFT records by EditorID.

Which list depends on two rule families, **who she is** before **where she is**:

* `--match-npc-outfits` matches her own EditorID/FULL and the EditorID/FULL of
  every FACTION she belongs to. `bandit=FEMALE_BANDITS_OUTFITS` catches
  `BanditFaction`, `VeyondCaveBandits` and `ANQBanditFaction` without naming an
  NPC — 43 women in Oblivion.esm, 11 in ElsweyrAnequina.esp (2026-08-28).
* `--match-outfits` matches where she is placed: every `ACHR` pointing at the
  NPC contributes its parent cell, and the cell's EditorID/FULL plus its
  worldspace's EditorID/FULL are matched. `bruma=BRUMA_OUTFITS_TO_CHOOSE`
  therefore catches `BrumaWorld` and every `Bruma*` interior without naming a
  single cell.

Identity beats placement, so a bandit camped outside Bruma stays a bandit.

**The class is NOT part of the identity text, on purpose.** An Oblivion class is
a stat template, not an identity: matching `bandit` against `CNAM` pulled in
Anequina's 8 Dune Soldiers and 12 tribeswomen (all built on `BanditMissile`)
plus Rona, a Mephala quest NPC — 21 additions, 21 of them wrong. Faction
membership is the authored answer to "is she a bandit".

**Factions live in the MASTERS**, so `--names-from` takes every selected
converted plugin in load order — an ElsweyrAnequina NPC can sit in Oblivion.esm's
`BanditFaction`, and a source-only index would never see it. This is the
[master-blindness](../../../CLAUDE.md) trap in its patch-tool form.

### Hair — `assign_npc_hair.py`

Every NPC on a **FaceGen-head race** gets a random hair from `MALE_HAIRCUTS` or
`FEMALE_HAIRCUTS` (by the same `ACBS` female bit), plus the hair's
`<name>HL` companion part.

The head-part run is rebuilt as `[hair, hairHL, ...everything that was not
hair]`, which in practice means the eyes survive and the converted Oblivion hair
is dropped.

**The beast races are excluded** (`EXCLUDE_RACES` in `build_patch.py`, currently
`['ArgonianRace', 'KhajiitRace']`). Argonians and Khajiit wear their hair as
part of the head mesh — horns, mane, spines — so a KS Hairdo's style on one is a
human wig on a lizard. `--exclude-race` takes a RACE **EditorID** or an 8-digit
FormID, and an EditorID that resolves to no loaded RACE aborts the run rather
than silently excluding nothing.

Both converted plugins put every beast NPC on the **vanilla Skyrim** race, so
naming the two vanilla records covers every source plugin — measured 2026-08-28:
`ArgonianRace 00013740` 121 + 15, `KhajiitRace 00013745` 100 + 130 over
Oblivion.esm and ElsweyrAnequina.esp, **366 NPCs left alone**. Elsweyr's own
`TES4ANQ*` races are all creatures and never had a FaceGen head to begin with.
Those NPCs still appear in the patch — they get outfits and skin tone — they
just keep the hair the converter gave them.

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
  wrong. Excluded by adding `DremoraRace` to `EXCLUDE_RACES` in
  `tools/patch/build_patch.py`, next to the two beast races already there.
- **`_Elf` hair variants are not used.** KS ships `<name>_Elf` meshes shaped for
  elf head geometry; the passes pick whatever the constants list names, with no
  per-race variant substitution. If elf ears clip, that is the lead.
- **The HL part is added to the NPC on top of the hair's own `HNAM` extra-part
  list**, which already references it. That is what NPC-replacer mods do and it
  was explicitly requested, but it is a duplicate reference if a rendering
  oddity ever points here.
- ~~**ElsweyrAnequina.esp's own 882 NPCs get nothing.**~~ **FIXED
  2026-08-27.** `build_patch.py` runs every pass once per selected plugin, and
  `SOURCE_OUTFITS` routes Elsweyr's 215 women to `ELSW_OUTFITS_TO_CHOOSE`.
