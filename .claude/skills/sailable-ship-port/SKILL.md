---
name: sailable-ship-port
description: >-
  Build and extend MyOwnTamrielShipPatch.esp — the patch that lands Sailable
  Ship's sea route in the converted Cyrodiil instead of Rigmor of Cyrodiil, so
  the player can sail a real ship between Skyrim and the converted world.
  Covers how Sailable Ship actually works (a Papyrus translateTo loop, not
  physics; a home-made wind model; sea gates whose script properties ARE the
  destination; a runtime-built return gate), the 23-slot hardcoded
  addon-worldspace table and why it is full, the three places the mod family
  carries Rigmor, the border region and the worldspace object bounds that
  stand between the player and every sea gate, why the compiled script is
  byte-patched instead
  of recompiled, how the landing point is verified against real terrain, and
  the recipe for retargeting another route or adding a second port. Use when
  working on sea travel between the converted world and Skyrim, when the
  Cyrodiil route does not appear or lands wrongly, when adding an Anvil or
  other port, or when any mod hardcodes another plugin's name and FormID that
  needs pointing at one of ours.
---

# The Sailable Ship port

Points **Sailable Ship** (ziher, v1.12, Nexus 72070) at our converted Cyrodiil.
Built, shipping and **confirmed in game** (2026-08-28): sailed Skyrim ->
Azurian Sea -> Abecean Sea -> SW Padomaic Ocean -> our Cyrodiil, arriving in
Topal Bay. The route table and the debug levers are in
[docs/sailable_ship_port.md](../../../docs/sailable_ship_port.md).

```bash
python tools/patch/build_patch.py --patch ship --plugins Oblivion.esm
python tools/patch/assign_ship_port.py --plugins Oblivion.esm --dry-run
python tools/patch/build_patch.py --patch ship --plugins Oblivion.esm --landing 93877 -183808
```

Also the **Sailable Ship (Cyrodiil route)** button in the GUI's Patches section.

| Piece | Where |
|---|---|
| The pass | `tools/patch/assign_ship_port.py` |
| The `.pex` editor | `tools/patch/pex_patch.py` |
| How the mod works, in full | [docs/sailable_ship_port.md](../../../docs/sailable_ship_port.md) |
| The mod itself | `patch_folder/sources/Sailable Ship/` — it ships **all 32 Papyrus sources** in its BSA under `scripts/source/` |

Read the mod's own scripts rather than guessing:
`asset_convert.bsa_extract.list_bsa_files` + `read_bsa_files`.

Output: `patch_folder/output/MyOwnTamrielShipPatch.esp` plus
`patch_folder/output/ship_scripts/aaaShipUtilityScript.pex`, zipped together
into `output/Finished Mods/` as the ESP and `Scripts/aaaShipUtilityScript.pex`.

---

## The one fact the whole patch rests on

**A sea gate's script properties ARE the destination.** A gate is a placed
`aaaTeleport` activator carrying `aaaShipTeleportScript`, and everything about
where it goes is four properties on that one reference:

| property | meaning |
|---|---|
| `LandingWorldSpace` | a console command string, `"CenterOnWorld <EditorID> x y"` |
| `Xpos`, `Ypos` | where the ship is set down in that worldspace |
| `ZWaterHeight` | that worldspace's sea level |
| `LandingWorldspaceIndex` | the slot in the addon table below |

Shared properties (`aaaShipUtility`, `MapMarker`, `aaaPlayerIsTeleportingFaction`,
`aaaShipHeight`) live on the **base ACTI**, not on the references — which is why
the override is three subrecords long and only `VMAD` changes.

`OnLoad()` fades out, sets `bDisablePlayerCollision:Havok`, runs the console
command through **ConsoleUtil** (a hard dependency — 11 `ExecuteCommand` calls
mod-wide), `SetPosition`s the player, `MoveTo`s the ship after them, then
`MoveShipParts()`.

## Two barriers stand between the player and every sea gate

Measured 2026-08-28 — this is what "the route cannot be tested, the world
border is still there" turned out to be. Neither is anything the route edit
touches.

**1. `BorderRegionSkyrim` (`000C5859`)** is the only REGN in Skyrim.esm with
record-header flag `0x40` ("Border Region" in the CK region dialog). Its
polygon over Tamriel reaches Y `169851`; the nearest of the mod's eight Tamriel
gates is at Y `174372`, so **all of them are outside it** and sailing towards
one gets "You cannot go that way". Only `bBorderRegionsEnabled=0` disables it —
Skyrim reads `Data/<plugin name>.ini` for every loaded plugin (`%sdata/%s.ini`
in the exe), which is how the mod ships `Sailable Ship.ini`. The patch now
ships its own `MyOwnTamrielShipPatch.ini` saying the same thing. **Do not
"fix" this by overriding the REGN**: its `RDMP` map name is an lstring into
Skyrim.esm's STRINGS and it is the only region naming the Tamriel worldspace,
so a non-localized override either corrupts that name or freezes one language.

**2. The worldspace object bounds.** Vanilla Tamriel is NAM0 `(-233472,
-176128)` .. NAM9 `(253952, 208896)`; **six of the eight gates are outside
that**, out to Y `289334` and X `-277223`, which is why Sailable Ship overrides
the Tamriel WRLD with widened bounds at all. Any later plugin overriding
Tamriel puts the vanilla numbers back — `MyOwnGamePatch.esp` does exactly that,
because it was CK-saved to rename the worldspace and never mastered Sailable
Ship. `widen_world_bounds()` re-asserts the bounds for every non-mod-owned
worldspace holding a gate, and `local_worldspace_names()` carries another local
patch's FULL through so re-asserting them does not un-translate "Скайрим".

**Our own worldspace proves nothing about the INI**: the importer never sets
flag `0x40`, so the converted plugin simply has no border region.

## Three things carry Rigmor, not two

Measured by scanning every subrecord and every script for `Rigmor`/`Cyrodiil`:

1. `LandingWorldSpace` on REFR **`036E0833`** (SouthWestPadomaicOcean, cell
   (0,54)): `"CenterOnWorld RigmorCyrodiil 0 0"`.
2. A hardcoded pair in `aaaShipUtilityScript.MakeWorldspaceArrays()`, slot 14:
   `(0x2F4DB2, "RigmorCyrodiil.esm")`. `IsWorldspaceActive()` is nothing but
   `Game.GetFormFromFile(ID, filename) != None`, and that is what decides
   whether the port lights up at all.
3. **In `Sailable Ship Missions.esp`** (which names Rigmor nowhere — 0 string
   hits — but carries its GEOMETRY): `aaaSMPortMarkerCyrodiil001` `040D70E6`,
   in the gate's own cell, whose `PosX/PosY/PosZ` = `53632, -17822, -1966` is
   Rigmor's dock. `aaaShipTeleportScript` moves that marker into the
   destination and activates it, and `aaaSMPortMarkerScript.SetMarkerPosition()`
   then `SetPosition`s it to those coordinates — the middle of our map, under
   our water line. `add_port_marker()` retargets it, picking the marker by the
   same 4000-unit proximity rule the mod uses, and only when Missions is
   installed (it is mastered only then).

Everything else the mod already calls Cyrodiil and needs no edit: the map port
ACTI `aaaShipMapPortCyrodiil`, the marker-name CLFM `aaaMarkerNameAddon07`
("Cyrodiil Route"), and the map marker's own FULL.

## The return gate is built at runtime — never touch it

Each gate is one of a **quartet** within ~550 units, all initially disabled:

| ref | role |
|---|---|
| `036E0833` | outbound gate → the addon world |
| `036E0835` | outbound map marker, "Cyrodiil Route" |
| `036E0832` | **return** gate → `CenterOnWorld SouthWestPadomaicOcean 0 0` |
| `036E0834` | return map marker |

On arrival the script finds the nearest map marker to itself, then the nearest
`aaaTeleport` to *that*, and **moves both into the destination next to the ship
and enables them**. The return path is therefore created by geometry and never
names a worldspace. Retargeting a route must not touch it.

## The addon table, and why it is full

`MakeWorldspaceArrays()` hardcodes 23 third-party worldspaces. Indexing is
sequential — 0 Skyrim, 1 Solstheim, 2–6 the five ocean worldspaces, 7+ addons —
and three structures depend on the offset:

| FormList | size | shape |
|---|---|---|
| `aaaTeleportMarkersAddOn` | 46 | **2 per addon**: [gate, map marker] — hence `iIndex / 2` |
| `aaaShipMapWorldspaceObjects` | 30 | 7 base + 23 addons — hence `index > 6` / `index - 7` |
| `aaaTeleportMarkers` | 28 | the base routes |

**All 23 slots are taken.** A 24th route means extending the hardcoded array
*and* both FormLists, preserving the pairing and the offset of 7.

There is an escape hatch worth knowing: if the global `aaaShipEnableAllMarkers`
is 1, `aaaStudyCharts` calls `BatchEnabler(aaaTeleportMarkersAddOn)` and lights
every addon port unconditionally, skipping `IsWorldspaceActive` entirely. It
works without touching any script, but also lights ports for mods that are not
installed.

---

## Why the compiled script is byte-patched, not recompiled

The sources ship and the CK compiler is on this machine, so this looks like the
wrong call until you read the script: `aaaShipUtilityScript.psc` declares
`aaaSMUtilityScript Property SMUtil`, a type that lives in the **optional**
`Sailable Ship Missions.esp`, whose sources the mod does not ship. Recompiling
needs a hand-written stub of that addon's API, and any signature guessed wrong
silently breaks Missions for everyone who has it.

Rewriting two literals leaves every other byte — Missions interop included —
untouched. Measured diff: 3 bytes in the code section, −6 in the string table.

`tools/patch/pex_patch.py` does it, and is reusable for any mod that hardcodes
another plugin's name plus a FormID:

- Skyrim `.pex` is **big-endian**; strings are u16-length.
- `--set-string` rewrites a **table entry**, so every reference (they are all by
  index) follows and the rest of the file is copied verbatim.
- Integer literals are inline operands (`03` + big-endian int32), so
  `--set-int` matches a byte pattern — and **refuses** if the value occurs zero
  or several times. Cross-check the `.psc` for the same uniqueness first.
- `--expect-string` asserts a name is in the table: the cheap proof this is the
  script you meant.

---

## What the pass reads instead of assuming

| Question | Authored answer |
|---|---|
| Which reference is the gate? | Searched for the `LandingWorldSpace` property naming the worldspace being replaced — **not** a hardcoded FormID, so a mod update that moves the record still works |
| Which worldspace do we land in? | The converted plugin's own overworld, local FormID `00003C` (TES4 gives every master's overworld that id); `--worldspace` overrides |
| What is the sea level? | That WRLD's `DNAM` default water height — ours is **0**, Rigmor's was **-3150** |
| Is the landing point water? | Its cell's `LAND` `VHGT` is decoded and compared to the water line; terrain at or above it **aborts the build** |
| Where do we land by default? | The coordinates the route already carries. Rigmor's Cyrodiil is the real Cyrodiil geography at the same scale, so they transfer unchanged |

Measured for the default landing `93877, -183808` = cell **(22,-45)**, Topal Bay
south of Leyawiin: seabed -5,992..-4,472, no `XCLW` (so worldspace default 0),
nearest object 1,508 units away and 4,600 below the surface.

Rigmor vs ours, for orientation: Weye (2,17) vs (0,15); Anvil (-47,-9) vs
(-49,-10); Kvatch (-33,-3) vs (-36,-7). One to four cells apart, same
orientation and scale.

---

## Verification

The structural gate `verify_npc_patch.py` passes **vacuously** here — its
fidelity and master checks only look at `NPC_`, and this patch has none. Do not
read its "all checks passed" as coverage. The real checks are in the pass
itself and run at the end of every build:

```
masters      Sailable Ship's masters, then Sailable Ship, then Missions if installed
references   exactly the gate, plus the Missions port marker when there is one
untouched    every non-VMAD subrecord byte-identical to the source
field order  unchanged
properties   the property SET is unchanged
route        the three values are exactly what was asked for
port marker  PosX/PosY/PosZ are the landing and the sea level
cell/wrld parent   copied verbatim (the widened worldspaces excepted)
gate bounds  every gate lies inside the bounds the patch writes
pex strings  951 entries, new name in, old name out
pex code     3 bytes differ, all within one int operand
```

Idempotence is not covered by those — `cmp` the ESP and the `.pex` against a
re-run (both are byte-identical today).

Structural facts this patch relies on: the gate sits in a **persistent**
children group (type 8), so **no ONAM entry is needed** — that requirement is
type 9 only. The CELL and WRLD above it must exist as plain overrides or the
nested reference does not resolve.

---

## Recipes

**Retarget for a different converted plugin.** Nothing is Oblivion-specific:
`--plugins <plugin>` picks the first ticked plugin that has an overworld, and
the pex's new plugin name and FormID are derived from it.

**Move the landing point.** `--landing X Y`. The anchorage check will refuse a
spot that is land. The `CenterOnWorld` cell arguments are recomputed from it, so
the engine loads directly at the target cell rather than at (0,0).

**Add a second port (e.g. Anvil on the Abecean Sea).** This is the expensive
one, because there is no free slot:
1. Extend `WorldSpaceID` / `WorldspaceFilename` in the script — which means the
   `.pex` grows a table entry, so `pex_patch.py` is no longer enough and the
   stub problem above has to be solved properly.
2. Add a gate + map marker pair to `aaaTeleportMarkersAddOn` (keeping 2-per) and
   a map object to `aaaShipMapWorldspaceObjects` (keeping the offset of 7).
3. Place the quartet — outbound gate, outbound marker, return gate, return
   marker — within ~550 units in the Abecean Sea, all initially disabled.

---

## 🛑 The mod is script-dead without Sailable Ship Missions

**Check this FIRST if anything about the ship does not work** — cabin, helm,
transitions, the route. Diagnosed 2026-08-28 from the Papyrus log.

`aaaShipUtilityScript`, `aaaShipMapShipScript` and `aaaShipSailInteriorScript`
declare a property typed `aaaSMUtilityScript`, which ships only with the
optional **Sailable Ship Missions.esp**. It is in neither the base download nor
`Sailable Ship.bsa` (measured: 32 `.pex` in the BSA, none `aaasm*`).

**Papyrus resolves a property's TYPE at link time even when the property is
never assigned.** One missing file therefore takes down `aaaShipUtilityScript`,
and with it every script holding an `aaaShipUtilityScript` property — which is
all of them. The mod handles Missions being absent at runtime (`CheckAddons()`)
but not at link time. Log signature:

```
Cannot open store for class "aaasmutilityscript", missing file?
Error: Unable to link type of property "ShipValues" on object "aaaShipSail"
warning: Property LandingWorldSpace on script aaaShipTeleportScript ... cannot be initialized
```

Fix: install Sailable Ship Missions, or drop a compiled `aaaSMUtilityScript`
stub in `Data/Scripts/`. **This patch does not ship a stub** — a loose one would
shadow the real script for anyone who does install Missions.

`assign_ship_port.py` warns about this at build time (`warn_missing_types`), so
never conclude "the patch broke it" from a dead ship before reading that
warning and the log.

**Do not suspect the retargeted `.pex` for this.** It differs from the BSA
original by exactly one string-table entry and 3 bytes inside one int literal,
it parses end to end, and the BSA original names `aaasmutilityscript` the same
way. That was measured, not argued.

## Install requirements and open points

- The patch mod must sit **below Sailable Ship** in MO2's left pane, or the
  loose `.pex` will not win over the BSA copy.
- **ConsoleUtil is required** by the mod itself. Without it nothing transitions,
  and the in-game "Naval Charts" book says so.
- `RigmorCyrodiil.esm` now competes for slot 14: if installed, its own route
  becomes unreachable.
- The port is switched on by reading the **Naval Charts** book in game.
- **Our Cyrodiil has no terrain LOD** — not one `.btr` in `output/Oblivion.esm`;
  `--lod-only` has not been run for this build. Sailing works, but the horizon
  past the loaded cell grid is empty. Sailable Ship ships 7,422 `.btr` for its
  own oceans precisely because you see far. This is the most likely first
  complaint from an in-game test.
- A Sailable Ship update that changes `aaaShipUtilityScript` needs the patch
  rebuilt; the build re-extracts from the current BSA, so rebuilding is the
  whole fix.
- The three-leg route, the arrival points and the console levers for testing it
  are in the doc; `OnLoad()` fires on 3D load, so a teleport into a gate's area
  does not arm it -- `prid <gate>` / `disable` / `enable` from >1000 units away,
  under sail, is the way to re-trigger one.
