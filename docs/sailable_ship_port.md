# Sailable Ship: how it works, and the Cyrodiil route

Notes taken while pointing [Sailable Ship](https://www.nexusmods.com/skyrimspecialedition/mods/72070)
(ziher, v1.12) at our converted Cyrodiil. Everything below was measured from
`patch_folder/sources/Sailable Ship/` on 2026-08-28, not read off a mod page.

Built by `tools/patch/assign_ship_port.py`; see
[python_tools_reference.md](python_tools_reference.md) for the command.

---

## The mod

`Sailable Ship.esm`, masters **Skyrim.esm, Update.esm, Dragonborn.esm**. Built
for SkyrimVR (`meta.ini` says `gameName=SkyrimVR`) with a working flat-screen
path — the mode test is `Game.GetFormFromFile(0x00000BD7, "SkyrimVR.esm")`,
absent means "PANCAKE".

The BSA is 1.5 GB and is almost entirely terrain LOD: 7,422 meshes and 10,626
textures under `terrain/`, against 200 meshes for the ships themselves. It also
ships **complete Papyrus sources** — 32 `.pex` and the matching 32 `.psc` under
`scripts/source/`.

Record counts: 5,463 REFR, 160 CELL, 107 STAT, 98 ACTI, 92 CLFM, 78 GLOB,
52 FLST, 46 MESG, 45 LAND, 7 WRLD.

### Five ocean worldspaces

Besides Skyrim and Solstheim: **Azurian Sea, Padomaic Ocean, South Padomaic
Ocean, Southwest Padomaic Ocean, Abecean Sea** — empty water with LAND and
terrain LOD, which is where the 1.5 GB goes.

### Sailing is a Papyrus loop, not physics

`aaaShipSail` (1,367 lines) sits on the ship reference. `OnUpdate()` is an
unbounded `While` loop: read input → `Turn()` → `PosCalc()` → `ShipSail()`, and
`ShipSail()` ends in

```papyrus
Ship.translateTo(PosX, PosY, ShipHeight, pitchX, pitchY, angle,
                 math.abs(ShipFinalSpeed), 0.0)
```

`CalculatePapyMod()` normalises each step against `Utility.GetCurrentRealTime()`
so frame rate does not change the speed. The player is attached with
`PlayerREF.setVehicle(Ship)` and released to `setVehicle(none)` to walk the
deck. A separate `aaaCollTrigger` reference is dragged along as the collision
body; hits arrive as `ShipMetrics()[0] == -1 / -2`.

Wind is a home-made model (`MakeMETAR`): strength from
`Weather.GetCurrentWeather().GetClassification()` (0.8–1.2 / 0.85–1.4 /
0.85–1.8), direction random-walking ±45° with a day/evening/night/morning bias,
re-rolled on a `TimeScale`-derived interval. Final speed is
`ShipSpeed * (1 - AOA/180) * windSpeed`, so beating into the wind nearly stops
the ship.

Controls are `RegisterForKey` on the numeric keypad (Num7/8/9 rudder, Num+/−
throttle, Num\*/Num÷ time acceleration via `ConsoleUtil.ExecuteCommand("sgtm …")`)
plus gamepad `RegisterForControl`, plus a `aaaShipMovementDirection` global fed
by quest-stage conditions for VR controllers.

**ConsoleUtil is a hard dependency** — 11 `ExecuteCommand` calls, and the
in-game "Naval Charts" book checks for it explicitly by writing an actor value
and reading it back.

### Worldspace transitions

A sea gate is a placed `aaaTeleport` activator carrying `aaaShipTeleportScript`.
Its script properties are the whole destination:

| property | meaning |
|---|---|
| `LandingWorldSpace` | a console command, `"CenterOnWorld <EditorID> x y"` |
| `Xpos`, `Ypos` | where the ship is set down in that worldspace |
| `ZWaterHeight` | that worldspace's sea level |
| `LandingWorldspaceIndex` | the slot in the addon table below |

`OnLoad()` fades out, sets `bDisablePlayerCollision:Havok`, runs the console
command, `SetPosition`s the player, `MoveTo`s the ship after them, then calls
`MoveShipParts()` to bring the doors and markers across. The player is flagged
with `aaaPlayerIsTeleportingFaction` so the gate cannot re-trigger.

Shared properties (`aaaShipUtility`, `MapMarker`, `aaaShipHeight`,
`aaaPlayerIsTeleportingFaction`) live on the **base ACTI**, not on each
reference — the references carry only the destination. That is why the override
in our patch is three subrecords long.

### The addon-worldspace table

`aaaShipUtilityScript.MakeWorldspaceArrays()` hardcodes 23 third-party
worldspaces as `(FormID, plugin file name)` pairs, and `IsWorldspaceActive(i)`
is nothing but `Game.GetFormFromFile(ID, filename) != None`. Indexing is
sequential: 0 Skyrim, 1 Solstheim, 2–6 the five seas, 7+ the addons.

The lists that hang off it:

| FormList | size | shape |
|---|---|---|
| `aaaTeleportMarkers` | 28 | the base routes |
| `aaaTeleportMarkersAddOn` | 46 | **2 per addon world**: [outbound gate, outbound map marker] — hence `iIndex / 2` in `EnableAddonWorldSpaces` |
| `aaaShipMapWorldspaceObjects` | 30 | 7 base + 23 addons — hence `index > 6` / `index - 7` in `EnableAddonMapObjects` |
| `aaaShipsAll` / `aaaShipPurchasedGlobals` | 29 | the buyable ships |

**All 23 addon slots are taken.** Adding a 24th means extending the hardcoded
array *and* both FormLists, keeping the pairing and the offset of 7.

The in-game book `aaaStudyCharts` is what runs the sweep. Note the escape hatch:
if the global `aaaShipEnableAllMarkers == 1` it calls
`BatchEnabler(aaaTeleportMarkersAddOn)` and lights every addon port
unconditionally, skipping `IsWorldspaceActive` entirely.

### Getting back

Each gate is one of a **quartet** sitting within ~550 units of each other, all
initially disabled:

| ref | role |
|---|---|
| `036E0833` | outbound gate → the addon world |
| `036E0835` | outbound map marker, FULL "Cyrodiil Route" |
| `036E0832` | **return** gate → `CenterOnWorld SouthWestPadomaicOcean 0 0` |
| `036E0834` | return map marker, "Southwest Padomaic Ocean Route" |

On arrival the script finds the nearest map marker to itself (`036E0834`), then
the nearest `aaaTeleport` to *that* (`036E0832`), and **moves both into the
destination worldspace next to the ship and enables them**. So the return path
is created at runtime by geometry and never names a worldspace — which is why
retargeting a route does not touch it.

### Other pieces

- **The naval map** is a real interior cell, `aaaSailableShipMapCell`: the
  player is teleported onto a scale model and moves a ship token to pick a
  route. Ports are ACTI like `aaaShipMapPortCyrodiil`.
- **Buying a ship**: `aaaBuyShipScript` shows a Message, charges
  `aaaShipPriceNN`, sets `aaaShipPurchasedNN`, hands over a deed BOOK, and
  `aaaShipSpawnScript` delivers the ship 1/3/7 game days later.
- **Cabins** are interior cells. Entering one parks the exterior loop
  (`ShipSailInInterior`) and `aaaShipSailInteriorScript` keeps integrating the
  ship's position without `translateTo`, handing the result back on exit.
- Optional interop: `Sailable Ship Missions.esp`, VRIK, `DA_Skyship.esm`
  (Dev Aveza gets its own transition branch with a `SaveGame`/`LoadGame`).

---

## Rigmor's Cyrodiil vs ours

`RigmorCyrodiil.esm` (Jim 2021, "Rigmor of Cyrodiil - Reboot", 83 MB; masters
Skyrim, Update, Dawnguard, HearthFires, Dragonborn) carries three worldspaces:

| FormID | EditorID | exterior cells | water |
|---|---|---|---|
| `05001B8F` | RigmorSeaOfGhosts | 4,010 | 0 |
| `052F4DB2` | **RigmorCyrodiil** | 16,387, X[-64..63] Y[-64..74] | **-3150** |
| `055BB0F7` | RigmorRoscrea | 16,624 | 1024 |

`0x2F4DB2 = 3100082`, which is exactly the id in `MakeWorldspaceArrays()`.

**It is the real Cyrodiil geography**, at the same scale and orientation as
ours. Its 44 map markers put the cities within one to four cells of where the
converted plugin puts them:

| place | Rigmor (cell, X/Y) | ours |
|---|---|---|
| Weye | (2,17) 11619, 71849 | (0,15) 1152, 63488 |
| Skingrad | (-16,-2) -65303, -7374 | Castle Skingrad (-16,-1) -62547, -1419 |
| Kvatch | (-33,-3) -131122, -10053 | (-36,-7) -146938, -27082 |
| Anvil | (-47,-9) -192092, -33333 | Anvil Lighthouse (-49,-10) -196733, -37483 |

Ours (`TES4Tamriel`, FULL "Cyrodiil", `0100003C`) has 14,687 exterior cells,
X[-64..69] Y[-69..59]. **The one difference that matters is sea level: Rigmor
-3150, ours 0.**

### The landing point transfers unchanged

The route's own `Xpos/Ypos` are `93877, -183808` = cell **(22,-45)**, Topal Bay
south of Leyawiin. In our Cyrodiil that cell exists, has LAND, carries no `XCLW`
(so it uses the worldspace default of 0), and measures:

- seabed min -5,992, max -4,472, mean -5,265
- nearest placed object 1,508 units away and 4,600 units below the surface
- nearest coastal content (Bogwater, Fort Blueblood) ~7,800 units north

So only `ZWaterHeight` had to change. `assign_ship_port.py` re-measures this
every build and aborts if the terrain reaches the water line.

---

## The patch

`MyOwnTamrielShipPatch.esp` — 6 records, 4 groups, 10,750 bytes; masters
Skyrim.esm, Update.esm, Dragonborn.esm, Sailable Ship.esm (all of them already
forced by Sailable Ship itself) plus Sailable Ship Missions.esp **when that is
installed** — the last one only because a record is read out of it.

1. **REFR `036E0833`**, nested under WRLD `036B2CCF` → CELL `036B2D16` →
   persistent children. Only `VMAD` changes; `NAME` and `DATA` are
   byte-identical. New values: `LandingWorldSpace = "CenterOnWorld TES4Tamriel
   22 -45"`, `ZWaterHeight = 0`, `Xpos/Ypos` unchanged. The group is type 8
   (persistent), so **no ONAM entry is needed** — that requirement is type 9
   only.
2. **REFR `040D70E6`** `aaaSMPortMarkerCyrodiil001`, in the same cell, when
   Missions is installed: `PosX/PosY/PosZ` → the same landing. See
   [Sailable Ship Missions](#sailable-ship-missions).
3. **WRLD `0000003C` Tamriel and `02000800` DLC2SolstheimWorld**, top-level
   overrides that re-assert the object bounds around the sea gates and keep
   whatever name another local patch gives the worldspace. See
   [the two barriers](#getting-out-of-skyrim-the-two-barriers).
4. **`Scripts/aaaShipUtilityScript.pex`**, shipped loose so it wins over the
   BSA copy: string-table entry `"RigmorCyrodiil.esm"` → `"Oblivion.esm"`, and
   the one int literal `3100082` → `60`.
5. **`MyOwnTamrielShipPatch.ini`**, the per-plugin INI holding
   `bBorderRegionsEnabled=0`.

Nothing else needed renaming: the map port ACTI is already
`aaaShipMapPortCyrodiil` ("Cyrodiil"), the marker name CLFM is
`aaaMarkerNameAddon07` ("Cyrodiil Route"), and the map marker's FULL is
"Cyrodiil Route".

### Why the script is patched, not recompiled

The sources are shipped, and the CK compiler is on this machine — but
`aaaShipUtilityScript.psc` declares `aaaSMUtilityScript Property SMUtil`, a type
that lives in the optional `Sailable Ship Missions.esp` whose sources the mod
does **not** ship. Recompiling would require a hand-written stub of that addon's
API, and any signature guessed wrong would silently break Missions for everyone
who has it. Rewriting two literals leaves all other bytes — Missions interop
included — untouched. `tools/patch/pex_patch.py` does that, and refuses to act
on a literal that is not present exactly once.

### The mod is script-dead without Sailable Ship Missions

> **Resolved 2026-08-28** — Missions is now installed in
> `patch_folder/sources/Sailable Ship/`, and its BSA supplies
> `aaasmutilityscript.pex`. Kept because the diagnosis is the reusable
> part: one missing `.pex` takes down a whole mod's script graph.

**Diagnosed 2026-08-28 from the Papyrus log**, after the ship cabin could not be
entered in game. Not caused by this patch — measured below.

The log's ship section opens with one line that explains everything after it:

```
Cannot open store for class "aaasmutilityscript", missing file?
Error: Unable to link types associated with function "FindHeadingMarkerOnCourse" ... on "aaashipsailinteriorscript".
Error: Unable to link type of property "ShipValues" on object "aaaShipSail"
Error: Unable to link types associated with function "OnActivate" ... on "aaaShipCabinDoor".
Error: Unable to link types associated with function "OnLoad" ... on "aaaShipTeleportScript".
warning: Property LandingWorldSpace on script aaaShipTeleportScript ... cannot be initialized
```

`aaaShipUtilityScript`, `aaaShipMapShipScript` and `aaaShipSailInteriorScript`
each declare a property typed `aaaSMUtilityScript`, which lives in the optional
**Sailable Ship Missions.esp**. That `.pex` is in neither the base download nor
`Sailable Ship.bsa` — measured: the BSA holds 32 `.pex` and none is `aaasm*`.

**Papyrus resolves a property's TYPE at link time even when the property is
never assigned.** So the missing file takes down `aaaShipUtilityScript`, and
with it every script holding an `aaaShipUtilityScript` property — which is all
of them. `CheckAddons()` handles Missions being absent at *runtime*; nothing
handles it at *link* time.

In game that means no cabin, no helm, no transitions, and no route: the log
shows `aaaShipTeleportScript` failing to bind `LandingWorldSpace`, so this
patch's own override is never even read.

**Why this patch is not the cause**, measured rather than argued:

| check | result |
|---|---|
| Does the BSA's own `aaaShipUtilityScript.pex` reference `aaasmutilityscript`? | **yes** — identically to ours |
| How does our `.pex` differ from the BSA original? | string-table entry 553 only (`RigmorCyrodiil.esm` → `Oblivion.esm`), plus 3 bytes inside one int literal |
| Does the patched `.pex` still parse end to end? | yes — 44,540 bytes consumed, one object, same 1,161 int literals and 105 string refs, both edits inside `MakeWorldspaceArrays` |

The fix is to install **Sailable Ship Missions**, or to put a compiled stub of
`aaaSMUtilityScript` in `Data/Scripts/`. A stub is NOT shipped by this patch: a
loose one would shadow the real script for anyone who does install Missions.

`assign_ship_port.py` now scans every `.pex` in the mod's BSA for types it does
not ship and prints this warning at build time, so it is caught before a
play session rather than after one.

---

## Getting OUT of Skyrim: the two barriers

Measured 2026-08-28, after the route could not be tested because "the world
border is still there in Tamriel". Two separate things stand between the player
and every sea gate, and neither is anything the base patch used to touch.

### 1. The border region (a REGN header flag, and only an INI turns it off)

Skyrim.esm contains **exactly one** REGN carrying record-header flag `0x40` --
"Border Region" in the CK's region dialog:

| | |
|---|---|
| record | `000C5859` `BorderRegionSkyrim` |
| WNAM | Tamriel `0000003C` |
| polygon | 173 points, X `-188714 .. 213174`, Y `-132575 .. 169851` |

Sailable Ship places **eight** `aaaTeleport` gates in Tamriel, and the
southernmost sits at Y `174372` -- every one of them is outside that polygon.
With border regions on, the answer to sailing towards any of them is
`sPlayerLeavingBorderRegion`, "You cannot go that way."

**No plugin can switch it off.** The setting is `bBorderRegionsEnabled:General`
(present in `SkyrimSE.exe`; `Skyrim.ini`'s `[General]`), and Skyrim reads
`Data/<plugin name>.ini` for every plugin it loads (`%sdata/%s.ini` in the exe),
which is how the mod ships `Data/Sailable Ship.ini` holding exactly

```ini
[General]
bBorderRegionsEnabled=0
```

`assign_ship_port.py` now writes the same file as
`Data/MyOwnTamrielShipPatch.ini` and the zip carries it, so the requirement
travels with the patch rather than depending on the mod's own file surviving
deployment. If the border still stands, the per-plugin INI is not being honored
and the line has to go in `Skyrim.ini` itself (MO2: the profile's `Skyrim.ini`).

**Why the REGN is not overridden instead.** It would be the airtight fix -- but
the record carries `RDAT` type 4 + `RDMP`, and `RDMP` is an **lstring** (`4326`)
into Skyrim.esm's STRINGS. It is the ONLY region supplying a map name for the
Tamriel worldspace (the other six are city worldspaces), so it cannot be
dropped, and a non-localized patch copying those four bytes turns the name of
Skyrim's wilderness into garbage. Baking the resolved literal would freeze one
language. The INI is the cheaper and cleaner lever.

Note that **our converted worldspace proves nothing here**: the importer never
sets flag `0x40`, so `output/Oblivion.esm` has 57 regions and zero border
regions. "TES4Tamriel has no border" is our converter, not the INI working.

### 2. The worldspace object bounds (NAM0/NAM9), and who reverts them

| | NAM0 (min X, Y) | NAM9 (max X, Y) |
|---|---|---|
| vanilla Tamriel | -233472, -176128 | 253952, 208896 |
| Sailable Ship's override | **-278528**, -176128 | 253952, **290816** |
| what the gates need | -277223 | 289334 |

The mod widens Tamriel exactly enough to enclose its outlying gates -- **six of
the eight are outside the vanilla bounds** -- which is why it overrides the
Tamriel WRLD at all.

**The bounds ARE the "which cells exist" contract.** Vanilla proves it: Tamriel
has 11,187 exterior cells spanning X -57..61 and Y -43..50, and its NAM0/NAM9
are `-233472, -176128 .. 253952, 208896` -- the bounding box of exactly those
cells, all four numbers to the unit. The mod proves it a second time:
it AUTHORS seven new Tamriel cells for its outlying gates -- (-68,53)
(-37,64) (-15,64) (-5,70) (16,64) (46,60) (53,54) -- and its NAM0/NAM9 are
exactly their bounding box: `-278528` is the west edge of cell -68 and `290816`
the north edge of cell 70, to the unit. Vanilla reaches only X >= -57, Y <= 51.

Measured consequence with the bounds reverted (2026-08-28, reported from game):
the **Skyrim -> Azurian Sea** gate, the mod's only one, is at `-277223, 218496`
= cell **(-68, 53)** -- 11 cells west and 2 north of the vanilla limit. Its cell
never loads, so the gate's `OnLoad()` never fires and there is no transition,
while the map marker still draws (the map does not need the cell). Of the eight
Tamriel gates only the Solstheim one at `231598, 174372` is inside the vanilla
bounds, so it is the only crossing that works -- Falskaar, Wyrmstooth,
Vominheim, Valefrost, Barbella, Althira and Azurian Sea all fail the same way.

The world MAP stopping short is unrelated and not a bug: that is `MNAM`'s usable
dimensions, cells X -30..40, Y -40..15, vanilla and untouched by the mod. `Sailable Ship Missions.esp` forwards the widened numbers
correctly.

**`MyOwnGamePatch.esp` does not.** It is a CK-saved personal patch (masters
Skyrim, Update, Gray Fox Cowl, KS Hairdo's, WitcherTrio -- no Sailable Ship), it
overrides Tamriel to rename it, and it therefore carries the **vanilla** bounds.
Two plugins overriding one record do not merge, so as an ESP loading after the
ESM it puts `NAM9.y` back to 208896 and the route's gates fall outside the
worldspace. Any third-party mod that touches Tamriel does the same thing; this
is the ordinary shape of the bug, not one plugin's mistake.

The patch now re-asserts the bounds itself: `widen_world_bounds()` collects
every `aaaTeleport` reference by the worldspace it is placed in, and for each
worldspace the mod does NOT own (Tamriel and DLC2SolstheimWorld -- nobody fights
over the five oceans) writes a WRLD override whose bounds enclose every gate
with a two-cell margin. The record copied is Sailable Ship's own, which is not
localized, so its FULL is a literal and no STRINGS lookup is needed.

**It keeps the worldspace's NAME.** Vanilla's Tamriel FULL is an lstring, so it
reads in the player's language; Sailable Ship's override replaces it with the
literal `"Skyrim"`. `local_worldspace_names()` scans `patch_folder/output/` and
`patch_folder/sources/` for another plugin overriding the same worldspace and
carries its FULL through -- for this install that is `MyOwnGamePatch.esp`'s
`Скайрим`. FULL holds no FormID, so this costs no master.

---

## Sailable Ship Missions

`Sailable Ship Missions.esp` (68 KB + a 10 MB BSA; masters Skyrim, Update,
Dragonborn, Sailable Ship) is the cargo-mission addon: reputation, a mock-ship
route preview on the naval map, and one port marker per route.

**Installing it fixes the link-time death** described above -- its BSA holds
`scripts/aaasmutilityscript.pex`, the type every Sailable Ship script declares a
property of. `missing_script_types()` now searches every installed BSA, so the
warning clears instead of firing forever.

It does **not** name Rigmor anywhere: 0 occurrences of `Rigmor` in the ESP and
the BSA, and its own routing is FormList-driven (`aaaSMPorts`,
`aaaSMMainRoutesList`, 7 base worldspaces indexed 0..6) rather than hardcoded.

**But it carries Rigmor GEOMETRY, which the "exactly two things" count above
does not cover.** `aaaSMPortMarkerCyrodiil001` (`040D70E6`) sits in
SouthWestPadomaicOcean cell `036B2D16` -- the same cell as the gate -- with

| property | was | now |
|---|---|---|
| `PosX` | 53632 | 93877 |
| `PosY` | -17822 | -183808 |
| `PosZ` | -1966 | 0 |

`aaaShipTeleportScript.OnLoad()` finds the marker with
`FindClosestReferenceOfTypeFromRef(aaaSMPortMarker, NearestMapMarker, 4000)`,
moves it next to the ship in the destination, enables it and activates it --
and `aaaSMPortMarkerScript.SetMarkerPosition()` then `SetPosition`s it to
`PosX/PosY/PosZ`. Left alone, a cargo run to Cyrodiil drops its port at Rigmor's
dock coordinates: cell (13,-5) in the middle of our map, 1966 units under our
water line. `add_port_marker()` retargets it, choosing the marker by the same
4000-unit proximity rule the mod uses rather than by EditorID, and only when
Missions is actually installed (it is mastered only then).


---

## Confirmed in game, and the route as sailed

**2026-08-28: sailed end to end, arrives correctly in our Cyrodiil.** The chain
of what was wrong and what fixed it, in order: border regions were already off;
`MyOwnGamePatch.esp` was reverting Tamriel's object bounds to vanilla; the
Skyrim -> Azurian Sea gate sits in cell (-68,53), 11 cells west and 2 north of
the vanilla limit, so its cell never loaded and `OnLoad()` never fired -- the
map marker still drew, which is what made it look like a marker bug. Re-
asserting the bounds from this patch was the fix. Confirmed on the way by the
player reaching Y `244308` (cell 59), 35,412 units past vanilla's `208896`.

Skyrim to our Cyrodiil is **three crossings**, each landing at the far side of
the next sea, so every leg is a long diagonal (about 1,133,000 units, 277 cells
in total). FormIDs below are at load-order index `0F`; positions are the gate,
and the landing is where that gate sets the ship down.

| leg | from | heading | gate | distance | lands at |
|---|---|---|---|---|---|
| 0 | Tamriel, sail NW | -- | `0F577AB8` at -277223, 218496 | -- | AzurianSea 199031, 1683 |
| 1 | AzurianSea | 238.7 WSW | `0F6CEA88` at -161644, -217263 | 421,928 | AbeceanSea -128659, 199661 |
| 2 | AbeceanSea | 140.3 SE | `0F6CE68A` at 198967, -195639 | 513,421 | SouthWestPadomaicOcean -194607, 199414 |
| 3 | SWPadomaicOcean | 83.4 E | `0F6E0833` at 2335, 222373 | 198,276 | **TES4Tamriel 93877, -183808, water 0** |

Sea level is -14000 in all five oceans and 0 in our Cyrodiil; leg 3's gate is
the one this patch rewrites, and `ZWaterHeight` is the field that matters.

Debug levers, all measured from the plugin: `aaaShipSlowTP` (`0F8DD4FC`) set to
5 or more prints every transition step and disables the fade -- the fastest way
to see where a crossing stalls; `aaaShipForceAnchor` (`0F86D2F4`) set to 1 makes
the sailing loop anchor and reset it to 0 itself, which is what to do before
`<ship>.moveto player`; `aaaShipEnableCheat` (`0F62C1B9`) is 3x speed;
`aaaShipEnableAllMarkers` (`0F7F75B8`) at 1 lights routes to worlds that are NOT
installed, which is confusing rather than useful.

**`OnLoad()` fires on 3D LOAD, so teleporting into a gate's area does not arm
it** -- and it aborts if the player is within 1000 units or the ship is
anchored. To re-trigger without sailing away and back: `prid <gate>`, `disable`,
`enable`, from more than 1000 units away and under sail.

### Known limits

- **Our Cyrodiil has no terrain LOD.** There is not one `.btr` in
  `output/Oblivion.esm`; the `--lod-only` stage has not been run for this build.
  Sailing works, but the horizon past the loaded cell grid is empty — Sailable
  Ship ships 7,422 `.btr` for its own oceans precisely because you see far.
- The loose `.pex` shadows the mod's own. A Sailable Ship update that changes
  that script needs the patch rebuilt; the build re-extracts from the current
  BSA, so rebuilding is the whole fix.
- Anvil, Cyrodiil's actual port, is not connected. It belongs on the Abecean
  Sea, which the mod has — but all 23 addon slots are full, so a second route
  means extending the hardcoded array and both FormLists (see above).
- Border regions were already off in that install (`GetINISetting
  "bBorderRegionsEnabled:General"` returned 0), so the shipped INI is belt and
  braces, not the thing that unblocked it. The BOUNDS were the whole bug.
