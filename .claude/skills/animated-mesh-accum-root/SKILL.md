---
name: animated-mesh-accum-root
description: >-
  Diagnosis and the fix for converted Oblivion doors (and gates, portcullises,
  sconces, traps) that swing through their own hinge into the wall, or stand
  rotated well away from their frame, while most doors in the same cell are
  fine. Covers Gamebryo's accum-root / NonAccum pose split, why the clip
  re-applies the accum root's authored transform so keeping it in the scene
  graph applies it TWICE, the two shapes the defect takes (accum root == the
  scene root, whose identity-pose entry has to be deleted; accum root == a
  child, whose entry is the clip's root-motion channel), the structural fix
  that is correct under either reading of that entry, the measured scope, and
  the two tools that measure and rebuild it. Use when an animated converted
  mesh is in the wrong place or orientation once its animation plays, when
  touching the NiControllerManager / rotation-wrap passes in nif_converter, or
  when you need to verify an animated mesh's world pose against its Oblivion
  source.
---

# Animated meshes: an accum root's transform is applied twice

**Status: FIXED 2026-08-28, CONFIRMED IN GAME 2026-08-29.** Measured against
`export/Oblivion.esm/meshes` and `output/Oblivion.esm/meshes/tes4`.

**Symptom (in game):** in some interiors a door is rotated wrongly or drives
into the wall; most doors in the same cell are fine. Reported for Five Claws
Lodge (Leyawiin) and Olav's Tap and Tack (Bruma).

---

## 1. How Oblivion authors an animated object

The exporter splits the pose in two.

* The node named by the sequence's `target_name` — the **accum root** — carries
  the authored transform in the scene graph.
* The clip drives **`<accum> NonAccum`** with the **ABSOLUTE** transform, and
  hands the accum root an **identity pose** so its own transform is cancelled
  while the clip runs.

Rest and playback therefore produce the same world pose, by two different
routes. Verified on three doors — the NonAccum curve at the closed frame
reproduces the accum root's authored transform exactly:

| mesh | accum root authored | NonAccum at the closed frame |
|---|---|---|
| `Architecture/LowerClass/doorfulllower02` | root `Rz -179.78°` | `Rx180·Ry180·Rz0.22 = Rz 180.22°` |
| `Architecture/Leyawiin/LeyawinDoorLowerINT01` | child `+74.76°` | `-285.24° ≡ +74.76°` |
| `Architecture/Bravil/BravilLoadDoorLowerINT01` | child `+90°`, `T(0,-42.7,12)` | the same, both channels |

Row-vector convention throughout (`Rz = atan2(m_12, m_11)`); reading it as
`atan2(m_21, m_11)` inverts every sign and makes the table look inconsistent.

---

## 2. Where it dies — two shapes, one defect

**accum root == the SCENE ROOT** (5 of 258 Oblivion door models). Its
identity-pose entry is DELETED by `_process_controller_manager` — it has to be,
a root-targeting entry crashes `BGSGamebryoSequenceGenerator` and 0 vanilla
sequences ship one. Nothing then zeroes the node, and the rotation-wrap pass
re-hangs the same transform on the inner wrapper.

**accum root == a CHILD node** (8 of 258, including every Leyawiin and Bravil
interior door). The entry survives, but it is the sequence's ROOT-MOTION
channel; an engine may write it to the node or consume it for accumulation.

Both collapse to the same thing — the accum root's transform applied TWICE —
and both disappear if the node simply has no transform to apply.

Measured on the shipped output before the fix, at the CLOSED frame:

| mesh | Oblivion | shipped conversion |
|---|---|---|
| `doorfulllower02` leaf | `T(50.58, 3.43)` | `T(-50.57, -3.62)` — mirrored through its own hinge |
| `LeyawinDoorLowerINT01` leaf | `Rz -15.24°` | `Rz +59.51°`, displaced ~41 units |
| `BravilLoadDoorLowerINT01` leaf | `Rz 0°`, `T(0.67,-0.08,10.28)` | `Rz 90°`, `T(42.79,0.67,22.27)` |

Note the shape of this bug: **every block in the file is correct.** A
structural dump passes. Only the pose the engine computes once a clip plays is
wrong, and at REST every one of these meshes is pixel-perfect — which is why it
only shows after a door has been opened once.

---

## 3. The fix

`_sink_accum_root_transform()` in `asset_convert/nif_converter.py`, called
immediately after `_process_controller_manager` at **both** call sites (the
root pass in `_convert_nif`, and the child-manager branch of `_walk_node`).

For a `'transferred'` accum root with a non-identity transform and a `NonAccum`
child: push the node's transform down into **every** one of its children
(world poses, and therefore the rest pose, unchanged), bake it into its own
collision body if it has one, and leave the node identity. The NonAccum child
then holds exactly the transform the clip writes — which is also how vanilla
Skyrim authors its animated doors.

At the ROOT site it must run **BEFORE** the rotation-wrap pass: sinking leaves
the root identity, so no wrapper is built to re-apply what the clip carries.

### Why structural and not another entry rewrite

The two readings of the accum entry disagree, and the evidence is split: the
arena-crowd finding (`_accum_root_mode`, verified in the live engine
2026-08-18) says the pose IS applied to the node, while the door geometry says
it is not. **Sinking satisfies both** — the node is identity either way. Do not
re-litigate which engine reading is true; the fix does not depend on it.

Gated on `'transferred'` only (`_accum_root_mode`): an `'orphan'` accum root is
the one thing nothing else carries, and zeroing it collapses the node. Skinned
meshes are excluded — an actor rig's `Bip01` pose is its bind pose and its
clips go through the behaviour graph, not this path.

---

## 3b. The ordering trap (found 2026-08-29)

`_accum_root_mode` decides 'transferred' vs 'orphan' from the NonAccum entry's
interpolator — and `_process_controller_manager` **sentinels a data-less
interpolator's rotation to −FLT_MAX**. Classify after it and a NonAccum *pose*
reads as a channel carrying nothing, so the accum root is called 'orphan' and
skipped.

The sink ran immediately after that pass at both call sites. Measured:
**18 of 58 sunk, 40 silently skipped** — every sconce, `benirusdoor01`, both
Oblivion gates. The survivors were the meshes whose NonAccum entry is a real
KEY LIST: `doorfulllower02` and the Leyawiin/Bravil doors, i.e. precisely the
three the first report named, which is why the fix looked complete.

`_transferred_accum_roots()` now runs BEFORE `_process_controller_manager` at
both sites and the names are handed down. If a sweep reports 18 rather than 58,
the meshes predate this.

## 4. Measured scope

**92 meshes in Oblivion.esm, of which 58 ship** — the other 34 are `menus/`
(28) and `creatures/` (3 + others), both in `SKIP_PATHS`. The Elsweyr asset
tree (1,583 NIFs) contains **none**.

Doors and gates (14), sconces and lamps (15), traps and mechanisms (11),
effects and props (18). Every inn door the user reported is in there.

---

## 5. Verifying

Two tools were built for this and both belong to this workflow:

```bash
# 1. Which meshes are wrong, at rest and at every sequence's end frame,
#    under BOTH readings of the accum entry.  Non-zero exit if anything moved.
python tools/nif/anim_pose_diff.py -f Oblivion.esm --list <hits> --both
python tools/nif/anim_pose_diff.py <source.nif> <converted.nif> --both -v

# 2. Rebuild only those meshes, into the real output tree, through the same
#    code path the mesh phase uses.  Always --dry-run first.
python tools/nif/convert_meshes_subset.py -f Oblivion.esm --list <hits> --dry-run
python tools/nif/convert_meshes_subset.py -f Oblivion.esm --list <hits>
```

```bash
# 3. Ship the whole class as LOOSE meshes -- no BSA repack, no re-deploy.
#    The set is derived from the mark the pass leaves, never listed.
python tools/patch/build_patch.py --patch doors --plugins Oblivion.esm [--dry-run]
```

🛑 **A full `--meshes-only` is ~20,000 meshes and many minutes at 100% CPU.**
This change touches 58. Use the subset tool.

**Did the pass run?** The mesh phase prints it — `Detailed stats: ... Accum
roots sunk=N` (`stats['accum_sunk']`, rolled up from each mesh's
`accum_roots_sunk`). Before 2026-08-28 the pass was completely silent, which
is what makes a run look like it never applied the fix. To audit the SHIPPED
tree instead of the run, look for any accum root that still has a non-identity
transform while owning a `<name> NonAccum` child: the only legitimate hits are
skinned rigs (`arenaspectator*`, excluded on purpose) and `'orphan'` accum
roots (`clawstandcontainer`, `siegecrawlerdeath`).

Result of the sweep after the fix: **58 pairs compared, 0 regressions.** Eight
meshes still differ (`seflamesofagnon*` ×5, `oblivioncitadelfirecolumn01`,
`oblivionwargateani02`, `siegecrawlerdeathsigil`) — they differ **identically
in the pre-fix output**, i.e. they are the separate, pre-existing billboard
axis behaviour. Do not chase them here.

Regression test: `tests/test_asset_convert.py::TestAccumRootTransformSunk` —
three doors, one scene-root accum and two child accums, asserting the accum
root ships identity and the NonAccum child absorbed its pose.

In game: open a door in Olav's Tap and Tack or Five Claws Lodge, close it,
leave and come back. The leaf should fill its frame and swing away from the
wall. **Done 2026-08-29 and the doors are correct** — the user installed the
rebuilt meshes as LOOSE overrides, which is also the quickest way to retest
this class without waiting on a BSA repack.

---

## 6. Things that are NOT this bug

* **`BrumaOlavsRentBed.SetOwnership Sthasa`** in `PublicanBrumaOlavsTapandTackOlav`
  — Sthasa is the Border Watch innkeeper. That is a Bethesda copy-paste bug in
  the ORIGINAL script and the conversion is faithful. Leave it.
* The **rotation-wrap pass** (`stats['root_rotation_baked']`, the inner NiNode
  that inherits the root's name) is correct and load-bearing for static meshes;
  Skyrim ignores a BSFadeNode root's own rotation. Sinking simply means the
  wrapper is no longer built for these 58.
* **Billboard nodes losing their authored rotation** is deliberate — a
  NiBillboardNode discards its rotation at runtime. See
  `docs/nif_conversion_notes.md`.

Full write-up: `docs/nif_conversion_notes.md`, "An accum root's transform must
be SUNK onto NonAccum".
