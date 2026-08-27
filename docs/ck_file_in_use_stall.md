# The CK "File in use" stall on ElsweyrAnequina.esp (2026-08-27)

Loading `ElsweyrAnequina.esp` into the Creation Kit looks like a very slow load.
It is not slow. **The CK stops dead** at the end of the load and waits forever
on a modal retry dialog for a file it can never open.

Measured on the live process (pid 28104, CK 1.6.1378.1 under MO2):

| wall clock | process CPU | dialog timer |
|---|---|---|
| 21:53:10 | 20.0 s | `01:23 Waiting` |
| 21:53:30 | 20.0 s | `06:57 Waiting` |
| 22:11    | 21.7 s | `24:12 Waiting` |

24 minutes of wall time for 1.7 seconds of CPU. A load that is genuinely slow
pegs a core; this one is parked.

## 🛑 The CK actually in use is the SSE copy, not the SkyrimVR one

`D:\SteamLibrary\steamapps\common\Skyrim Special Edition\CreationKit.exe`,
**v1.6.1378.1**, CKPE 0.6 build 267, launched through **MO2**
(`D:\Skyrim VR Mods\MO\ModOrganizer.exe`), so `Data\` is virtualized and the
on-disk `Data\` is empty. Every RVA in this document is from that binary.
[ck_reference_init_hang.md](ck_reference_init_hang.md) says the CK in use lives
in the SkyrimVR folder at 1.5.73 — that was true in 2026-08 and is not true now.
Check the title bar or `ckpe.log`'s `Creation Kit Skyrim Special Edition [vX]`
line before trusting any RVA map.

## What the process is doing

`tools/live/win_stackwalk.py --pid <pid> --windows` shows the whole shape in one
capture — the window list is what names the problem, not the stacks:

```
0x00070666 tid=24180 [vis] '#32770' 'File in use'
    Static 'D:\SteamLibrary\steamapps\common\Skyrim Special Edition\ElsweyrAnequina.esp'
    Static '06:57 Waiting'
    Button 'Cancel'
0x00040c4c tid=27424 [vis] '#32770' 'Loading...'
    Static 'Validating forms...'
```

Note the path: the **game root**, not `Data\`. No `.esp` exists in the game root,
and MO2's VFS maps `Data\`, not the root — so the file the CK is waiting for can
never appear, and the retry timer just counts up.

Worker thread 24180 (the load thread), innermost first:

| frame | RVA | source file / strings |
|---|---|---|
| #5 | `0x1647960` | `fileio\tesfile.cpp` — builds `%s%s` from (dir, name), `fopen(path,"rb")`, and on failure shows **dialog resource 244** = "File in use" |
| #6 | `0x1650a70` | `"File '%s' is not a valid TES file."` |
| #7 | `0x1646cc0` | — |
| #8 | `0x164e580` | `fileio\tesfile.cpp` |
| #9 | `0x1614e70` | `fileio\tesdatahandler.cpp` — the end-of-load pass that **reopens plugin files to write fixes back** (`AUTOEDIT-removed invalid forms from file`, `badformfixes`) |
| #10 | `0x1629960` | the load-phase driver (`Loading Files...Initializing...`, `Initializing References...`, `Loading Files...Done!`) |
| #11 | `0x16209f0` | `fileio\tesdatahandler.cpp` — load-file driver |

The main thread (27424) is idle in its own modal `Loading...` dialog, so nothing
else can progress either.

Reading the blocked frame's arguments out of the process
(`[rsp+0x470]` is `TESFile* this`, spilled before `sub rsp,0x468`) confirms it:

```
[sp+0x470] = 0x1845f0c90  TESFile 'ElsweyrAnequina.esp'   <- a NEW TESFile, built for the reopen
[sp+0x120] str 'D:\SteamLibrary\...\Skyrim Special Edition\ElsweyrAnequina.esp'
```

while the pass's own loop variable one frame up is the *loaded* TESFile for the
same plugin (`0x2f45af10`). So this is a **second** open of a file the CK already
read successfully — the rewrite pass, not the load.

Form validation had essentially finished: the driver at `0x1622b30` runs the
sub-phases Large Ref Data → Materials → **Movement Type** → … → **Books** →
`Finished validating forms`, and the log's last entries are the Books ones.

## Why ElsweyrAnequina.esp and not Oblivion.esm

`<game root>\Oblivion.esm` does not exist either, so if this pass covered every
loaded file the CK would have parked on Oblivion.esm first — and Oblivion.esm on
its own has loaded to completion before. The pass therefore only walks files the
CK decided need rewriting, and ElsweyrAnequina.esp is on that list.

🛑 **What puts it on that list is NOT proven.** The one flag that gates the
"Invalid forms were encountered on load" message (`0x3a9a6c2`, written only by
`tesform.cpp`'s SetFormID-collision path at `0x16a4771`) was *not* set — no
`SetFormID bashing` line appears in the log. The container the pass walks
(`TESDataHandler+0xD90`) did not decode as a plain `BSTArray`. The correlation
below is strong and the underlying data defect is real and worth fixing on its
own merits, but "fix the duplicates and the stall goes away" is a prediction,
not a measurement.

## The real data defect: master-blind generated records

Pulled from the CK's own log (the file is exclusively locked during a load; read
the `RTEDITLOG` child `RICHEDIT50W` with `EM_GETTEXTRANGE` instead — plain
`WM_GETTEXT` on 500k chars exceeds any sane timeout).

Load order this session: `Oblivion.esm`, `Skyrim.esm`, `MyOwnGamePatch.esp`
(active), `Update.esm`, `Dawnguard.esm`, `KS Hairdo's.esp`, `WitcherTrio.esp`,
`ElsweyrAnequina.esp` — so **03 = Oblivion.esm, 06 = ElsweyrAnequina.esp**.

955 `[EDITOR] Editor ID ... is not unique ... will be set to <X>DUPLICATE001`
messages, split by file:

| file | renames |
|---|---|
| 06 ElsweyrAnequina.esp | **682** |
| 03 Oblivion.esm | 273 (collisions against vanilla Skyrim — separate, older issue) |

ElsweyrAnequina.esp's 682, by record type:

| type | count | generator |
|---|---|---|
| IDLE | 513 | `creature_idles.build_creature_idles` |
| CLFM | 46 | |
| MOVT | 40 | `creature_races._build_movts` |
| MGEF | 40 | |
| VTYP | 18 | `creature_races.build_creature_voice_types` |
| BPTD | 16 | `creature_races.build_creature_body_parts` |
| SOPM | 5 | |
| FACT | 2 | |
| LCTN | 1 | |
| DLVW | 1 | |

MOVT is the only one of these the CK treats as an error rather than a rename,
because a movement type's `MNAM` must be unique — 40 `[FORMS] Movement type ID
'X' ... is already in use by movement type 'X_MT' ... One of these needs its
Material Name changed.`

Measured straight from the binaries, not from the log
(`temp/movt_dupe_census.py`):

```
output/Update_ElsweyrAnequina/ElsweyrAnequina.esp: 55 MOVT
output/Oblivion.esm/Oblivion.esm:                  92 MOVT
MNAM present in BOTH: 40        e.g. TES4ratDefault  plugin 022DE654 TES4ratDefault_MT
                                                     master 016EE654 TES4ratDefault_MT
MNAM only in the plugin: 15     camel, elephant, ragasha, runningbird, spider,
                                pahmer, werecrocodile — the genuinely new ones
```

Identical `MNAM` **and** identical `EDID`; only the FormID differs.

### Cause

`tes5_import/creature_races.py`:

- `_load_projects` (~line 1146) deliberately **inherits creature projects from
  the masters**, so an ESP whose CREA reuse Oblivion.esm's creature folders
  (`rat`, `dog`, `horse`, `goblin`, `troll`, …) gets those folders in
  `_PROJECTS`. That inheritance is correct and was itself a fix.
- `build_creature_races` (line ~1247) then calls `_build_movts(writer, folder,
  proj)` and `build_creature_idles(...)` once per folder **without ever asking
  whether a master already owns those records**. `_build_movts` has no
  `master_export` parameter and does no lookup; it just writes
  `derive_formid('MOVT', (folder, mnam))` into the current plugin.

This is textbook [master-export blindness](../CLAUDE.md#master-blindness): the
generator indexes only the current plugin and re-creates what the master already
provides. `build_creature_races` *does* receive `master_export` (it passes it to
`load_creature_item_index`), so the information is already in hand at the call
site.

## The fix (2026-08-27) — built and measured

Sharing runs through the manifest that already exists for exactly this purpose
(`tes5_import/master_manifest.py`: *"a plugin that OVERRIDES such a record must
point at the MASTER's companions — minting its own would duplicate content the
master already has"*). It only ever covered records keyed on a **source
record**; the creature generators key on a **folder**, which has no source
record, so they fell outside it.

* `PluginWriter.derive_shared(site, key) -> (fid, from_master)` — returns the
  master's id when it owns the key, and the caller then does **not** write the
  record. `derive_formid` stays pure: answering with a master's id from it would
  silently turn every unaudited call site into an override of the master's
  record.
* The manifest gains a `derived` section, `{derive payload -> id}`, restated
  into the dependent plugin's index space by the same `out_map` that already
  handles `fid`/`companions`. The section is optional — a manifest written
  before it existed does not fail the build, it prints which master to
  re-convert and falls back to minting our own.
* `creature_races.share_folder_fid()` gates on **both** conditions: the folder
  was inherited wholesale (`_INHERITED_FOLDERS`, recorded by `_load_projects`
  before `own` is merged in) **and** the master's manifest actually records the
  id. The second matters: inferring "the master surely generated one too" would
  ship a creature with no movement type at all against an older master build,
  which is a creature that cannot move.
* Applied to MOVT, the IDLE action tree, VTYP, BPTD and the death-pile ACTI.

### Measured after rebuilding both plugins

| | before | after |
|---|---|---|
| MNAM shared with Oblivion.esm | 40 | **0** |
| MOVT in ElsweyrAnequina.esp | 55 | 15 (exactly its 7 own creature folders) |
| records reused from the master | 0 | **587** (513 IDLE, 40 MOVT, 18 VTYP, 16 BPTD) |
| FormIDs moved | — | **0** |

Drift was checked by recovering 695 of the old build's ids from the CK log
(`<EditorID> (06XXXXXX)`) and matching them by EditorID against the rebuilt
plugin: 108 surviving records all kept their id, 587 are absent, and every one
of the 587 is a record the CK had been renaming. Compare the **low 24 bits
only** — the log's index byte is that session's runtime load-order slot (06),
not the plugin's own index (02).

`tools/validate/plugin_load_audit.py ElsweyrAnequina.esp` → 175,970 records,
60 top groups, CLEAN. Regression test: `tests/test_shared_derived_records.py`.

🛑 The 587 records are **gone from the plugin**, which is a save-compatibility
change even though no surviving id moved.

### Not fixed: 95 duplicates from other generators

The same class, none of them load errors — the CK renames them and moves on.
Measured from the same log: CLFM 46, MGEF 40, SOPM 5, FACT 2, LCTN 1, DLVW 1.

`CLFM_HAIR` (keyed on an RGB triple), `SOPM` (rounded min/max distance +
stereo) and `MGEF_AIMED` (a vanilla-table lookup) are pure functions of their
key, so `derive_shared` applies to them unchanged. **`MGEF_AV` is not**: its
DATA/FULL/DNAM are built from `by_code[code]` — this plugin's own source MGEF
record — so a plugin that ships a different base effect must keep its own
variant. That one needs an audit before it can share, and MGEF is referenced by
FormID from SPEL/ENCH, so getting it wrong changes magic behaviour.

## Getting a stuck CK moving again

The dialog's `Cancel` button is the only exit; the retry never succeeds because
the path does not exist. Cancelling makes `tesfile.cpp` fall through to its
`errno` switch (2 = `ENOENT`, 13 = `EACCES`) and return failure to the rewrite
pass, so the load can finish without the auto-fix being written back.

## Tooling this needed

- `tools/live/win_stackwalk.py --pid N --windows` — the window tree named the
  problem; no stack walk states "a modal dialog is waiting for a click" as
  plainly as seeing the dialog in the list.
- `tools/live/win_stackwalk.py --sample` (added for this) — a sampling profiler,
  because `--watch` triggers on CPU going flat and is useless when the question
  is "busy or stopped?". Here it answered by *not* finding any CPU at all.
- `tools/disasm/skyrim_disasm.py --exe <ck> --func <rva>` per frame, collecting
  the `lea rcx,[rip+...]` string references inside each function: the Bethesda
  source paths and diagnostic strings name every frame in the chain without
  PDBs. `temp/ck_frame_srcnames.py` is the throwaway that did it.
- `tools/disasm/skyrim_xref.py --xref <rva>` to find the single writer of the
  invalid-forms flag.
