---
name: house-upgrade-fix
description: >-
  Diagnosis and the fix for converted Oblivion house upgrades that cannot be
  bought: the house itself sells fine, but the furnishing receipts never appear
  in the merchant's barter menu. Covers Oblivion's receipt/container/quest-script
  model for player-house furnishing, what converts correctly, the exact reason it
  dies in Skyrim (barter reads ONLY the vendor faction's VENC container, so an
  owned container is never merchandise), the measured scope across all seven
  cities plus Sinderion's skill-gated stock in MS39, the one-line Papyrus fix,
  the general script_convert rule behind it, and why an ESP patch is the wrong
  vehicle. Use when house upgrades or any other runtime-assigned merchant stock
  is unbuyable in the converted game, when touching SetOwnership conversion in
  script_convert, or when reasoning about how a TES4 merchant's stock becomes a
  TES5 vendor chest.
---

# House upgrades cannot be bought

**Status: DIAGNOSED, NOT FIXED.** Everything below was measured on 2026-08-27
against `export/Oblivion.esm` and `output/Oblivion.esm`. Nothing has been
changed in the pipeline yet.

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

One extra line where the script sets up the merchant, moving the stock into the
container the barter menu actually reads:

```papyrus
HouseSkingradAddonsRef.Enable()
HouseSkingradAddonsRef.SetActorOwner(Gunder.GetActorBase())
HouseSkingradAddonsRef.RemoveAllItems(ColovianTradersGunderChest)   ; <-- add
```

`ObjectReference.RemoveAllItems(akTransferTo)` moves the whole stock in one
call. **The gate survives exactly**: below stage 10 the branch never runs, so
nothing is on sale until the house is bought; `MerchSetup` keeps it once-only.
Everything downstream — `GetItemCount` polling, enabling the furniture — already
works and is untouched.

If the receipts refuse to move, pass `abRemoveQuestItems = true`; they are
ordinary BOOKs, so this should not be needed.

### The general rule for `script_convert`

Keyed on authored data, not on names:

> When a TES4 script calls `<ref>.SetOwnership <actor>` where `<ref>` resolves
> to a **CONT** reference and `<actor>` has vendor bits in `AIDT.Services`,
> emit the ownership call **and** a transfer of the container's contents into
> that actor's merchant chest.

The merchant chest is already resolved on the import side by
`_build_merchant_chest_map()` in `tes5_import/record_types/actors.py`, which
maps a base actor to the `XMRC` container on its `ACHR`. `script_convert` reads
the same export and can resolve it the same way.

The bed-rental calls are excluded automatically: a BED is not a CONT.

---

## 6. Why not an ESP patch

The `MyOwnTamriel*Patch` route does not work here, and the reason is worth
keeping:

- A Skyrim vendor faction has **one** `VENC`. Pointing Gunder's at the addons
  container would replace his ordinary shop stock with 15 receipts.
- Adding a second vendor faction is not a workaround — the barter menu does not
  merge them.
- Simply moving the receipts into the vendor chest *statically* does work, but
  destroys the gate: the furnishings become buyable before the house is owned.

The fix belongs in `script_convert`, and ships via `--scripts-only`.

---

## 7. Verifying a fix

1. `python convert.py -f Oblivion.esm --scripts-only`
2. Confirm the transfer line reached all eight scripts:
   ```bash
   grep -l "RemoveAllItems" output/Oblivion.esm/scripts/source/TES4_House*FurnScript.psc
   grep -n "RemoveAllItems" output/Oblivion.esm/scripts/source/TES4_MS39Script.psc
   ```
3. Confirm nothing leaked into the bed rentals:
   ```bash
   grep -l "RemoveAllItems" output/Oblivion.esm/scripts/source/TES4_Publican*.psc   # expect none
   ```
4. In game: buy a house, then talk to that city's merchant — the receipts should
   be in the barter list at their own price. Buying one should furnish the room
   on the next script tick.
