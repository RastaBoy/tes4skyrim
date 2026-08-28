---
name: house-upgrade-fix
description: >-
  Diagnosis and the fix for converted Oblivion house upgrades that cannot be
  bought: the house itself sells fine, but the furnishing receipts never appear
  in the merchant's barter menu. Covers Oblivion's receipt/container/quest-script
  model for player-house furnishing, what converts correctly, the exact reason it
  dies in Skyrim (barter reads ONLY the vendor faction's VENC container, so an
  owned container is never merchandise), the measured scope across all seven
  cities plus Sinderion's skill-gated stock in MS39, and the implemented
  script_convert rule: SetOwnership on a vendor's CONT also MOVES the stock into
  his VENC chest, and the poll SWEEPS it afterwards, because the hand-over branch
  latches in the save and the destination chest respawns. Also covers the three
  traps behind that (a new script property cannot be filled by --scripts-only and
  RemoveAllItems(None) destroys the stock; a container cannot be enumerated
  without SKSE, so the authored CNTO list is carried into the script; the TES4
  item count's SIGN is the restock rule), why an ESP patch is the wrong vehicle,
  and the loose-script `--patch house` package as the delivery shortcut. Use when
  house upgrades or any other runtime-assigned merchant stock is unbuyable in the
  converted game, when touching SetOwnership conversion in script_convert, or
  when reasoning about how a TES4 merchant's stock becomes a TES5 vendor chest.
---

# House upgrades cannot be bought

**Status: FIXED 2026-08-28 (third attempt), NOT yet confirmed in game.** The
diagnosis was measured on 2026-08-27 against `export/Oblivion.esm` and
`output/Oblivion.esm`; the rule in section 5 is implemented in `script_convert`
and built into `output/`.

Read the three 🛑 sections in section 5 before changing anything here: attempts
one and two both failed IN GAME, and each failure was a general trap, not a
detail of this quest.

| attempt | what it did | why it failed |
|---|---|---|
| 1 | `RemoveAllItems(<chest property>)` | the property was `None` (VMAD is not written by `--scripts-only`), and `RemoveAllItems(None)` DESTROYS the stock |
| 2 | runtime-resolved chest, inside the hand-over branch | that branch latches on a save variable, so no existing save could ever run it |
| 3 | the same call **plus** a poll sweep carrying the authored item list | current — untested |

**Symptom (in game):** buying a house works. Buying its furnishings does not —
the upgrades are simply not on sale anywhere.

---

## 1. How Oblivion does it

House upgrades are not a dialogue topic and not a special item type. There is no
`Upgrade` topic anywhere in `DIAL.txt` (measured: 0). They are **books**.

1. Each upgrade is a BOOK "receipt" — `HouseSkingradBedroomAreaReceipt`,
   *"This entitles the bearer to one bedroom area…"*. **63 of them across the
   seven cities.**
2. They sit in a hidden CONT placed in the merchant's shop
   (`HouseSkingradAddonsRef`), flagged **persistent + initially disabled**
   (`RecordFlags = 3072`) and with **no owner in the file at all**.
3. The house quest script, at the stage reached by buying the house, does:

   ```
   if ( GetStage HouseSkingrad == 10 ) && ( MerchSetup == 0 )
       HouseSkingradAddonsRef.Enable
       HouseSkingradAddonsRef.SetOwnership Gunder
       set MerchSetup to 1
   endif
   ```

4. The same script then polls `Player.GetItemCount <receipt>` and enables the
   matching furniture parent reference.

So buying an upgrade *is* buying a book, and the gate is that the container
holding the books does not exist until you own the house.

**The load-bearing assumption is step 3**: in Oblivion a merchant also sells
from containers he *owns*, not only from the one his placed reference names in
`XMRC`. Gunder's `XMRC` points at `ColovianTradersGunderChest`, never at the
addons container — so ownership alone is what puts the receipts on sale.

---

## 2. What converts correctly

Almost all of it. Do not go looking for a bug in these:

| Piece | State in `output/Oblivion.esm` |
|---|---|
| The quest script | converted faithfully — `HouseSkingradAddonsRef.Enable()` then `SetActorOwner(Gunder.GetActorBase())` |
| The container | present, **15 items** for Skingrad, Initially Disabled preserved |
| The receipts | all 63 BOOKs converted |
| The merchant's vendor faction | correct — `TES4Merchant_028F98`, `VEND` set, `VENC → ColovianTradersGunderChest` |

Ordinary merchants therefore work, which is why nothing else looks broken.

---

## 3. Where it dies

**In Skyrim a merchant's stock is exactly one thing: the container named by
`VENC` on his vendor faction.** `SetActorOwner` marks a container as his
*property* — stealing from it counts as theft — and does nothing else. It never
makes the contents merchandise.

So after conversion the receipts sit in an enabled container that the merchant
owns and will never sell. The Oblivion rule the script leans on has no Skyrim
equivalent, and the conversion is faithful to the letter of the script while
losing its meaning.

Note the shape of this bug: **every individual record is correct.** A structural
audit of the plugin passes. Only the *engine rule* the script assumed is gone.

---

## 4. Measured scope

Same structure in all seven cities, and every merchant already has a real
`VENC` chest to move the goods into:

| Script | Addons container | Items | Merchant | Merchant's VENC chest |
|---|---|---|---|---|
| `HouseBravilFurnScript` | `HouseBravilAddonsRef` | 6 | Nilawen | `FairDealNilawenChest` |
| `HouseBrumaFurnScript` | `HouseBrumaAddonsRef` | 9 | Suurootan | `NovaromaSuurootanChest` |
| `HouseCheydinhalFurnScript` | `HouseCheydinhalAddonsRef` | 10 | Borba gra-Uzgash | `BorbasGoodsBorbaChest` |
| `HouseChorrolFurnScript` | `HouseChorrolAddonsRef` | 11 | Seed-Neeus | `NorthernGoodsSeedNeeusChest` |
| `HouseImperialCityFurnScript` | `HouseICAddonsRef` | 5 | Sergius Verus | `ThreeBrothersSergiusChest` |
| `HouseLeyawiinFurnScript` | `HouseLeyawiinAddonsRef` | 7 | Gundalas | `BestGoodGundalasChest` |
| `HouseSkingradFurnScript` | `HouseSkingradAddonsRef` | 15 | Gunder | `ColovianTradersGunderChest` |

**A second, unrelated-looking case is the same bug:** `MS39Script` (Sinderion's
alchemy quest) owns him **four** skill-gated containers —
`MS39SinderionChestStage65/75/85/100`, all `RecordFlags = 3072` — so his stock
improves as your Alchemy rises. All four are broken the same way. Sinderion's
own `XMRC` chest is `0004E974`.

**Total: 11 containers across 8 scripts.**

### What is NOT affected

Of the **52** `SetOwnership` calls in Oblivion's scripts, **35 are inn bed
rentals** (`Publican*RentBed` — `SetOwnership` on a BED so sleeping there stops
being trespass). Those are a completely different idiom and convert fine. The
remaining 2 are a door and a rent door. **Do not "fix" any of them.**

---

## 5. The fix

Two pieces. First, one extra line where the script sets up the merchant,
moving the stock into the container the barter menu actually reads:

```papyrus
HouseSkingradAddonsRef.Enable()
HouseSkingradAddonsRef.SetActorOwner(Gunder.GetActorBase())
TES4Polyfill.SellFromOwnedContainer(HouseSkingradAddonsRef, 0x037CCF, "Oblivion.esm")
```

...plus a generated `TES4_RestockMerchants()` swept from the poll OUTSIDE that
branch, carrying the container's authored CNTO list so the shelf can be put back
-- see the two sections below. Neither piece is a name test: both are keyed on
the container being a CONT, the owner having vendor bits, and the container
being ENABLED.

### 🛑 Do NOT name the chest with a script property

The obvious form — `RemoveAllItems(ColovianTradersGunderChest)` with an
`ObjectReference Property` — was the first attempt and **failed in game**, in
the worst possible way.

A property's VALUE is stored in the PLUGIN's VMAD, filled by the importer, and
`--scripts-only` does not write VMAD. Measured: the converted `HouseBruma` QUST
fills 21 properties for `TES4_HouseBrumaFurnScript` and the chest was not among
them, so the property was `None` — and
**`RemoveAllItems(None)` DESTROYS the inventory** instead of moving it. The nine
Bruma receipts were deleted the moment the quest reached stage 10.

So every form the emitted code needs -- the chest AND each item -- is resolved
at runtime through `Game.GetFormFromFile` instead, and the polyfill returns
early on anything that fails to resolve. That is also what keeps the whole fix
inside the SCRIPTS, which is what lets it ship loose with no plugin rebuild. The
converted records keep their TES4 FormIDs (`000377B9` in the export, `010377B9`
in the output), so the low 24 bits address them directly.

**The generalisation, which outlives this bug:** a pass that adds a script
property needs `--import-only` too. A pass that must work from `--scripts-only`
alone -- which is what a loose-script patch ships -- has to resolve its forms at
runtime.

Everything downstream — `GetItemCount` polling, enabling the furniture — already
works and is untouched. If the receipts ever refuse to move, pass
`abRemoveQuestItems = true`; they are ordinary BOOKs, so this should not be
needed.

### 🛑 The hand-over branch LATCHES -- so the poll also SWEEPS

`MerchSetup` (and `WeakDone`/`ModDone`/... in MS39) is set to 1 the first time
the branch runs, and it lives in the SAVE. A transfer emitted only inside that
branch is dead on every save that already bought the house -- which was every
save the user had. Measured 2026-08-28: the only house stage-10 fragment in any
of the four Papyrus logs is Bruma's, from the run BEFORE the corrected build, so
the second version was never exercised at all.

The converter therefore also generates, per script, a `TES4_RestockMerchants()`
called from the poll on a ~60s countdown (`Int TES4_StockTick`, a plain script
variable -- it starts at 0 in a save that has never seen it, so the first pass
after installing sweeps immediately). It is gated on `akStock.IsEnabled()`,
which IS the authored gate, not a substitute: the container is flagged Initially
Disabled and the hand-over branch `Enable()`s it **one line above** the ownership
call in all 15 sites (measured).

### 🛑 Moving the stock is not enough -- the shelf does not KEEP

Two ways the stock goes missing after the move, neither recoverable from the
source container (it is empty by then):

1. the FIRST build resolved the chest through a script property `--scripts-only`
   could not fill, and `RemoveAllItems(None)` DESTROYED it (Bruma);
2. **the vendor chest RESPAWNS.** Measured over the export: TES4
   `CONT.DATA.Flags` splits 437 x 0 / 436 x 2, with 2 on every vendor chest and
   clutter container and 0 on unique/quest ones -- bit `0x02` is Respawns, and
   `convert_CONT` copies it through unchanged. All seven merchants' `XMRC`
   chests have it; the addons containers (flags=0) and `MS39SinderionChest` (0)
   do not. So a cell reset restores the chest to its base inventory. Oblivion
   had no such exposure -- the stock stayed put and ownership alone sold it.

A script cannot read a container either (`GetNumItems`/`GetNthForm` are SKSE;
the pipeline compiles against the vanilla headers), so the sweep CARRIES the
list. `CrossRefGraph.container_stock()` reads the base CONT's CNTO at conversion
time and the emitter writes it in as literals:

```papyrus
Function TES4_RestockMerchants()
  Int[] items0 = new Int[9]
  Int[] counts0 = new Int[9]
  items0[0] = 0x0B1593
  counts0[0] = 1
  ...
  TES4Polyfill.StockMerchant(HouseBrumaAddonsRef, 0x0377B9, "Oblivion.esm", items0, counts0)
EndFunction
```

**The TES4 count's SIGN is the rule**, and it is authored:

| count | TES4 meaning | StockMerchant |
|---|---|---|
| `> 0` | a finite pile | add while neither the chest nor the player has it |
| `< 0` | "always N for sale" | top the chest up to `N`, whatever the player does |

Measured: the 63 house receipts are all `+1`; Sinderion's four chests are all
negative (`-1, -2, -3, -5`). The negative branch also repairs an older gap --
`MS39SinderionChest` has flags=0, so his converted stock never restocked through
the respawn flag Skyrim uses, and the authored `-5` was lost.

`StockMerchant` does the `RemoveAllItems` too, so the sweep is move-then-repair
in one call. Papyrus caps an array at 128; the biggest container here holds 15,
and a larger one is truncated rather than emitting a script that will not
compile.

### `house_receipts.txt` is now only a manual escape hatch

`build_house()` still writes it to `patch_folder/output/`, but it is **no longer
shipped in the archive** -- a console batch has to sit next to `SkyrimSE.exe`
and the archive root is Data, so shipping it there was misleading. Nothing
should need it: a latched save, Bruma's destroyed container and a respawned
vendor chest all repair themselves within a minute of loading.

It is derived, not hand-listed: the emitted call gives the chest FormID, the
reference it names gives the stock container, and that container's own CNTO list
gives the receipts -- 73 items across 11 containers. `--plugin-index NN` stamps
the load-order byte, without which the console reads a bare `0377B4` as a
Skyrim.esm record; the default is a literal `XX`.

**It doubles as the experiment that settles the whole approach.** Everything
record-side is verified correct -- Suurootan's `TES4Merchant_035EB3` has
`VENC -> NovaromaSuurootanChest`, the receipt BOOK carries keyword `000A0E57`
which IS in his `VEND` list, and it is a takeable book worth 1100 gold -- so
receipts placed in that chest MUST appear in his barter menu. If they do not,
the vendor-chest model is wrong and the fix belongs in dialogue instead.

### The general rule for `script_convert`

Keyed on authored data, not on names:

> When a TES4 script calls `<ref>.SetOwnership <actor>` where `<ref>` resolves
> to a **CONT** reference and `<actor>` has vendor bits in `AIDT.Services`,
> emit the ownership call **and** a transfer of the container's contents into
> that actor's merchant chest -- plus a poll sweep, carrying that container's
> authored CNTO list, that keeps the chest stocked while the container is
> enabled.

The merchant chest is already resolved on the import side by
`_build_merchant_chest_map()` in `tes5_import/record_types/actors.py`, which
maps a base actor to the `XMRC` container on its `ACHR`. `script_convert` reads
the same export and can resolve it the same way.

The bed-rental calls are excluded automatically: a BED is not a CONT.

---

## 6. Why not an ESP patch -- and what ships instead

The `MyOwnTamriel*Patch` ESP route does not work here, and the reason is worth
keeping:

- A Skyrim vendor faction has **one** `VENC`. Pointing Gunder's at the addons
  container would replace his ordinary shop stock with 15 receipts.
- Adding a second vendor faction is not a workaround — the barter menu does not
  merge them.
- Simply moving the receipts into the vendor chest *statically* does work, but
  destroys the gate: the furnishings become buyable before the house is owned.

The fix belongs in `script_convert`, so it is part of the CONVERSION: a full
rebuild that repacks the BSA carries it, and the patch is then unnecessary. The
patch exists only because re-deploying a multi-gigabyte converted mod to change
nine scripts is absurd -- it ships those scripts LOOSE, where they win over the
copies in the mod's BSA:

```bash
python convert.py -f Oblivion.esm --scripts-only          # produces the fix
python tools/patch/build_patch.py --patch house --plugins Oblivion.esm
```

`build_house()` in `tools/patch/build_patch.py` finds the scripts by the marker
comment the converter stamps on the line it adds
(`script_convert.constants.OWNED_CONTAINER_MARKER`, shared by both so they
cannot drift), never by a hardcoded list — so another plugin's merchants, or a
future script the same rule touches, are packaged without editing the tool. It
is the only patch in that driver that ships no plugin, and it aborts if no
converted script carries the marker, which is what "you did not run
`--scripts-only`" looks like.

Also in the GUI's Patches section as **House upgrades**.

## 7. Verifying a fix

**Measured after the implementation (2026-08-28), all of it reproducible:**

| check | result |
|---|---|
| scripts carrying the transfer | exactly the 8 from section 4 |
| in-branch transfer sites | 15 — one per house, 8 in MS39 (4 chests x 2 branches) |
| swept containers | 11 — one per house, 4 in MS39 (deduplicated by container) |
| authored items carried into the sweep | 73 (63 receipts + Sinderion's 10) |
| bed rentals touched | **0** |
| full stage | 16,519/16,519 scripts compiled, 0 failed |
| packaged | `MyOwnTamrielHousePatch.zip`, 8 `.pex` + `TES4Polyfill.pex`, 21,919 bytes |

The bed-rental exclusion is not luck and not a name test: `PublicanAllSaintsWillet`
still emits `AllSaintsInnRentBed.SetActorOwner(Willet.GetActorBase())` and no
transfer, **even though Willet is himself a vendor with an XMRC chest** — the
reference resolves to a BED, not a CONT, and that is the guard.

1. `python convert.py -f Oblivion.esm --scripts-only`
2. Confirm both halves reached all eight scripts (15 and 11; exclude
   `TES4Polyfill.psc`, which is copied into the same folder and names both):
   ```bash
   D=output/Oblivion.esm/scripts/source
   grep -h "TES4Polyfill.SellFromOwnedContainer" $D/TES4_*.psc | wc -l   # 15
   grep -h "TES4Polyfill.StockMerchant"          $D/TES4_*.psc | wc -l   # 11
   grep -h "items[0-9]\[" $D/TES4_*.psc | wc -l                          # 73
   ```
3. Confirm nothing leaked into the bed rentals:
   ```bash
   grep -l "SellFromOwnedContainer\|StockMerchant" $D/TES4_Publican*.psc   # expect none
   ```
4. Package it, if you are not repacking the whole mod:
   ```bash
   python tools/patch/build_patch.py --patch house --plugins Oblivion.esm --plugin-index 0E
   ```
5. In game: buy a house, then talk to that city's merchant — the receipts should
   be in the barter list at their own price. Buying one should furnish the room
   on the next script tick.

### What each in-game outcome MEANS

The sweep runs on a ~60s countdown, so give a loaded save a minute before
concluding anything.

| what happens | read it as |
|---|---|
| receipts on sale after buying the house | working |
| still nothing, and the Papyrus log has `TES4Polyfill: StockMerchant could not resolve chest` | the FormID or the plugin file name is wrong — check `ScriptConverter.plugin_file` and that the converted record kept its TES4 id |
| still nothing, log silent | the vendor-chest model itself is wrong. Prove it with `house_receipts.txt` (`patch_folder/output/`, next to `SkyrimSE.exe`, `bat house_receipts`): if hand-placed receipts do not appear in the barter menu either, no script fix can work and the answer is dialogue-side |
| receipts appear BEFORE the house is bought | the `IsEnabled()` gate is not holding — check that the container is still Initially Disabled in the built plugin |
| Sinderion's shelf empty at the right Alchemy level | his four containers are enabled by skill AND a day/hour delay in `MS39Script`; wait a game day before calling it broken |

Sinderion is also the case that proves the negative-count branch: his stock is
authored `-5/-3/-2/-1`, so buying one of an item should see it back on his shelf
within a minute.
