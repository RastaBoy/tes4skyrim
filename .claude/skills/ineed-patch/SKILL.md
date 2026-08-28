---
name: ineed-patch
description: >-
  Build and extend MyOwnTamrieliNeedPatch.esp — the patch that makes the
  converted Oblivion world legible to the iNeed hunger/thirst/sleep mod, by
  registering its food and drink in iNeed's FormLists and by putting converted
  innkeepers and merchants into the vanilla job factions iNeed's water dialogue
  checks. Covers how iNeed actually works (no food classifier at all; empty
  lists filled at runtime from seeds plus a 76 KB hand-written per-mod table),
  why the patch overrides FormLists instead of calling AddForm, the exact
  faction gating behind the "refill my waterskin" and "sell me water" options,
  the authored signals used to identify edibles and innkeepers, the measured
  coverage, and the recipe for adding another plugin or re-categorising an item.
  Use when food or drink in the converted game does nothing for hunger, when the
  innkeeper water options are missing, when adding a new plugin's food to the
  patch, or when working on iNeed integration generally.
---

# The iNeed patch

Makes the converted world work with **iNeed** (isoku, 1.95 SE — hunger, thirst,
fatigue). Built and shipping; **merchant stock confirmed in game 2026-08-28**
(after the cosmetic-patch conflict below was fixed).

```bash
python tools/patch/build_patch.py --patch ineed --plugins Oblivion.esm
python tools/patch/assign_ineed.py --plugins Oblivion.esm --dry-run --report r.tsv
```

Also the **iNeed (food & water)** button in the GUI's Patches section. Output:
`patch_folder/output/MyOwnTamrieliNeedPatch.esp`, zipped to
`output/Finished Mods/`.

| Piece | Where |
|---|---|
| The item → category table | `patch_folder/sources/food_changes.py` (run it for a report) |
| The pass | `tools/patch/assign_ineed.py` |
| How iNeed works, in full | [docs/ineed_food_water.md](../../../docs/ineed_food_water.md) |
| iNeed itself | `patch_folder/sources/iNeed/` — and it ships its 27 Papyrus **sources** inside `iNeed.bsa` |

Read iNeed's own scripts rather than guessing:
`asset_convert.bsa_extract.list_bsa_files` + `read_bsa_files`.

---

## The two things that make this patch possible

### 1. iNeed has NO food classifier

No keyword scan, no value or weight heuristic. Its three keywords are about
water containers. It looks every item up in one of eight FormLists that **ship
empty** and are filled at runtime from `_SNFood_Initial_*` (83 vanilla items)
plus `_SNDLCQuestScript.psc` — **76 KB of hand-written
`Game.GetFormFromFile(0xID, "Plugin.esp")` + `AddForm`** for ~25 known food
mods. Anything in neither is invisible: eating it does nothing.

> **So the patch OVERRIDES those FormLists**, adding our items as BASE entries —
> it does not call `AddForm`. That is not a style preference. `_SNDLCQuestScript`
> calls `FormList.Revert()` on all eight lists whenever it re-seeds, and
> `Revert()` drops runtime-added forms while keeping the ones the plugins
> define. **Script-added entries can be reverted away; ours cannot.**

`_SNFood_IgnoreList` is not a dumping ground — an item on it never raises
iNeed's "what is this?" prompt, so filing Oblivion's ~130 alchemy reagents there
is what stops the player being asked to categorise nightshade.

### 2. The water options are pure faction gating

Read out of the INFO conditions; no dialogue is authored by this patch, iNeed's
own topics attach themselves once the factions are right:

| Topic | Condition | Effect |
|---|---|---|
| `_SNInnRefillTopic` | `JobInnkeeperFaction` **or** `JobInnServer`, + >5 gold, + a refillable skin | refills every skin, 5 gold each |
| `_SNTravelerRefillTopic` | `JobMerchantFaction`, + an EMPTY waterskin, + 50 gold | the merchant shares their own water |

Vanilla FormIDs: `JobInnkeeperFaction 0005091B`, `JobInnServer 000DEE93`,
`JobMerchantFaction 00051596`. Converted vendors are in none of them, which is
the whole reason the options are missing.

The patch **appends** these — verified that no actor loses a faction the
conversion gave it.

---

## The vendor base stock

The shops that sell food carry a tavern-style set -- food list, drink list,
two full waterskins for an inn -- shaped like vanilla's `ServicesNightGateInn`
chest. Four rules, all of them measured:

* **WHO gets it is authored.** Class `MerchPublican` = inn (food + drink +
  skins); `AIDT.Services` bit 4 = food/general shop (food + drink); everyone
  else nothing. A blacksmith has no business selling bread.
* **Stock goes where the engine looks**: the vendor faction's `VENC` container
  or the actor's inventory when the faction has none. Chest-less vendor
  factions are vanilla -- that is how hunters and followers trade.
* **`VEND` is a FILTER, not a source**, and service bit 4 is the answer to it:
  `tes5_import` maps that bit to `VendorItemIngredient` + `FoodRaw` + `Food`,
  so every shop entitled to the stock already admits it and NO keyword widening
  is needed. An earlier revision appended the keywords to all 21
  `TES4VendorList_<mask>` lists and handed every smith the larder -- do not go
  back to it.
* **Anything the filter cannot admit is left OUT of the vendor list** -- 3 of
  21 drinks carry `VendorItemPotion` instead. They stay in iNeed's own
  `_SNFood_DrinkList`: what eating them does is a different question from
  whether a shop may stock them.

Every vendor faction is also given a `PLVD` Vendor Location, unconditionally.
A vendor faction without one sells NOTHING -- the barter menu opens empty.

One food list and one drink list serve the WHOLE patch, not one pair per
plugin, so a plugin `food_changes.py` does not cover yet (Anequina) stocks
Cyrodiil's larder instead of water alone.

## 🛑 It shares 220 NPCs with the cosmetic patch

`MyOwnTamrielCosmeticPatch.esp` overrides **every one of these merchants** --
measured 220 shared `NPC_` records. Two plugins that override one record do not
merge: **the later one wins the WHOLE record.** The first build copied the
merchants off the converted master, so whichever patch loaded second erased the
other's work on all 220 -- with the shipped load order, every faction and every
item of stock this patch writes. That is the reason merchants still had nothing
after the stock was added.

The fix is `--overlay`, which `build_patch.py` passes automatically from
`STACK_ON`: the shared record is copied from the LAST override instead of from
the master, and that patch becomes a **master** of this one, so the load order
can never put it second. An overlay that contributes no record is not mastered
(mastering an unused file makes the patch refuse to load without it).

> **Rebuild this patch after the cosmetic patch, every time.** It loads last
> and wins, so a stale copy of a shared actor is what the game uses. The GUI
> builds one patch per button and cannot know the order.

`SourceStack` in `patch_builder.py` is the lookup, and it is general -- any
future pair of patches sharing a record needs the same treatment.

## The authored signals

Never classify by name where the data says it:

| Question | Authored answer |
|---|---|
| Is this NPC an innkeeper? | class **`MerchPublican`** ("Publican") — 37 in Oblivion.esm, all also vendors |
| Is this NPC a merchant? | `AIDT.Services` buy/sell bits (mask `0x3FFF`; bit 14 is training) — 145 in Oblivion.esm |
| Is this ALCH a drink? | `ENIT.Flags` bit `0x02`, the food flag — exactly 18, all alcohol |
| Is this INGR food? | **nothing says.** See the trap below |

Vanilla innkeepers (Hulda, Orgnar, Valga Vinicia, Corpulus Vinius) carry BOTH
`JobInnkeeperFaction` and `JobMerchantFaction`, so publicans get both.

> ### 🛑 The trap: INGR has no food flag
> The export's `INGR ENIT.Flags` column is the item's **gold value**, not a flag
> word (Poisoned Apple 300, Daedra Heart 25). Mesh and icon paths do not separate
> food from reagents either — all 173 icons live under `Clutter\`, and an apple
> and nightshade are both `Ingred*.NIF`. **In TES4 every edible is an ingredient
> and nothing marks which ones are meals**, so the INGR half of
> `food_changes.py` is a judgement call that wants reading, not trusting.
>
> Good news that removes the other half of the problem: iNeed's
> `OnObjectEquipped` accepts `Potion` **or** `Ingredient`, so no category
> conversion is needed.

---

## Measured coverage (Oblivion.esm, 2026-08-27)

```
253 ALCH (18 authored food, all alcohol) · 173 INGR / 163 distinct names
  drink  21    heavy   3    med  12    light  26    ignore 132
   37 publicans -> JobInnkeeperFaction + JobMerchantFaction
  108 merchants -> JobMerchantFaction
```

The ignore list keeps iNeed's own 11 entries and appends ours. Ship gate: all
5,649 untouched subrecords byte-identical to the source.

**There is no non-alcoholic drink anywhere in Oblivion.esm** — no water, milk,
juice or tea. Thirst therefore cannot come from Oblivion items at all.

---

## Recipes

### Add another plugin's food
1. Add its names to `OBLIVION_DRINKS` / `OBLIVION_FOOD` in `food_changes.py`.
2. **Add the plugin to `COVERED_PLUGINS`.** Until it is there the pass leaves
   that plugin alone entirely and says so — deliberately, so an uncovered
   plugin's ingredients are not swept into the ignore list and its drinks are
   not silently dropped.
3. Rebuild; the report prints per-category counts.

ElsweyrAnequina.esp is the outstanding one: 13 ALCH (9 authored food — Shein,
Flin, Greef, Sujamma, Mazte, Riverhold Plum Brandy…) plus its own ingredients.
Its vendors are already covered, because the vendor signals are authored and
work for any plugin.

### Re-categorise an item
Edit the name's value in `OBLIVION_FOOD`. The key is the **FULL name**, not the
EditorID — 173 records carry 163 names, and same-named records always want the
same category. Tiers are worth: heavy 50 hunger, med 40, light 25, soup 45+25
thirst, drink 45 thirst, drink-no-alcohol 50 thirst.

### Decisions already argued, do not silently reverse
- **Meat is `med`, not `raw`.** iNeed's raw tier is harmful and cannibals-only;
  Oblivion draws no cooked/raw distinction, so making meat raw invents a danger
  the original never had. Candidates are listed in `RAW_CANDIDATES`.
- **Nothing is `soup`** — Oblivion has no soup.
- Poisoned Apple, Rat Poison, Dog Food, Felldew and Greenmote are food-shaped
  and deliberately excluded; the reasons are in `DELIBERATELY_NOT_FOOD`.
- `Alocasia Fruit` and `Ironwood Nut` are genuinely borderline and listed in
  `BORDERLINE` rather than decided.

---

## Unverified — check before building on it

1. **Merchant stock is confirmed** (2026-08-28, after the overlay fix). Still
   untested: the innkeeper refill option, the merchant water option, and
   whether eating bread actually moves the hunger bar.
2. **Whether iNeed's water sources reach Cyrodiil at all.** Its refill runs
   through `_SNActivatePerks`, whose activate-entry-point fragments sit on
   *vanilla Skyrim* water activators, wells and rain containers. Converted
   Oblivion water may be entirely different records. If it does not reach, that
   is separate work — but the two paid sources (innkeeper, merchant) do not
   depend on it.
