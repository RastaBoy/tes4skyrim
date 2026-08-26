# Data census

Measured 2026-08-27 against `output/Oblivion.esm/Oblivion.esm` (615 MB,
1,184,918 records) and the `patch_folder/sources/` plugins. Re-measure after a
new conversion run; these numbers describe a specific build.

---

## The source plugin

3,838 `NPC_` · 35,494 `CELL` · 11,668 `ACHR` · 84 `WRLD` · 223 `RACE` ·
814 `HDPT` · 2,463 `OTFT` · 57 `REGN`. None of the `NPC_` records are
compressed.

`NPC_` subrecord census (occurrences): CNTO 10,708 · SNAM 9,839 · PKID 8,930 ·
SPLO 5,067 · PNAM 4,855 · EDID/OBND/ACBS/RNAM/AIDT/CNAM/DATA/DNAM/NAM5/NAM6/
NAM7/NAM8 3,838 each · VTCK/DPLT 3,396 · FULL 3,354 · COCT 2,972 · QNAM 2,924 ·
HCLF/NAM9/NAMA/TINI/TINC/TINV/TIAS 2,482 · **DOFT 2,463** · SPCT 1,782 ·
ZNAM 1,365 · CSDT/CSDI/CSDC 909 · **VMAD 460** · TPLT 442 · INAM 209.

---

## Gender and templates

- **778 female** NPCs (`ACBS` flags bit 0).
- Resolving gender through `TPLT` + `Use Traits` changes nothing — **no** female
  NPC uses a template, so no `Use Inventory` inheritance can defeat a `DOFT`.
- 30 of the 778 had no `DOFT` and needed one inserted.

## Races

Only **11** races carry the FaceGen-head flag, and they are all vanilla Skyrim
records (`00xxxxxx`); all 223 TES4-converted races are creature races.

| Race | NPCs | | Race | NPCs |
|---|---|---|---|---|
| ImperialRace `00013744` | 834 | | ArgonianRace `00013740` | 121 |
| HighElfRace `00013743` | 296 | | **DremoraRace `000131F0`** | 115 |
| BretonRace `00013741` | 290 | | OrcRace `00013747` | 109 |
| DarkElfRace `00013742` | 277 | | KhajiitRace `00013745` | 100 |
| NordRace `00013746` | 180 | | | |
| WoodElfRace `00013749` | 139 | | **total** | **2,597** |
| RedguardRace `00013748` | 136 | | of them female | 778 |

The 1,241 remaining NPCs sit on creature races. **A "race comes from
Skyrim.esm" test is not enough** — it also admits `WispRace` (5),
`SkeletonRace` (4) and `DraugrRace` (1), which is exactly why the FaceGen flag
is the criterion.

All 778 female NPCs are on a FaceGen race, so the outfit set and the hair set
overlap perfectly on the female side.

## Head parts, before the patch

Every NPC that has any has **exactly two**: the converted Oblivion hair
(`01xxxxxx`, type Hair) and a vanilla Skyrim eye part (`00xxxxxx`).

- 2,482 NPCs have head parts; 2,373 of those have a hair.
- 115 selected NPCs have **no** head parts at all — they get a fresh `PNAM` run.
- Only **12 distinct** vanilla head parts are referenced, and every one is in
  `tes5_import/skyrim_overrides.py`'s `_SKY_EYE_BY_COLOR` table — i.e. all
  eyes, no vanilla hair anywhere. Verified rather than assumed, because "leave
  the non-hair parts alone" depends on it.

## Placement

7,433 distinct (NPC, cell) placements from 11,668 `ACHR`. 187 of the 778 female
NPCs are placed in no cell at all and fall through to the default outfit list.

**Bruma** = 124 cells: 57 in `BrumaWorld` (`0101C318`) plus 82 matched by name
(`Bruma*` interiors), overlapping. The 56 cells tagged with
`BrumaWeatherRegion` (`010CA47B`) are a strict subset of those, so adding a
region test changes nothing — 21 female NPCs either way.

---

## KS Hairdo's.esp

2,701 `HDPT`, masters `Skyrim.esm` + `Update.esm` (so its own index is `02`,
remapped to `04` in the patch).

| type | flags | count | what |
|---|---|---|---|
| Hair (3) | `0x05` Playable+Female | 1,160 | female hairstyles |
| Hair (3) | `0x03` Playable+Male | 192 | male hairstyles |
| Misc (0) | `0x0D` Playable+Female+Extra | 1,152 | female hairlines |
| Misc (0) | `0x0B` Playable+Male+Extra | 197 | male hairlines |

962 hairs have a matching `<name>HL` (857 female, 105 male). The 390 without are
mostly `_Elf` variants, which share the base style's hairline.

Curated lists in `patch_folder/sources/constants.py`:
`MALE_HAIRCUTS` = 0TheTruth, 0Theo, 0Victor, 0RedRobin ·
`FEMALE_HAIRCUTS` = 0Leona, 0Lenore, 0Laurell, 0Lamb, 0Koala.

---

## The patch, as built

| | original | after outfits | after hair |
|---|---|---|---|
| bytes | 3,228 | 514,995 | 1,700,360 |
| records | 26 | 804 | 2,623 |
| groups | 26 | 27 | 27 |
| HEDR | 52 | 831 | 2,650 |
| `NPC_` | 0 | 778 | 2,597 |

Unchanged throughout: 15 `OTFT`, 10 `CELL`, 1 `WRLD` — byte-identical to the
source patch.

Master indexes referenced by the final `NPC_` records: `03` 38,862 ·
`00` 8,484 · `04` 5,194 (= 2,597 × 2, hair + HL) · `06` 778 (the outfits).

`ElsweyrAnequina.esp` defines 882 of its own NPCs and overrides **zero**
Oblivion.esm NPCs, so the patch conflicts with nothing there.
