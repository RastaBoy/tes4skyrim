# Skyrim ↔ Oblivion Creature Equivalence Map

**Close-to-exact matches only.** A row exists here only when the Skyrim race is
the *same creature* — same body plan, same locomotion class, same combat idiom —
so it could stand in for the Oblivion one without a player noticing a substitute.
Anything that would merely be "the nearest available thing" is deliberately left
**unfilled**. An empty cell is a real answer: it means Skyrim has no equivalent
and the creature must be generated (`creature_races.py`), not aliased.

Sources: `references/Skyrim.esm/RACE.txt` (84 non-vampire/child races) and every
`export/<plugin>/CREA.txt`. **Coverage: Oblivion.esm (909 CREA), Nehrim.esm
(734), Morrowind_ob.esm (307).**

> ## 🛑 The grouping key is (folder, NIFZ body-part set), NOT the folder
>
> An Oblivion mesh *folder* is far too coarse to key a swap on, and using it
> silently mismatches creatures. Measured, in the exports:
>
> | Folder | Actually contains |
> |---|---|
> | `sheep` (Nehrim) | sheep, horned **rams**, and **12 mammoth races** (`Elefant*`, `37Mammut`) |
> | `dog` | dog, wolf, **fox** (Nehrim `fox.nif`), SI skeletal/skinned hounds |
> | `rat` (Nehrim) | rats and a **rabbit** (`rabbit01.nif`) |
> | `hillgiant` (Nehrim) | 13 **giant** races, distinguished only by beard/armour parts |
> | `imp` (Nehrim) | imps, **bats**, and dragon-ish `testdragon.nif` |
>
> The body-part set (`NIFZ`) is the authored signal that separates these, and it
> is already the key `creature_races.py` uses to mint one generated RACE per
> unique `(folder, body set)`. A swap option must key on the same thing — that
> is what "based on race" means here, since **TES4 CREA records have no race
> field at all** (verified: race is a TES5 concept; a CREA carries only a model
> path plus its NIFZ part list).
>
> Race counts per plugin: **Oblivion 229, Nehrim 262, Morroblivion 94.**
> A single race covers many FormIDs, which is exactly why swapping by race
> covers "the many formids that could possibly use one race".

The table is implemented as data in
[vanilla_creature_swap.py](../tes5_import/vanilla_creature_swap.py); inspect
coverage with `tools/creature/creature_swap_report.py`. Every Skyrim.esm FormID below was
verified against the dump.

---

## 0. Intended use: a vanilla-creature swap option

**Status: reference data only. Nothing in the pipeline reads this yet.**

The table exists to back a future converter option that uses a vanilla Skyrim
creature in place of the converted Oblivion one, wherever Skyrim already ships
the same creature. The trade is "looks exactly like the Oblivion original" for
vanilla-quality animation, ragdoll, footsteps, sound and combat AI.

Notes for whoever implements it:

**A swap must replace the RACE *and* the skin ARMO — never the race alone.** A
vanilla race points ANAM/NAM3 at a vanilla skeleton and behavior project, so an
actor left on its Oblivion body mesh gets bone names that do not exist in that
skeleton and T-poses or explodes. Each entry therefore carries both FormIDs.

**Stats should be kept.** Health, level, damage, factions, inventory, AI
packages, scripts and dialogue should still come from the Oblivion CREA, so a
level-40 Oblivion boss stays a level-40 boss wearing a vanilla body. Only the
visual/animation shell is the thing being swapped.

Two tiers, because "close enough" is a judgment call:

| Tier | Meaning |
|---|---|
| `exact` | Same creature in both games. Safe default. |
| `near` | Same archetype, visibly different species (mountain lion → sabre cat). Should require an explicit opt-in. |

Measured coverage (`tools/creature/creature_swap_report.py`):

| Plugin | CREA | exact | exact+near |
|---|---|---|---|
| Oblivion.esm | 909 | 217 (24%) | 396 (44%) |
| Nehrim.esm | 734 | 227 (31%) | 425 (58%) |

```bash
python tools/creature/creature_swap_report.py -f Oblivion.esm          # exact only
python tools/creature/creature_swap_report.py -f Nehrim.esm --near
python tools/creature/creature_swap_report.py -f Oblivion.esm --list   # per record
```

**Resolution order is EditorID first, then folder** — one Oblivion folder can
hold several creatures Skyrim separates. The `dog` folder holds dog, wolf, timber
wolf *and* the SI skinned/skeletal hounds; the first two have exact Skyrim
matches, the hounds have none. An EditorID rule may also map to `None`, meaning
"always generate this one even though its folder swaps" — that is what keeps a
skinned hound from being served as a golden retriever.

Nehrim's creature EditorIDs are **German**, so the table carries German keys
(`hund`, `fuchs`, `hase`, `kuh`, `schaf`, `pferd`). Without them every Nehrim dog
and fox fell through to a generated race despite having exact Skyrim matches.

## 1. Exact matches — same creature in both games

These are the same animal/monster, drawn by both art teams. Safe to treat as
equivalent for animation donation, keyword assignment, and sound routing.

| Oblivion folder | Oblivion creature | Skyrim race | FormID | Notes |
|---|---|---|---|---|
| `bear` | Black / Brown Bear | `BearBlackRace` / `BearBrownRace` | `000131E8` / `000131E7` | Direct colour-for-colour match. `BearSnowRace` `000131E9` has no Oblivion counterpart. |
| `dog` | Dog | `DogRace` | `000131EE` | Same quadruped canine rig; Skyrim's dog is the pipeline's template creature. |
| `dog` | Wolf / Timber Wolf | `WolfRace` | `0001320A` | Oblivion shares one folder for dog+wolf; Skyrim splits them. Match is per-CREA, not per-folder. |
| `horse` | Horse (all coats) | `HorseRace` | `000131FD` | Same rig, same mount role. See [horse_rideability_plan.md](horse_rideability_plan.md). |
| `deer` | Deer Buck / Doe | `DeerRace` | `000CF89B` | `DeerRace` is the true match. `ElkRace` `000131ED` is the *antlered male* and is a closer visual fit for Buck specifically. |
| `mudcrab` | Mud Crab | `MudcrabRace` | `000BA545` | Same creature, same name, both games. |
| `slaughterfish` | Slaughterfish | `SlaughterfishRace` | `00013203` | Same creature, same name, both games. |
| `skeleton` | Skeleton | `SkeletonRace` | `000B7998` | Animated humanoid skeleton, weapon-using, in both. |
| `spriggan` | Spriggan | `SprigganRace` | `00013204` | Same creature, same name, both games. |
| `troll` | Troll | `TrollRace` | `00013205` | Same creature, same cave-brute role in both games. Models differ in detail (Skyrim's is a three-eyed ape) but this is a troll standing in for a troll. Nehrim `nightmaretroll` → `TrollFrostRace` `00013206`; both share `SkinTroll` `00016EE4`. |
| `flameatronach` | Flame Atronach | `AtronachFlameRace` | `000131F5` | Same creature, same name, both games. |
| `frostatronach` | Frost Atronach | `AtronachFrostRace` | `000131F6` | Same creature, same name, both games. |
| `stormatronach` | Storm Atronach | `AtronachStormRace` | `000131F7` | Same creature, same name, both games. |
| `willothewisp` | Will-o-the-Wisp | `WispRace` | `00013208` | Same floating-light creature. `WitchlightRace` `00013209` is the same asset family. |

## 1b. Newly found exact matches (2026-08-17 body-set audit)

These were invisible while the table keyed on folders, because the folder name
does not describe what is inside it. All are **exact** — the same creature.

| Plugin | Folder | Body set | Creature | Skyrim race | FormID |
|---|---|---|---|---|---|
| Nehrim | `sheep` (!) | `mammoth*.nif` | Mammoth (`Elefant`, `37Mammut`) | `MammothRace` | `000131FF` |
| Nehrim | `hillgiant` | `giant.nif` + beard/armour | Giant (13 races) | `GiantRace` | `000131F9` |
| Nehrim | `dog` | `fox.nif` | Fox | `FoxRace` | `00109C7C` |
| Nehrim | `rat` | `rabbit01.nif` | Rabbit/Hare | `HareRace` | `0006DC99` |
| Nehrim | `spinne` | 15 tarantula meshes | Spider | `FrostbiteSpiderRace` | `000131F8` |
| Morroblivion | `horker` | `body.nif` | Horker | `HorkerRace` | `000131FC` |
| Morroblivion | `spherecenturion` | `body.nif` | Dwarven Sphere | `DwarvenSphereRace` | `000131F2` |
| Morroblivion | `steamcenturion` | `body.nif` | Dwarven Centurion | `DwarvenCenturionRace` | `000131F1` |
| Morroblivion | `centspider` | `centurion.nif` | Dwarven Spider | `DwarvenSpiderRace` | `000131F3` |
| Morroblivion | `draugr` | `body.nif` | Draugr | `DraugrRace` | `00000D53` |
| Morroblivion | `skeleton` | `skellie.nif|skull.nif` | Skeleton | `SkeletonRace` | `000B7998` |
| Morroblivion | `spriggan` | `bmspriggan.nif` | Spriggan (Solstheim) | `SprigganRace` | `00013204` |
| Morroblivion | `icetroll` | `body.nif` | Ice Troll | `TrollFrostRace` | `00013206` |
| Morroblivion | `blondbear` | `body.nif` | Snow Bear | `BearSnowRace` | `000131E9` |
| Morroblivion | `a_bear` | `bearbody`/`blackbearbody` | Bear | `BearBrownRace` / `BearBlackRace` | `000131E7` / `000131E8` |
| Morroblivion | `redwolf` / `dog` | `body.nif` / `wolfbody.nif` | Wolf | `WolfRace` | `0001320A` |
| Morroblivion | `mudcrab` | mudcrab parts | Mud Crab | `MudcrabRace` | `000BA545` |
| Morroblivion | `slaughterfish` | `slaughterfish.nif` | Slaughterfish | `SlaughterfishRace` | `00013203` |
| Morroblivion | `flameatronach` / `frostatronach` / `stormatronach` | atronach meshes | Atronachs | `AtronachFlame/Frost/StormRace` | `000131F5`/`F6`/`F7` |

**Requires Dragonborn** (FormIDs NOT yet verified — no dump available; must be
read from the user's installed ESM before use):

**✅ VERIFIED 2026-08-18** — every FormID below was read out of the real plugin
with `python tools/creature/creature_race_resolve.py`. The low 24 bits are stable; the
load-order byte is assigned at runtime, and **ESL-flagged plugins live in the
`0xFE___xxx` space** (flagged per row), which changes how the reference is written.

| Plugin | Folder | Creature | DLC race | FormID | Confidence |
|---|---|---|---|---|---|
| Morroblivion | `iceminion` | Riekling | `DLC2RieklingRace` | `0x02017F44` | **exact** — UESP confirms the Morrowind Riekling is what Dragonborn reintroduces |
| Morroblivion | `iceraider` | Mounted Riekling | `DLC2MountedRieklingRace` | `0x020179CF` | **exact** — Dragonborn ships a dedicated mounted race, so the rider variant is covered properly |
| Morroblivion | `boar` | Tusked Bristleback (`0FrostBoar`) | `DLC2BoarRace` | `0x02024038` | **exact** — same creature, same name |
| Oblivion / Nehrim | `boar` | Boar / Wildschwein | `DLC2BoarRace` | `0x02024038` | **exact** — a bristleback is a "large tusked boar" (UESP); same rig |
| Morroblivion | `bullnetch` | Bull Netch | `DLC2NetchRace` | `0x0201FEB8` | **exact** |
| Morroblivion | `bettynetch` | Betty Netch | — | — | ❌ **Dragonborn has NO betty race.** It ships `DLC2NetchRace` and `DLC2NetchCalfRace` `0x02028580` (a calf, not a betty). Under the strict rule the betty stays generated. |
| Morroblivion | `frostgiant` (Karstaag) | Frost Giant | `DLC2GhostFrostGiantRace` | `0x0201CAD8` | ⚠ **ghost** variant only — Karstaag's spectral form. A living frost giant race does not exist; leave generated unless the ghost look is wanted. |

**Corrections this verification forced:**

- **Dawnguard has no frost giant.** The `Skyrim:Creatures` "Frost Giant" is
  Dragonborn's `DLC2GhostFrostGiantRace`. The earlier "check the Dawnguard dump"
  follow-up is closed: there is nothing there.
- **There is no betty netch race.** An earlier note said "Dragonborn has both
  (`DLC2NetchRace` vs a betty variant)" — wrong. The second netch race is a
  *calf*. Bull swaps; betty does not.
- **`DLC2MountedRieklingRace` exists**, so the `iceraider` row is no longer a
  caveat about a rider with no mount.

### Creation Club tier — ✅ VERIFIED 2026-08-18

Read from the real files with `tools/creature/creature_race_resolve.py`. Every id the repo
already had in `skyrim_overrides.py` is **confirmed correct**.

⚠ **Three of these are ESL-flagged**, so at runtime their records live in the
`0xFE___xxx` space and only the low 12 bits are addressable — a swap ESP must
write the reference accordingly, not with the raw id shown here.

| Source plugin | ESL? | Creature | Race | FormID | Covers |
|---|---|---|---|---|---|
| `ccbgssse040-advobgobs.esl` | **yes** | Goblin | `ccBGSSSE040_GoblinRace` | `0x05000800` | **goblin 122** (Obl 95, Neh 20, Morro 7) |
| `ccbgssse025-advdsgs.esm` | no | Elytra | `ccBGSSSE025_ElytraRace` | `0x05000A76` | **elytra 35** — no other source has it |
| `ccbgssse025-advdsgs.esm` | no | Golden Saint | `ccBGSSSE025_GoldenSaintRace` | `0x05000816` | SI golden saints — no other source |
| `ccbgssse025-advdsgs.esm` | no | Dark Seducer | `ccBGSSSE025_DarkSeducerRace` | `0x05000817` | SI dark seducers — no other source |
| `ccbgssse003-zombies.esl` | **yes** | Zombie | `ccBGSSSE003ZombieRace` | `0x05000D6B` | zombie ~120 — a true zombie, unlike `near`-tier `DraugrRace` |
| `ccbgssse036-petbwolf.esl` | **yes** | Bone Wolf | `ccBGSSSE036_BoneWolfCompanionRace` | `0x01002F93` | Morroblivion `undeadwolf` |
| `ccbgssse067-daedinv.esm` | no | Wight | `ccBGSSSE067_WightRace` | `0x051DB955` | ⚠ **not an Ayleid Lich.** The Cause ships only a *Wight* race — see below |

**Correction:** an earlier row claimed `ccbgssse067-daedinv.esm` provides an
"Ayleid Lich". The file contains exactly **one** RACE, `ccBGSSSE067_WightRace`.
The Ayleid Lich the UESP page describes is an *actor* using another race, not a
race of its own. **Beyond Skyrim has the real one** (`BSKAyleidLichRace`), so the
lich row belongs to that tier instead.

Also found: `ccBGSSSE025_ElytraRace_PET` `0x05000A52` and
`ccBGSSSE040_GoblinRaceDuplicate` `0x05000807` — variants that exist but are not
what the swap wants.

### Beyond Skyrim tier — ✅ VERIFIED 2026-08-18

`BSAssets.esm` (30 races) + `BSHeartland.esm` (23 races), read with
`tools/creature/creature_race_resolve.py`. **Every id the repo already had is confirmed
correct**, and the read turned up considerably more than was recorded.

This is the **single best source** for this project: BS: Cyrodiil is a deliberate
recreation of *Cyrodiil's* creatures in the Skyrim engine — the same animals our
plugins ship. Neither file is ESL-flagged, so ids are used as-is with the
load-order byte.

| Source | Creature | Race | FormID | Covers |
|---|---|---|---|---|
| `BSAssets.esm` | Goblin | `BSKGoblinRace` | `0x01602681` | **goblin 122** + `wuestegoblin` 6 |
| `BSAssets.esm` | Scamp | `BSKScampRace` | `0x01601FA8` | **scamp 34** |
| `BSAssets.esm` | Ogre | `BSKOgreRace` | `0x01601FBD` | **ogre 27** (also plain `OgreRace` `0x016026BE`) |
| `BSAssets.esm` | Imp | `BSKImpRace` | `0x0160299D` | **imp 22** (strict rule: Nehrim's bats stay generated) |
| `BSAssets.esm` | Minotaur | `CYRMinotaurRace` | `0x016026EA` | **minotaur 38** (lord: `CYRMinotaurLordRace` `0x016026DB`) |
| `BSAssets.esm` | **Ayleid Lich** | `BSKAyleidLichRace` | `0x01602708` | **lich 17** — the real one; CC's "Ayleid Lich" is a Wight |
| `BSAssets.esm` | Boar | `BSKBoarRace` | `0x01602432` | boar 13 — a **Cyrodiil** boar, better than `DLC2BoarRace` and no DLC needed |
| `BSAssets.esm` | Rat | `BSKRatRace` | `0x01602430` | **rat 36** — a real rat, where vanilla only offers `near`-tier Skeever |
| `BSAssets.esm` | Zombie | `BSKZombieRace` | `0x01602431` | zombie ~120 — no CC needed |
| `BSHeartland.esm` | Daedroth | `CYRDaedraDaedrothRace` | `0x020ADFB0` | **daedroth 20** |
| `BSHeartland.esm` | **Sheep** | `CYRSheepRaceDomestic` | `0x020AEB19` | **sheep** — a real sheep, not a goat (wild: `CYRSheepWildRace` `0x020AEB1E`) |
| `BSHeartland.esm` | **Ram** | `CYRRamRaceDomestic` | `0x020AEB2F` | **ram** — settles the ram question: BS has one (wild: `CYRRamWildRace` `0x020AEB32`) |
| `BSHeartland.esm` | Mountain Lion | `CYRMountainLionRace` | `0x020D51B7` | **mountainlion 18** — a real mountain lion, not a sabre cat |
| `BSHeartland.esm` | Horse | `CYRHorseRace` | `0x020AE5AF` | horse 85 — Cyrodiil horses |
| `BSHeartland.esm` | Dog | `CYRColovianDogRace` | `0x020AD6B0` | dog — plus Nibenese variants BLK/BWN/YEL `0x020AEB2B/27/24` |
| `BSHeartland.esm` | Wolf | `CYRWolfRace` | `0x02003C82` | wolf |
| `BSHeartland.esm` | Bear | `CYRBearBrownRace` | `0x020D5665` | bear |
| `BSHeartland.esm` | Mudcrab | `CYRMudcrabRace` | `0x020D6C70` | mudcrab |
| `BSHeartland.esm` | Troll | `CYRTrollRiverRace` | `0x0208BB68` | troll 39 (savage: `CYRTrollSavageRace` `0x0208BB67`) |
| `BSHeartland.esm` | Skeleton | `CYRSkeletonRace` | `0x0205BC32` | skeleton 110 — *alternative*; `SkeletonRace` is already exact + dependency-free |
| `BSHeartland.esm` | Will-o-the-Wisp | `CYRWillotheWispRace` | `0x0207822E` | wisp 15 — *alternative* to `WispRace` |

**What this changes:**

1. **The ram exists after all.** `CYRRamRaceDomestic` is a genuine ram race, so
   Nehrim's `Schafbock`/`Widder` records have a true match — and so does a
   *sheep* (`CYRSheepRaceDomestic`), which vanilla never had. The earlier
   "no ram anywhere, sheep→goat is only `near`" conclusion holds for vanilla but
   **not** with Beyond Skyrim installed.
2. **Rat and mountain lion get promoted.** Both were stuck at `near` against
   Skeever/SabreCat; `BSKRatRace` and `CYRMountainLionRace` are exact.
3. **The lich moves tiers** — Beyond Skyrim has the Ayleid Lich, CC does not.
4. **Boar needs no DLC** — `BSKBoarRace` covers it without Dragonborn.

**Priority when several tiers offer one creature: Beyond Skyrim → Skyrim.esm →
CC/DLC.** Exception: where vanilla genuinely has the creature (skeleton, wisp,
horse, dog, wolf, bear, mudcrab), the verified dependency-free Skyrim.esm race
stays the default and the `CYR*` version is an alternative.

### ⚠ Corrections — rows removed after review (2026-08-17)

An earlier draft of this section was **wrong**, built from folder-name
similarity rather than from the meshes or the lore. Recorded here so the same
mistake is not made again:

| Wrongly claimed | Why it is wrong |
|---|---|
| `ashghoul`/`ashslave`/`ashvampire`/`ashzombie` → one "Ash Spawn" row | These are **four different creatures**, each with its own skeleton (`SixthHouse\AshGhoul`, `\AshSlave`, `\AshVampire`, `\AshZombie`). They are Sixth House **corprus** beasts of the Third Era; Skyrim's Ash Spawn are Fourth-Era constructs of volcanic ash raised by a necromancer after the Red Year (UESP). Different creature, different lore, no match. Add Ascended Sleeper to the same family — also distinct. |
| `bullnetch` + `bettynetch` → one "Netch" row | **Two different creatures.** Separate skeletons and different part meshes (`jelly.nif` vs `netchjelly.nif`); UESP: the betty is smaller and more aggressive, the bull larger — they even ship separate images. Dragonborn has both (`DLC2NetchRace` vs a betty variant), so if used they need **two** rows, not one. |
| `udrfrykte`, `frostgiant` → `TrollFrostRace` | Udyrfrykte and Karstaag are **unique named bosses**, not a generic troll race. Left generated. **Follow-up (2026-08-18):** `Skyrim:Creatures` lists a **Frost Giant** added by *Dawnguard* (Forgotten Vale). Karstaag is a frost giant in lore, so `frostgiant` may have a real Dawnguard match — needs the Dawnguard dump to confirm the race and check whether it is a generic race or a unique actor. |

## 1c. Deliberately NOT matched (looks close, is not)

| Oblivion/Nehrim | Tempting match | Why rejected |
|---|---|---|
| `sheep` (plain, `sheep.nif`) | `GoatRace` | **A sheep is not a goat.** Different species, different silhouette and horns. Near tier only. |
| `sheep` **ram** (`ramhornl/r.nif`) | `GoatRace` | **A ram is not a goat either** — and it is not the same as a sheep, so it cannot share the sheep row. Horned male sheep; Skyrim has no ram. Near tier at best. |
| `rat` | `SkeeverRace` | Skeever is a *different animal* filling the same niche. Near, not exact. |
| `spiderdaedra` | `FrostbiteSpiderRace` | Only the spider half matches; the Dark Elf torso has no counterpart. |
| `boar` (Oblivion/Nehrim) | `GoatRace` | Skyrim.esm has no boar — but **Dragonborn's `DLC2BoarRace` is an exact match**, now listed in §1b. |
| `imp` bats (Nehrim `bat.nif`) | — | Skyrim has no bat creature. |
| Morroblivion `bonewalker` / `greaterbonewalker` | `SkeletonRace` | A bonewalker is a **rotting corpse revenant** (UESP), not an animated bare skeleton. Closer to a draugr, but not that either. |
| Morroblivion `lich` / `lichmw` | `DragonPriestRace` | A Morrowind lich is not a masked Nordic dragon priest. Different creature, different silhouette. |
| Morroblivion `ashghoul`/`ashslave`/`ashvampire`/`ashzombie` | Ash Spawn | Four separate Sixth House corprus creatures; Skyrim's Ash Spawn are unrelated 4th-Era ash constructs. See §1b corrections. |
| Morroblivion `bullnetch` + `bettynetch` | one Netch row | Two different creatures with different meshes and sizes. |
| Morroblivion `udrfrykte`, `frostgiant` | `TrollFrostRace` | Udyrfrykte and Karstaag are unique named bosses. |
| Morroblivion `ascendedsleeper` | any undead race | Half-Dunmer half-beast Sixth House abomination; nothing comparable. |

### ⚠ The "ram" was never a creature (correction, 2026-08-18)

Recorded because it is the same class of mistake as the folder-name errors:

- All four Oblivion "ram" records (`CreatureSheepRam`, `SakeepaSheepRam`,
  `UurasSheepRam`, `WeynonPriorySheepRam`) have **FULL = "Sheep"**. Oblivion has
  no ram creature, which is why UESP has no ram page.
- `ramhornl.nif`/`ramhornr.nif` are decoration, and are worn by **goblins**
  (`CGGoblinThiefShaman`, `GoblinTribeLeaderA`–`G`) as headgear — so the part
  name says nothing about the species.
- **Nehrim is the exception:** it names real rams (`01SchafBock` = "Schafbock",
  `01SchafSchwarzBock` = "Schwarzer Schafbock", `28TollwuetigerWidder` =
  "Widder"). There the variant is authored in the FULL NAME.

**Lesson: read the FULL name, not the mesh parts, to decide whether a variant is
a distinct creature.** A part list tells you how something is decorated; the
authored name tells you what it is.

### 🛑 Method note — how the bad rows got in

Every wrong row above came from reading a **folder name** and matching on the
word, rather than checking the mesh or the lore. Two specific traps:

1. **Generic body-mesh names are not identity.** `body.nif` is used by **20
   different Morroblivion folders** (alit, cliffracer, draugr, dreugh,
   frostgiant, horker, kagouti, riekling, …) and `mesh.nif` by 11. A body set of
   `body.nif` tells you nothing at all.
2. **The full skeleton path is the identity**, not the folder leaf and not the
   body set: `Creatures\Horker\skeleton.nif` vs
   `Morroblivion\Creatures\SixthHouse\AshGhoul\skeleton.nif`. Paths also vary
   in case (`Skellie.NIF` vs `skellie.nif`), so compare case-insensitively or
   identical creatures split into two races.

**Rule: a row is only allowed once the creature has been confirmed from the mesh
path AND from UESP** (`python tools/misc/uesp_lookup.py --page "Morrowind:<X>"`).
Folder-name resemblance is not evidence.


## 2. Near-exact — same archetype, different species

Usable as animation/sound donors; **not** interchangeable on screen.

| Oblivion folder | Oblivion creature | Skyrim race | FormID | Why it is not exact |
|---|---|---|---|---|
| `mountainlion` | Mountain Lion | `SabreCatRace` | `00013200` | Same big-cat quadruped rig and pounce idiom; Skyrim's has sabre tusks and is larger. |
| `sheep` (`sheep.nif`) | Sheep | `GoatRace` `000131FA` / `GoatDomesticsRace` `0006FC4A` | — | Skyrim has no sheep. Same livestock size/gait, different species. |
| `sheep` + `ramhornl/r.nif` (Nehrim only) | **Ram** (`Schafbock`) | `GoatRace` | `000131FA` | **Nehrim only.** Oblivion's "ram" records are FULL="Sheep" — there is no Oblivion ram (see the correction note below). Nehrim authored real rams by NAME (`Schafbock`, `Widder`), and vanilla has no ram either way. |
| `rat` | Rat | `SkeeverRace` | `00013201` | Skeever fills the rat niche but is a different, larger animal. |
| `spiderdaedra` | Spider Daedra | `FrostbiteSpiderRace` | `000131F8` | Spider half only; no counterpart for the Dark Elf torso. |
| `ox` / `calf` (Nehrim) | Ox / Calf | `CowRace` | `0004E785` | Cow-class draft animals; Skyrim has only the adult cow. |
| `mrsiikasdonkey` (Nehrim) | Donkey | `HorseRace` | `000131FD` | Donkey on the horse rig; visibly smaller in the original. |
| `pig` (Nehrim) | Pig | — | — | No Skyrim pig. Listed to record that it was considered. |
| `boar` | Boar | — | — | Skyrim has no boar. Nearest quadruped is `GoatRace`; too different to list as a match. |
| `zombie` | Zombie | `DraugrRace` | `00000D53` | Both shambling undead humanoids using a humanoid rig. Draugr are armed, armoured and weapon-using; Oblivion zombies are unarmed maulers. |
| `ghost` | Ghost | `WispShadeRace` | `000F1182` | Both translucent floating humanoid spirits. Skyrim's is a wisp-mother thrall, not a generic ghost. |
| `wraith` | Wraith | `IceWraithRace` | `000131FE` | **Name only.** Skyrim's Ice Wraith is a serpentine ice creature, not a humanoid spectre. Listed because the pipeline's fallback uses it — it is a poor match. |
| `imp` | Imp | — | — | Skyrim has no small flying daedra. No honest match. |
| `minotaur` | Minotaur | — | — | Nearest is `GiantRace`/`TrollRace` by size only; neither is bovine-headed. |
| `ogre` | Ogre | `GiantRace` | `000131F9` | Both large humanoid brutes with club-style melee. Giants are much taller and non-hostile by default. |

## 3. No equivalent in *Skyrim.esm* — generated, unless an optional tier covers it

Skyrim.esm ships nothing close to these. **Many are now covered by the optional
Beyond Skyrim / Creation Club / DLC tiers above** — the ✅ column says which. Rows
with no mark are generated by the pipeline in every configuration.

| Creature | Covered by |
|---|---|
| goblin (122) | ✅ Beyond Skyrim `BSKGoblinRace`, or CC `ccbgssse040` |
| minotaur (38) | ✅ Beyond Skyrim `CYRMinotaurRace` |
| scamp (34) | ✅ Beyond Skyrim `BSKScampRace` |
| ogre (27) | ✅ Beyond Skyrim `BSKOgreRace` |
| imp (22) | ✅ Beyond Skyrim `BSKImpRace` |
| daedroth (20) | ✅ Beyond Skyrim `CYRDaedraDaedrothRace` |
| elytra (35) | ✅ CC `ccbgssse025` |
| zombie (~120) | ✅ CC `ccbgssse003` (a true zombie, unlike `DraugrRace`) |
| lich (17) | ✅ CC `ccbgssse067` Ayleid Lich |
| Golden Saint / Dark Seducer | ✅ CC `ccbgssse025` |
| Morroblivion `undeadwolf` | ✅ CC `ccbgssse036` Bone Wolf |
| boar (13) | ✅ Dragonborn `DLC2BoarRace` |
| riekling | ✅ Dragonborn `DLC2RieklingRace` |
| **grummite (113)** | ❌ nothing, anywhere |
| **gnarl (48)** | ❌ nothing (Beyond Skyrim may have one — unconfirmed) |
| **clannfear, xivilai, land dreugh, spider daedra** | ❌ not confirmed in any source |
| **gatekeeper, Jyggalag, hunger, shambles, baliwog, murkdweller** | ❌ Shivering Isles uniques |
| **Nehrim originals** (fleshgolem, ghoul, swampstalker, thornelemental, firedemon, reaper, lichking, ivellon-lich, spiderspriggan) | ❌ original creations |

The list below is the original Skyrim.esm-only analysis, kept for reference.

**Oblivion / Shivering Isles**

| Folder | Creature | Nearest thing in Skyrim (still not a match) |
|---|---|---|
| `clannfear` | Clannfear | — (`DremoraRace` is a humanoid; Clannfear is a raptor) |
| `daedroth` | Daedroth | — (crocodilian biped; nothing comparable) |
| `scamp` | Scamp | — |
| `xivilai` | Xivilai | `DremoraRace` `000131F0` is humanoid daedra but a different creature |
| `landdreugh` | Land Dreugh | — |
| `goblin` | Goblin | `FalmerRace` `000131F4` — small hunched humanoid tribals, different species |
| `lich` | Lich | `DragonPriestRace` `000131EF` — robed undead spellcaster, different lore/model |
| `mehrunesdagon` | Mehrunes Dagon | — (unique boss) |
| `gatekeeper` | Gatekeeper | — (unique SI boss) |
| `jyggylag` | Jyggalag | — (unique SI boss) |
| `grummite` | Grummite | — |
| `gnarl` | Gnarl | — (`SprigganRace` is plant-based but a different creature) |
| `baliwog` | Baliwog | — |
| `elytra` | Elytra | — |
| `hunger` | Hunger | — |
| `shambles` | Shambles | — |
| `murkdweller` | Scalon / Murk Dweller | — |
| `fleshatronach` | Flesh Atronach | — (Skyrim has no flesh atronach) |

**Nehrim-only folders** (no Skyrim equivalent unless noted)

`butcher`, `firedemon`, `fleshgolem`, `ghoul`, `hillgiant` (→ `GiantRace`
`000131F9` is a genuine near-match), `ivellon-lich`, `lichking`, `reaper`,
`spiderspriggan`, `swampstalker`, `thornelemental`, `nightmaretroll` (→
`TrollRace`/`TrollFrostRace` near-match), `wuestegoblin`/`goblin1` (goblin
variants), and the livestock set `calf`, `chicken` (→ `ChickenRace` `000A919D`,
exact), `cow` (→ `CowRace` `0004E785`, exact), `ox` (→ `CowRace`, near),
`pig`, `mrsiikasdonkey` (→ `HorseRace` `000131FD`, near). `spinne` (spider) →
`FrostbiteSpiderRace` `000131F8`, exact-class match.

## 4. Skyrim races with no Oblivion source

Listed so nothing tries to map *into* them. Every one is a Skyrim-original
creature: `DragonRace`, `AlduinRace`, `UndeadDragonRace`, `MammothRace`,
`HorkerRace`, `HagravenRace`, `ChaurusRace`, `ChaurusReaperRace`,
`DwarvenCenturionRace`, `DwarvenSphereRace`, `DwarvenSpiderRace`,
`WerewolfBeastRace`, `FoxRace`, `HareRace`, `BearSnowRace`,
`SabreCatSnowyRace`, `SkeeverWhiteRace`, `TrollFrostRace`, `FalmerRace`,
`DragonPriestRace`, `GiantRace`, `ElkRace`, `WhiteStagRace`.

---

## Reading this against the code

`skyrim_overrides.CREA_RACE_PATTERNS` is a **keyword fallback** used only for
creatures with no converted project. Several of its rows are not real matches by
the standard of this document and are marked as such in-table above — notably
`wraith → IceWraithRace`, `clannfear → DremoraRace`, `scalon → ChaurusRace`,
and `grummite → FalmerRace`. They are acceptable as last-resort fallbacks
(something must be written) but should not be read as equivalences, and any
creature reaching them is a creature whose project failed to convert.

---

## 5. The patch-side proposal table (2026-08-27)

`patch_folder/sources/creature_changes.py` is a second, narrower table built for
the hand-authored patch: **Oblivion.esm + ElsweyrAnequina.esp only**, and
restricted to the Skyrim plugins actually installed on this machine
(Skyrim.esm, Dawnguard, Dragonborn, `ccbgssse025-advdsgs.esm` / Saints &
Seducers). Beyond Skyrim and the other CC packs are NOT installed, so the rows
this document credits to `BSKGoblinRace`, `CYRMinotaurRace`, `BSKScampRace`
etc. are unavailable there and fall back to `near` tier. It also carries the
mount/horse layer this document has no data for. Run
`python patch_folder/sources/creature_changes.py` for the full report, and
`python tools/creature/creature_patch_census.py -f <plugin>` to find creatures
the table does not cover yet.

**Implemented 2026-08-27.** The table is no longer reference-only:
`tools/patch/assign_creatures.py` applies it, and `tools/patch/build_patch.py`
(the GUI's **Patches** section) ships it as `MyOwnTamrielCreaturePatch.esp` and
`MyOwnTamrielHorsePatch.esp`. Mounts are a separate plugin. Measured over
Oblivion.esm + ElsweyrAnequina.esp: **955 creature swaps, 26 removals** (30
placed refs disabled, 15 leveled lists rewritten) and **70 mounts**.

**Decisions taken 2026-08-27** (settled, not proposals — rows in the table carry
a `DECIDED` note): alfiq **removed outright** rather than substituted; the 25
Elsweyr fish, the 16 elephants and the 10 Oblivion xivilai **left converted**;
camels become horses in a coat drawn deterministically from the source FormID;
Slarjei become dogs; goblins (95) and grummites (113) become rieklings.
Resulting coverage — Oblivion.esm: exact 264 records / near 582 / keep 68.
ElsweyrAnequina.esp: exact 52 / near 127 / keep 49 / remove 27.

### 🛑 A race swap must carry the whole vanilla AI SHELL, not just race + skin

**In-game, 2026-08-27.** The first build swapped `RNAM`/`WNAM`/`ATKR`/`VTCK`.
Result: horses became rideable and **wolves behaved correctly, while spiders and
everything else stood still and did nothing.**

Cause, measured in the converted plugins: the converter stamps **`csWolf` on
almost every creature** — 646 of 914 in Oblivion.esm and 245 of 255 in
ElsweyrAnequina.esp, the remainder `DefaultCombatstyle`. It also gives them all
`EncClassAnimalPredator` and `DefaultMasterPackageListCreature`. That is the
correct vanilla combination for exactly one creature: the wolf. On a wolf body
it works, which is why wolves were the one thing that behaved; on a spider, a
giant or a skeleton it is a combat style the body cannot perform, and the actor
never engages.

So the shell a swap has to move is bigger than "race + skin":

| Field | Taken from |
|---|---|
| `RNAM` | the vanilla race |
| `WNAM` | the skin the vanilla ACTORS of that race wear — **and nothing at all where they carry none** |
| `ATKR` | the race |
| `VTCK` | the race's voice type |
| `ZNAM` | the race's combat style |
| `CNAM` | the race's class |
| `DPLT` | the race's default package list |
| `DOFT` | the race's default outfit, where it has one |

Each is a **majority vote over every vanilla `NPC_` pointing at that race**,
published only above a 60% majority so a split vote leaves the converted value
alone; the vote is recorded per row in `creature_changes.py` (`votes`). Stats,
level, factions, inventory, packages, scripts and dialogue stay the Oblivion
record's own.

Two things this fixed that were silently wrong:

- **`DOFT` is part of a creature's kit.** Every vanilla frostbite spider (10/10)
  carries `SpiderSpitOutfit` — the spit attack is an equipped item, so a spider
  without it has no ranged attack at all.
- **The race's own `WNAM` is not always usable.** `DLC1DeathHoundRace` points at
  `SkinDog`, whose ARMA does **not** list that race, so a death hound wearing it
  has no body; its actors wear `DLC1SkinVampireWolf` instead. Most creature
  actors (the frostbite spider, the elytra) carry **no** `WNAM` and inherit the
  race's — writing one anyway is how the elytra got a skin no ARMA maps to it.
  Rule: write what the actors write, including nothing.

### 🛑 The swap CLONES the vanilla actor; only size, name and scripts are kept

**Second in-game round, 2026-08-27.** With the full AI shell (above) the goblins
started behaving and **the spiders still stood still and would not attack.**

Measured: a converted spider carries **one** Oblivion faction where a vanilla
frostbite spider has **three**, plus converted paralysis lesser-powers and an
Oblivion inventory. A creature in no hostile faction has nobody to attack. Field
by field there was always going to be another one of these, so the default
became a **wholesale clone of the vanilla donor actor**, keeping only:

| Kept from the converted record | Why |
|---|---|
| `EDID` / `FULL` / `SHRT` | identity and the Oblivion name — no behavioural cost |
| `NAM6` / `NAM7` | the size, kept by request |
| `VMAD` | converter-attached scripts (171 creatures have one); dropping one silently breaks quest logic |

The donor is the most **typical** vanilla actor of the race — the one agreeing
with the majority vote on the most fields, tie-broken towards an `Enc*`
EditorID (`EncFrostbiteSpider`, `EncWolf`, `EncGiant03`, `DLC2EncRiekling01Melee`
…). It is recorded per race in `creature_changes.py` so it can be argued with.

**Verified:** all 955 cloned records are byte-identical to their donor outside
the keep-list, across 33 races; sizes survive (595 at 1.0, the rest spread
0.9–2.0).

**What it costs, deliberately:** 798 creatures lose their Oblivion abilities,
904 their Oblivion loot, 1,168 their Oblivion factions, and levels become the
vanilla creature's. That is what "identical to the vanilla one" means; the
shell-only behaviour is still available as `--no-clone`, and the **horse patch
stays on it**, because horses already worked and there was no reason to hand
them vanilla stats too.

### A removal has three layers, not one

Measured for the alfiq with `creature_patch_census.py --group mountainlion/alfiq
--refs`: **27** base CREA records, **30** placed `ACRE` references, and **41**
entries across **15** `LVLC` leveled lists. Deleting only the base records is
the failure mode — the placed refs and list entries become null. Worth
recording: despite individual names (J'Shani, Z'lil, K'vigi, Skooma Cat, Alfiq
Guard) **no alfiq is referenced by any INFO, QUST or PACK record**; the single
non-placement dependency in the whole plugin is the script `ANQSummonsAlfiqBrown`,
which does `player.PlaceAtMe ANQCreatureAlfiqBrownSummon` for a summonable pet.

Findings that also belong here:

### The authored mount flag is `CREA DATA.Type == 4`, and the importer drops it

TES4 CREA carries a creature type (0 Creature, 1 Daedra, 2 Undead, 3 Humanoid,
**4 Horse**, 5 Giant). Measured: **Oblivion.esm sets type 4 on 51 records**,
**ElsweyrAnequina.esp on 26** (horses, zebras, elephants, camels and one
running bird). `grep -rn "DATA.Type" tes5_import/*.py` finds **no reader** —
the flag is discarded, which is why every converted mount is an ordinary
walking actor.

### RACE Mount Data is a CK default, not the mountability switch

All **99** Skyrim.esm races — dog, cow, wolf, sabre cat included — carry
byte-identical mount data: mount offset `(-63.479, 0, 0)`, dismount
`(-50, 0, 65)`, camera `(0, -300, 0)`. `creature_races.py`'s DogRace template
already emits exactly those bytes, so adding "mount data" to a generated race
changes nothing. This corrects step 2 of
[horse_rideability_plan.md](horse_rideability_plan.md), which treats the struct
as the data-only half of the fix.

### What a vanilla mount actor actually carries

Read off `WhiterunPlayerHorse 00109E3D`, `EncHorseSaddledBrown 00023AB2` and
`HorseForCarriageNew 00072A08`:

| Field | Value |
|---|---|
| `RNAM` | `HorseRace 000131FD` (carriage: `CartHorseRace 000DE505`) |
| `WNAM` | the coat skin ARMO |
| `ATKR` | `000131FD` |
| `KWDA` | `ActorTypeHorse 00026110` — **on the NPC_, not on the RACE** |
| `VTCK` | `CrHorseVoice 0001F232` |
| `CNAM` | `EncClassHorse 0010F71E` |
| `DOFT` | `HorseSaddleOutfit 00060798` when saddled; `HorseHarnessOutfit01 000C236E` for cart horses; absent for wild |
| `ACBS.Flags` | `0x00040018` |

Coats (Oblivion body NIF is the authored indicator, and it agrees with the FULL
name in all 55 records):

| Oblivion body mesh | Skyrim skin | Vanilla actor |
|---|---|---|
| `horse.nif` (bay) | `SkinHorse 00060715` | `EncHorseBrown` |
| `horseblack.nif` | `SkinHorseBlackHide 0008650D` | `EncHorseBlack` |
| `horsepaint.nif` | `SkinHorseBlacknWhiteHide 00086510` | `EncHorseBlackAndWhite` |
| `horsegrey.nif` (white) | `SkinHorseGreyHide 0008650F` | `EncHorseGrey` |
| `horsechestnut.nif` | `SkinHorsePalominoHide 0008650E` | `EncHorsePalomino` |

`Dark10Horse` (Shadowmere) has a true counterpart: Skyrim ships **Shadowmere
`0009CCD7`** with `SkinHorseShadowmere 00086503`. `DAHircineUnicorn` does not —
grey coat is the right base, the horn has no vanilla source.

### Correction: Will-o-the-Wisp is `WitchlightRace`, not `WispRace`

`WispRace 00013208` is the **Wispmother**, a humanoid caster.
`WitchlightRace 00013209` is the small floating drain-light, which is what an
Oblivion Will-o-the-Wisp is. `vanilla_creature_swap.BY_FOLDER['willothewisp']`
still points at `WispRace` — unchanged, because nothing reads that module, but
noted so the next pass does not "fix" the new table to match the old one.

### ElsweyrAnequina folder traps (same class as §1c)

The plugin reuses Oblivion folder names for unrelated animals. Measured from
`export/ElsweyrAnequina.esp/CREA.txt`:

| Folder | Actually contains |
|---|---|
| `goblin` | **monkeys and a Tenmar Ape** (`anequinaape*.nif`) — no goblins at all |
| `sheep` | 4 sheep and **10 goats** (`anequinagoat*.nif`) — an exact `GoatRace` match Oblivion.esm never had |
| `deer` | White Stag, a desert antelope (`anequinaaddax.nif`) and a **skeletal shark** |
| `rat` | rats and a **glyptodon** |
| `mountainlion` | lion, leopard, panther, senche-tiger, spore cat and **27 house-cat-sized alfiq** |
| `anequinaragasha` | built entirely from Warhammer **skaven** meshes (ratmen), despite two records named "Desert Goblin" |
| `dog` | red wolves and **10 durzogs** (hairless reptilian war-dogs) |
| `clannfear` | one "Nequinal Lizard" |
