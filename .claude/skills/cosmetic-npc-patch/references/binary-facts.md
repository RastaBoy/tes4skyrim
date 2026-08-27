# Measured TES5 binary facts

Everything here was **measured** while building `tools/patch/plugin_patch.py`
(2026-08-27), against the converted `Oblivion.esm`, the real
`Skyrim.esm`, `KS Hairdo's.esp`, `Apachii_DivineEleganceStore.esm`,
`ElsweyrAnequina.esp` and `MyCosmeticTamrielPatch.esp`. Do not re-derive; if you
change one of these, re-measure and update the number here.

Also mirrored into `docs/record_mapping_reference.md` (memory is per-machine, a
doc is the only copy another computer sees).

---

## File structure

| Thing | Size |
|---|---|
| Record header | 24 bytes: sig(4) dataSize(4) flags(4) formID(4) timestamp+VC(4) formVersion(2) v2(2) |
| GRUP header | 24 bytes: `GRUP`(4) size(4) label(4) groupType(i4) stamp(8) |
| Subrecord header | 6 bytes: sig(4) size(u2) |
| Compressed flag | `0x00040000` on the record's flags word |

GRUP `size` **includes** its own 24-byte header. Record `dataSize` does **not**.

### HEDR "number of records"

**= every record OUTSIDE the file header + every GRUP, nested groups included.**

Exact on four independent plugins:

| Plugin | HEDR | records + groups |
|---|---|---|
| MyCosmeticTamrielPatch.esp (original) | 52 | 52 |
| Apachii_DivineEleganceStore.esm | 4,498 | 4,498 |
| KS Hairdo's.esp | 2,702 | 2,702 |
| ElsweyrAnequina.esp | 182,404 | 182,404 |

### Top-level GRUP order

The xEdit/CK canonical list, held in `GROUP_ORDER` in `plugin_patch.py`. The
load-bearing part for this patch:

```
... WEAP AMMO NPC_ LVLN KEYM ... LVLI ... REGN NAVI CELL WRLD DIAL QUST
IDLE PACK ... ARMA ECZN LCTN MESG ... SCEN ASTP OTFT ARTO ...
```

`NPC_` before `CELL`; `OTFT` near the end. Apachii's ESM
(`TXST FACT HDPT MGEF ENCH ARMO CONT DOOR LIGH MISC STAT MSTT FURN WEAP AMMO
NPC_ COBJ PROJ LVLI NAVI CELL WRLD PACK ARMA LCTN OTFT`) matches it exactly, and
so does this patch's original `CELL WRLD OTFT`.

### Group types

`0` top-level (label = signature) · `1` world children (label = WRLD FormID) ·
`2/3` interior block/sub-block · `4/5` exterior block/sub-block ·
`6` cell children (label = CELL FormID) · `7` topic children ·
`8/9/10` cell persistent / temporary / visible-distant children (label = CELL).

Only `1` sets the parent worldspace; only `6/8/9/10` set the parent cell.
Restore both when a group ends, or a CELL following a cell-children group
inherits the wrong parent (`tools/tes5_esm_reader.py` has exactly that bug).

---

## NPC_

### Where FormIDs live

Full map in `NPC_FORMID_FIELDS` / `NPC_PLAIN_FIELDS`. One FormID at offset 0 of
each stride:

- **stride 4** — TPLT RNAM VTCK CNAM DOFT SOFT DPLT HCLF ZNAM INAM PKID SPLO
  PNAM CSDI WNAM ANAM ATKR CRIF FTST GNAM ECOR DEFA CSCR SPOR OCOR GWOR KWDA
- **stride 8** — CNTO (item + count), SNAM (faction + rank), PRKR (perk + rank)
- **structured** — VMAD (walk it, see below)
- **no FormID** — EDID OBND ACBS AIDT DATA DNAM FULL SHRT NAM5 NAM6 NAM7 NAM8
  NAM9 NAMA COCT SPCT PRKZ QNAM TINI TINC TINV TIAS CSDT CSDC KSIZ ATKD ATKE

Traps: `QNAM` is 12 bytes of texture-lighting RGB floats, **not** a FormID
despite the name. `NAM9` is 76 bytes of face-morph floats, `NAMA` 16 bytes of
face-part indices.

### Canonical field order

```
EDID VMAD OBND ACBS SNAM(x) INAM VTCK TPLT RNAM SPCT/SPLO WNAM ANAM ATKR
ATKD/ATKE SPOR OCOR GWOR ECOR PRKZ/PRKR COCT/CNTO AIDT PKID KSIZ/KWDA CNAM
FULL SHRT DATA DNAM PNAM(x) HCLF ZNAM GNAM NAM5 NAM6 NAM7 NAM8
CSDT/CSDI/CSDC CSCR DOFT SOFT DPLT CRIF FTST QNAM NAM9 NAMA TINI/TINC/TINV/TIAS
```

Three positions this patch depends on, all verified:

- **`DOFT` comes AFTER the sound block (`CSDT/CSDI/CSDC`, `CSCR`), not straight
  after `NAM8`.** Vanilla Skyrim.esm never has both `DOFT` and `CSDT` on one
  record, so the ordering had to come from the sound-block records
  (`... DNAM NAM5 NAM6 NAM7 NAM8 CSDT CSDI CSDC QNAM`, 31 records) plus the
  `... NAM8 CSCR DOFT DPLT QNAM` pattern (121 records).
  Reconstructing the position from the rule reproduces the real index in **all
  2,463** converted NPC_ records that already carry a `DOFT`.
- **`PNAM` sits immediately after `DNAM`** — true in all 2,597 records the hair
  pass rewrites.
- **`QNAM` sits between `FTST` and `NAM9`**, i.e. after the outfit/faction block
  and before the face-morph block.

`insert_run()` implements this as "put the run where the first existing one was;
failing that, immediately before the first successor field; failing that, at the
end", which is why it needs the `AFTER_DOFT` / `AFTER_PNAM` / `AFTER_QNAM`
successor tuples.

### ACBS

24 bytes. `flags` u32 at 0 (**bit 0 = Female**), magicka/stamina offsets i16 at
4/6, level u16 at 8, calcMin/Max u16 at 10/12, speedMult u16 at 14, disposition
i16 at 16, **templateFlags u16 at 18**, healthOffset i32 at 20.

Template flags: `0x0001` Traits, `0x0002` Stats, `0x0004` Factions,
`0x0008` Spell List, `0x0010` AI Data, `0x0020` AI Packages, `0x0040`
Model/Animation, `0x0080` Base Data, `0x0100` **Inventory**, `0x0200` Script,
`0x0400` Def Pack List, `0x0800` Attack Data, `0x1000` Keywords.

If `Use Traits` is set the gender comes from the template, and if `Use
Inventory` is set the outfit does — resolve the chain before trusting either.
(In this data it never matters: **zero** female NPCs in the converted
Oblivion.esm use a template.)

### VMAD

In the converted plugin: **version 5, object format 2**, Object properties only,
no fragments (only QUST/INFO/PACK/SCEN carry those). A full walk consumes every
one of the 460 blobs exactly, so FormID remapping inside VMAD is exact.

```
i16 version, i16 objFormat, u16 scriptCount
  script:  wstring name, u8 flags (only when version >= 4), u16 propertyCount
    prop:  wstring name, u8 type, u8 status, value
```

Types: 1 Object, 2 wstring, 3 i32, 4 f32, 5 bool(1 byte), 11-15 = array of
(type-10) preceded by a u32 count. Object layout depends on `objFormat`:
`1` = `formID u32, alias i16, unused u16`; `2` = `unused u16, alias i16,
formID u32`.

`tools/vmad_probe.py`'s parser handles neither arrays nor `objFormat 1` — use
`plugin_patch.vmad_formid_offsets()`.

---

## QNAM and the skin-tone tint layer

`QNAM` (texture lighting, 3 floats) and the skin-tone tint layer
(`TINI`/`TINC`/`TINV`/`TIAS`) are the same colour written twice. When they
disagree the face is lit differently from the body. Vanilla derives one from the
other:

```
QNAM_channel = floor(127 * (1 - TINV/100) + TINC_channel * TINV/100) / 255
```

Measured over Skyrim.esm's 5,118 NPC_ records:

- all **15,354** vanilla QNAM channel values are exactly `N/255` for integer N;
- the base **127** is pinned by the 9 NPCs whose layer has `TINV=0` — their QNAM
  is `127/255` whatever colour the layer holds;
- `floor` reproduces **3,142 / 3,213** channels exactly, 65 more within 1/255;
- **995 / 1,071** vanilla NPCs write `TINV=100`, where the base cancels out —
  so anything tested only at TINV=100 cannot see a wrong base.

Implemented once, in `tes5_import.npc_face_mapper.skin_tone_qnam()`.

## RACE

`DATA` is 164 bytes (form version 44) in both Skyrim.esm (all 99 races) and the
converted plugin (all 223).

**Flags word is at offset 32.** Bit `0x01` Playable, **bit `0x02` FaceGen
Head**, bit `0x04` Child.

*FaceGen Head* is the engine's own "this actor wears head parts" marker and is
the correct humanoid-vs-creature test:

| set | clear |
|---|---|
| the 10 playable races, DremoraRace, ElderRace, DefaultRace, all `*Vampire` and `*Child` variants, ManakinRace, InvisibleRace, DA13AfflictedRace (33 of 99) | SkeletonRace, DraugrRace, WispRace, WolfRace, HorseRace, ChaurusRace, DragonRace … (66 of 99) |

All **223** TES4-converted races have it clear, so no creature converted from
Oblivion can ever pass the test.

Offset 96 is *Stamina Regen* — reading flags there yields plausible-looking
garbage like `0x40800000` (= 4.0). Check that a "flags" value is not a float.

---

## HDPT

- `PNAM` = part type: `0` Misc, `1` Face, `2` Eyes, `3` **Hair**, `4` Facial
  Hair, `5` Scar, `6` Eyebrows.
- `DATA` = 1 byte of flags: `0x01` Playable, `0x02` **Male**, `0x04` **Female**,
  `0x08` **Is Extra Part**.
- `HNAM` = extra parts (repeatable FormID), `RNAM` = valid-races FLST.

KS Hairdo's ships each hair as type 3 with the matching gender bit, and its
hairline as `<name>HL`, type 0 + `Is Extra Part`, listed in the hair's `HNAM`
alongside a shared `0_HAIRLINE_*` part.

---

## Compressed records

Third-party plugins compress freely (Apachii's NPC_, this patch's own CELL
records). `iter_records()` inflates them and clears the flag, because anything
rewritten is emitted uncompressed. Groups that are carried through untouched
keep their original bytes, compression included.
