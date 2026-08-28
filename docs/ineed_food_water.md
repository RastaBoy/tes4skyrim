# iNeed: how it works, and what the converted world needs to join it

Read from the plugins and from **iNeed's own Papyrus sources**, which ship
inside `iNeed.bsa` — all 27 `.psc` files, not just the compiled `.pex`. Nothing
here was inferred from behaviour.

Inputs: `patch_folder/sources/iNeed/` — `iNeed.esp` (551 records, isoku,
"iNeed 1.95 for SE") and `iNeed - Extended.esp` (4,408 records, masters
`iNeed.esp`). Extract the scripts with
`asset_convert.bsa_extract.list_bsa_files` + `read_bsa_files`.

The item classification table lives in
[patch_folder/sources/food_changes.py](../patch_folder/sources/food_changes.py);
run it for the report.

---

## The three needs

`_SNQuestScript` holds `HungerState`, `ThirstState`, `FatigueState` as floats
0–110. The tick is `RegisterForSingleUpdateGameTime(0.95)` — roughly hourly —
plus real-time 185 s / 305 s passes. Decay per game hour comes from globals the
MCM edits: hunger **12.5**, thirst **14.0**, fatigue **5.0**.

Bands, for hunger; thirst and fatigue mirror them:

| State | Effect |
|---|---|
| ≥ 105 | "sated" buff, `_SNHungerBuffSpell` |
| 85–105 | neutral |
| 50–85 | level 0 |
| ≤ 50 | level 1, notification |
| 0 | level 2; the penalty then escalates with **time spent at zero** — < 14 h penalty 1, < 39 h penalty 2, beyond that penalty 3 plus a wellness loss |

Penalties are applied as spells (`_SNHungerPenaltySpell_1/2/3`); the 87 MGEF and
24 PERK records are their effects.

## Food: lists, not rules

The working lists — `_SNFood_HeavyList`, `_MedList`, `_LightList`, `_RawList`,
`_SoupList`, `_DrinkList`, `_DrinkNoAlcList`, `_BloodList` — **ship empty**.
They are filled at runtime:

1. `FillFormList()` copies in the `_SNFood_Initial_*` lists — 83 vanilla items
   hand-classified in the ESP;
2. `_SNDLCQuestScript.psc`, **76 KB of hand-written compatibility table**, does
   `Game.GetFormFromFile(0xID, "Plugin.esp")` + `AddForm` per item for ~25 known
   food mods (CACO, Hunterborn, Wild Loot, Requiem, Falskaar, Wyrmstooth,
   Nordic Cooking, CC Fishing, CC Survival — and **Beyond Skyrim: Bruma**).

> ### 🛑 There is no classifier
> No keyword scan, no value or weight heuristic. iNeed's only three keywords —
> `_SNThirstServing`, `_SNThirstServing_Unknown`, `_SNRefillable` — are about
> water containers, not food. **An item in neither the initial lists nor the
> hardcoded table is unknown to iNeed**, and eating it does nothing.

The fallback is manual: the `_SNUnknownAllToggle` global turns on `Categorize()`
in `_SNPlayerAlias`, which asks the player through a message box to file the item
as Heavy/Med/Soup/Light/Raw, Drink/NoAlc/Blood, or Ignore. The answer is
`AddForm`ed into the runtime list and lives in the save.

`_SNFood_IgnoreList` is therefore not a bin — putting an item there is what stops
that prompt firing for it.

### What each tier is worth

`SetNeedsChange(hunger, thirst, fatigue, followerEat)` in `_SNPlayerAlias.psc`:

| Tier | Hunger | Thirst | Fatigue |
|---|---|---|---|
| Heavy | 50 | — | 0.5 |
| Soup | 45 | 25 | 0.25 |
| Med | 40 | — | 0.25 |
| Light | 25 | 0–1 | 0.1 |
| Drink (alcohol) | 0–7 | 45 | 0.25 |
| DrinkNoAlc | 0–3 | 50 | 0.25 |
| Snow | −10 | 25 | 0.25 |
| Raw | 15–40 random, cannibals only; harmful otherwise |

A ±2.5 jitter and the food-spoilage freshness multiplier are applied on top.

### It already accepts ingredients

```papyrus
Event OnObjectEquipped(Form akBaseObject, ObjectReference akReference)
    If _SNQuest.EnableMod && (akBaseObject as Potion || akBaseObject as Ingredient)
```

This matters more than anything else here for us. **Oblivion has no food item
type — every edible is an `INGR`** (173 of them; only 18 `ALCH` carry the
authored food flag, and all 18 are alcohol). Had iNeed keyed on potions alone,
the patch would have needed a category conversion. It does not.

## Water, sleep, and the rest

**Water.** The waterskin is an `ALCH` with three fill levels plus an empty
`MiscObject` and a salt-water variant. Refilling runs through
`_SNActivatePerks`, a perk whose activate-entry-point fragments
(`_snperkrefill.psc`) sit on water bodies, wells, snowdrifts and rain
containers. The rain path spawns a detector and casts a shelter-check spell
upward before allowing a refill.

**Sleep.** Vanilla `PlayerSleepQuest` (`000FC1A2`) is overridden; the
`_SNNeeds` magic effect on the player hooks `OnSleepStart` / `OnSleepStop`.
Sleep quality is decided by `FindClosestReferenceOfAnyTypeInListFromRef(...,
512.0)` against `_SNBedRollList` (66), `_SNTentList` (13), `_SNFireList` (40)
and `_SNHabitationList` (32).

**Also present:** per-inventory-slot food spoilage; eight diseases with their own
cure potions and priest dialogue (`_SNPriestList`, 17); follower needs including
followers buying their own food; horse feeding (25 items); vampire and werewolf
branches; a 59 KB SkyUI MCM; a HUD widget.

**`iNeed - Extended.esp`** is almost entirely world dressing: **1,783 references
placing six snowdrift statics across 784 cells**, so snow can be collected for
water, plus 105 food tweaks and 32 cooking recipes.

## The patch (built 2026-08-27)

`tools/patch/build_patch.py --patch ineed` → `MyOwnTamrieliNeedPatch.esp`, also
the **iNeed (food & water)** button in the GUI's Patches section. Two halves,
neither of which needs a script:

1. **Override the eight food FLSTs**, adding our items as BASE entries. Better
   than the `AddForm` route every other food mod uses: `_SNDLCQuestScript` calls
   `FormList.Revert()` on all eight when it re-seeds, and Revert drops
   runtime-added forms while keeping the ones the plugins define.
2. **Append the vanilla job factions** to converted vendors, which is the whole
   of the water feature — iNeed's topics attach themselves.

Measured on Oblivion.esm: 5 lists written (drink 21, heavy 3, med 12, light 26,
ignore 132 — the ignore list keeps iNeed's own 11 entries and appends ours), and
145 NPC_ overrides of which **37 publicans** get `JobInnkeeperFaction` +
`JobMerchantFaction` and 108 merchants get `JobMerchantFaction`. Verified: no
actor lost a faction the conversion gave it.

## What the converted world needs

Measured on `export/Oblivion.esm`:

| | |
|---|---|
| ALCH | 253, of which **18** carry the authored food flag — all alcohol |
| INGR | 173 records / 163 distinct names |
| Non-alcoholic drink | **none at all** — no water, milk, juice or tea anywhere in the plugin |

So the food half is a straightforward `AddForm` job over ~190 records, and
`food_changes.py` is the proposed mapping (38 food names → 41 records, 20 drink
names → 21 records, 125 names → the ignore list).

The **thirst half is not**. There is nothing in Cyrodiil to drink but alcohol,
which iNeed barely counts as hydration. Thirst has to come from iNeed's own
water sources, and whether its `_SNActivatePerks` fragments reach converted
Cyrodiil water — rivers, wells, fountains — is **unverified and should be tested
in game before that half is designed**.

> ### The trap to avoid
> `INGR ENIT.Flags` in the export dump is the item's **gold value**, not a flag
> word (Poisoned Apple 300, Daedra Heart 25). There is no food flag on TES4
> ingredients, and neither mesh nor icon paths separate food from reagents — all
> 173 icons are under `Clutter\`, and an apple and nightshade are both
> `Ingred*.NIF`. Any classification of the INGR half is a judgement call, which
> is why the table is meant to be read rather than trusted.

## The vendor base stock (added 2026-08-28)

Every converted merchant carries a tavern-style base set: **one food list, one
drink list, and two full iNeed waterskins**. The shape is vanilla's, read off
`ServicesNightGateInn`, whose chest is exactly `SaltPile` +
`LItemFoodInnCommon` + `LItemInnRuralDrink` + `VendorGoldInn`. Ours substitutes
the plugin's own larder: `TES4iNeedVendorFood` (41 Oblivion ingredients) and
`TES4iNeedVendorDrink` (18 wines, ales and meads), both `chanceNone 0` and
`flags 3` -- Calculate from all levels + Calculate for each item in count --
so the container resolves an entry every time it restocks.

Three things all have to be true, and each was a separate defect on the way:

1. **The stock has to sit where the engine looks.** That is the vendor
   faction's `VENC` container when it has one, and the actor's own inventory
   when it does not. Measured: **99 chest-backed merchants (50 distinct
   chests), 121 selling from inventory.** Both are vanilla-legal --
   `CurrentFollowerFaction` and `WEServicesHunterFaction` are chest-less vendor
   factions too, which is how hunters sell pelts.

2. **The vendor faction's `VEND` list has to ADMIT the items.** That list is a
   FILTER, not a source: a weapons vendor whose list holds only
   `VendorItemWeapon/Armor/Arrow` shows none of this however it got into the
   stock. Converted food is `INGR` (`VendorItemIngredient`) and converted drink
   is `ALCH` (`VendorItemFood`), so both keywords are appended to every
   `TES4VendorList_<mask>` a merchant actually resolves -- **21 lists**.

3. **An item the filter cannot admit is dead weight.** 3 of Oblivion's 21
   drinks (Cyrodilic Brandy, Rosethorn Mead, Shadowbanish Wine) are `ALCH`
   without the food flag, so they carry `VendorItemPotion`; they are left out
   of the vendor list rather than rescued, because adding `VendorItemPotion` to
   every vendor list would hand every merchant the whole potion catalogue.
   They stay in iNeed's `_SNFood_DrinkList` -- what EATING them does has
   nothing to do with whether a shop may stock them.

iNeed's full waterskin `_SNWaterskin_3` already carries `VendorItemFood`, which
is why the whole set rides on one added keyword pair.

**Anequina shares Cyrodiil's larder.** `food_changes.py` does not cover
ElsweyrAnequina yet, so one food list and one drink list are built for the
WHOLE patch rather than per plugin -- otherwise Anequina's 75 merchants would
stock water and nothing else. Cyrodiil is next door; when the table grows to
cover Anequina's own food, the lists pick it up with no code change.

Verified end to end on the built patch: 220 merchants, **0 missing part of the
base stock, 0 whose VEND list blocks any of it**, all 50 chest overrides
byte-identical to the source outside the appended `CNTO` run, and a re-run
byte-identical to the first.

## The patch conflict that hid all of it (2026-08-28)

The first build of the vendor stock reached the game and merchants still had
nothing. The cause was not in the stock at all: **`MyOwnTamrielCosmeticPatch.esp`
and `MyOwnTamrieliNeedPatch.esp` override the same 220 NPC_ records** -- every
merchant is also somebody the cosmetic patch restyled -- and two plugins that
override one record do not merge. The later one wins the WHOLE record.

Measured on the two built ESPs: 220 shared `NPC_`, and the cosmetic patch's
copy carries 4 `SNAM` and 4 `CNTO` where the iNeed copy carries 6 and 7. So
whichever loaded second erased the other's work on all 220 -- the factions and
the base stock with the load order as shipped, or every outfit, hair and
skin-tone change the other way round.

The fix is `--overlay`: the iNeed patch copies the shared record from the LAST
override rather than from the converted master, and MASTERS the patch it copied
from, which is what makes the load order put that patch first. **Confirmed in
game the same day: merchants stock the food, the drink and the waterskins.** `SourceStack` in
`patch_builder.py` does the lookup; `STACK_ON` in `build_patch.py` declares the
order. An overlay that contributes nothing is not mastered.

> **Consequence: the iNeed patch must be rebuilt after the cosmetic patch.**
> It loads last and wins, so a stale copy of a shared actor is what the game
> uses. The GUI builds one patch per button and cannot know the order, so this
> is on whoever presses them.

The same trap is waiting for any future pair of patches that share a record.
The creature and horse patches are already passed as overlays and today
contribute nothing -- measured 0 shared records with either.
