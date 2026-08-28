---
name: inn-room-rental
description: >-
  Diagnosis and the fix for renting a room from a converted Oblivion innkeeper:
  every inn answers "you lack the funds" although the player has gold, and a
  room that is rented stays the player's forever instead of for one night.
  Covers Oblivion's BedRental model (a gold condition on paired INFOs, a
  publican object script that unlocks the door and owns the bed), the two
  independent defects behind it — condition params naming Gold001 resolved to
  our inert converted copy instead of Skyrim's currency, and TES4's LOW PROCESS
  (a persistent actor's GameMode block kept running with its cell unloaded)
  having no equivalent, which strands both the "player has left" latch and the
  GameHour counter — the authored signals that decide which polls need it, the
  performance ceiling that keeps 213 streetlights out, and the one Jerall View
  room that vanilla Oblivion itself never releases. Use when a converted
  merchant or innkeeper refuses the player's money, when a timed script state
  never expires, or when touching engine-item substitution in dialog_conditions
  or the OnUpdate poll lifecycle in script_convert.
---

# Inn rooms: "you lack the funds", and a room rented forever

**Status: BOTH FIXED 2026-08-28, not yet confirmed in game.** Measured against
`export/Oblivion.esm` and the built `output/Oblivion.esm/Oblivion.esm`.

**Symptom (in game):** most inns answer *"I'm afraid you lack the funds to rent
a room"* although the player is carrying gold; a room that did get rented stays
the player's permanently rather than for a day.

Two unrelated defects, in two different stages. Fixing one alone leaves the
other visible.

---

## 1. How Oblivion does it

Quest `BedRental` (`0003AB56`), topic `BedYes` (`0003AB46`, *"I'll take it."*).
Each innkeeper gets a PAIR of INFOs under it, distinguished only by the gold
test:

```
INFO 000B12A0  GetIsID(Olav) == 1  &&  GetItemCount(Gold001) >= 10 [RunOnTarget]
    Result: player.removeitem gold001 10 ;  set OlavRef.rent to 1
INFO 000B12A1  GetIsID(Olav) == 1  &&  GetItemCount(Gold001) <  10 [RunOnTarget]
    "Not even 10 gold to your name? …"
```

`rent = 1` is picked up by that innkeeper's own object script (37
`Publican*` SCPTs), which unlocks the room door, gives the bed to the player,
stamps the clock, and — a day later, once the player is elsewhere — relocks the
door and hands the bed back.

Prices are 10, 15, 20, 25 and 40 gold. `RunOnTarget` is what makes the count
read the PLAYER, not the innkeeper; that converts correctly (TES5 runOn = 1).

---

## 2. Defect A — the gold condition names a dead record

`GetItemCount Gold001` is how Oblivion asks *can you pay?*.
`dialog_conditions._remap_formid` shifted the param like any other reference,
to **`0x0100000F`** — our converted Oblivion Gold001. That record is real,
valid, and **inert**: Skyrim hardcodes `0x0F` as currency, so the player's
money is always Skyrim's copy.

Measured in the built plugin: the converted copy is referenced by **0 REFR, 0
CNTO, 0 LVLO** — nothing hands it out, so the count reads 0 and every gold gate
answers no, at every inn.

**Scope before the fix: 88 `GetItemCount` conditions on `0x0100000F`** — all 31
innkeepers of `BedRental`, plus bribes, tolls and training fees.

The record fields (`text_reader.get_formid`) and the scripts
(`object_scripts`, `dialog_converter`) already applied
`TES4_ITEM_FORMID_TO_SKYRIM`; only the conditions were left reading the dead
copy.

**Fix:** apply the same substitution in `dialog_conditions._remap_formid`,
after the player/engine-global passthrough. It **cannot** corrupt a param that
is an index rather than a FormID, because `0x0000000F → 0x0000000F` is the
identity — all it does is stop the shift.

Rebuilt: 88/88 now on `0x0000000F`, 0 on the dead copy.

---

## 3. Defect B — there was no low process

`TES4Polyfill.SafeGameModeGate` stops an object/actor poll once the
reference's cell detaches. That is right for almost every script and **wrong
for one whose whole job is to notice something that happens WHILE THE PLAYER IS
AWAY.** TES4 ran a persistent actor's `GameMode` block in the LOW PROCESS with
its cell unloaded, just slowly; the conversion had no low process at all.

The 32 rentals fail two different ways for that one reason:

* **29 publicans** (`PublicanBrumaOlavsTapandTackOlav`, `PublicanRoxeyMalene`, …)
  latch on

  ```
  if ( Player.GetInCell <inn> == 0 )
      if ( Cleanup == 1 )
          set Cleanup to 2
  ```

  unanswerable from a poll that only runs while the player is *here*: the only
  pass that could see it is the single trailing tick after the cell
  transition, racing the loading screen.

* **Bruma's Jerall View** (`PublicanBrumaJerallViewHafid`) instead counts
  `GameHour` boundaries to 24, and that counter advances **at most one hour per
  pass** (`if ( renthour + 1 ) < GameHour / set HoursPassed to HoursPassed + 1`).
  In Oblivion its `MenuMode` twin counted through the wait/sleep menu as time
  flowed; in Skyrim a sleep jumps the clock in one step, so eight hours of sleep
  score 1. With passes only while the player stands in the inn it never reached
  24.

**Fix:** `_needs_low_process_poll()` in `script_convert/converter.py`. A
qualifying body re-arms on the `Else` branch of the gate at
`_LOW_PROCESS_INTERVAL` (5 s) instead of stopping — the top insurance arm, the
bottom cadence arm, and the spliced `Return` prefix all get it.

Two AUTHORED signals, no name matching:

1. the body **stores** a clock global in a script variable (`set renthour to
   GameHour`) — the "remember when this started" idiom, whose elapsed time is
   not re-derivable on the next attach;
2. the body tests the **player being elsewhere** (`Player.GetInCell <x> == 0`).

### 🛑 Merely READING the clock must NOT qualify

That is what `streetlightscript` and `ExteriorLightScript` do (`if gamehour >=
18 / enable / else / disable`) — a decision recomputed from scratch every pass
that self-corrects the instant the cell attaches. Including reads takes the set
from **46 scripts on 59 placed instances** to **73 on 372** (213 streetlights +
60 exterior lights + 11 bell towers), i.e. ~74 Papyrus passes/second forever,
for no behavioural gain. Measured over Oblivion.esm's 2,031 object scripts with
source.

---

## 4. The Jerall View room is a VANILLA bug — do not "fix" it

`PublicanBrumaJerallViewHafid` is the only publican that counts hours rather
than testing the player's cell, and **nothing in Oblivion.esm ever sets its
`cleanup` to 2**, so its release block can never run.

Measured: `set Cleanup to 2` appears in exactly **32** scripts, all publicans,
and Hafid's is not one of them. The only writes to `HafidHollowlegRef.*`
anywhere in the plugin are `rent` (from the dialogue INFO) and
`EvaluatePackage` / `moveto` / `evp` (MQ13, unrelated). Its trigger script
`PublicanJerallViewTriggerScript` only calls `EvaluatePackage` when
`Cleanup == 1`.

So the Jerall View room never un-rents in the original game either. Our
conversion reproduces it faithfully. Deviating from vanilla to release it is a
deliberate design choice, not a bug fix — ask first.

---

## 5. Verifying

```bash
# Defect A — after --import-only, no gold gate may name the dead copy.
python - <<'PY'
import struct, collections
data = open('output/Oblivion.esm/Oblivion.esm','rb').read()
c, i = collections.Counter(), 0
while True:
    i = data.find(b'CTDA', i)
    if i < 0: break
    if struct.unpack_from('<H', data, i+4)[0] == 32:
        b = data[i+6:i+38]
        if struct.unpack_from('<H', b, 8)[0] == 47:      # GetItemCount
            c[hex(struct.unpack_from('<I', b, 12)[0])] += 1
    i += 4
print('0x100000f:', c.get('0x100000f', 0), ' 0xf:', c.get('0xf', 0))
PY
# expect 0 and 88

# Defect B — after --scripts-only.
D=output/Oblivion.esm/scripts/source
grep -rl "TES4 low process" $D | wc -l                       # 54
grep -c "TES4 low process" $D/TES4_PublicanBrumaOlavsTapandTackOlav.psc   # 1
grep -c "TES4 low process" $D/TES4_streetlightscript.psc                  # 0
```

Useful while investigating:

```bash
python tools/dialog/tes4_ctda_dump.py --dial 0003AB46      # the whole BedYes topic
python tools/validate/vmad_property_typecheck.py --plugin Oblivion.esm -v
python tools/script/convert_scripts_subset.py -f Oblivion.esm \
    --scpt PublicanBrumaOlavsTapandTackOlav --out temp/subset_scripts
```

Regression tests: `tests/test_dialog.py::TestGoldConditionParam` (5) and
`tests/test_script_converter.py::TestLowProcessPoll` (7).

Stages to rebuild: **`--import-only`** for defect A, **`--scripts-only`** for
defect B. Both are needed; neither alone makes the rental work.

In game: rent a room (gold should be deducted and the door unlock), sleep,
leave the inn, come back the next day — the door should be locked again and the
bed no longer yours. Everywhere except Jerall View.

---

## 6. Verified correct — do not re-investigate

| thing | state |
|---|---|
| `RunOnTarget` on the gold condition | converts to TES5 runOn = 1, correct — the count reads the player |
| `GameDay` / `GameMonth` / `GameHour` script properties | bound to Skyrim's own `0x37` / `0x36` / `0x38`, not our copies |
| the publicans' VMAD properties | all bind; the rent door, bed, cell and the other publican resolve to real refs |
| the rent bed and rent door REFRs | `XOWN` = the innkeeper, `XLOC` level 50 preserved |
| `BrumaOlavsRentBed.SetOwnership Sthasa` in the cleanup | a Bethesda copy-paste bug in the ORIGINAL script; faithful |

Full write-ups: `docs/dialogue_conversion_notes.md` (the gold param) and
`docs/papyrus_conversion_notes.md`, "The LOW PROCESS" (the poll).
