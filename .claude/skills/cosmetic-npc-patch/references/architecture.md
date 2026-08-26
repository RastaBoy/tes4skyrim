# Architecture

## `tools/plugin_patch.py` — the library

### `SourcePlugin(path, want_types)`

Reads a plugin once and indexes the record types you ask for.

```python
src = SourcePlugin('output/Oblivion.esm/Oblivion.esm', {'NPC_', 'CELL', 'ACHR', 'WRLD'})
src.masters                      # ['Skyrim.esm']
src.by_type['NPC_'][fid]         # (header_bytes, [(sig, payload), ...])
src.parents[fid]                 # (parent_cell, parent_wrld)
```

Reading the 615 MB converted `Oblivion.esm` with four types takes ~2 s. Cheap
enough that no caching is warranted; do not add any.

### `Patch(path)`

```python
patch = Patch('patch_folder/output/MyCosmeticTamrielPatch.esp')
patch.masters                    # the load order, index == FormID high byte
patch.npcs                       # OrderedDict fid -> (header, subs), already-present overrides
patch.records_of('OTFT')         # parsed records of any other group
patch.set_npc(fid, header, subs)
patch.write(out_path)            # -> (size, records, groups)
```

`Patch` keeps every top-level group as **raw bytes** and rebuilds only `NPC_`.
That is what makes the passes compose: a pass that never touches `OTFT` cannot
perturb it, and `write()` re-emits the original bytes verbatim (verified).
`write()` also re-sorts top-level groups into `GROUP_ORDER` and recomputes
`HEDR`.

### The remap

```python
mapping = make_remap(src.masters, patch.masters, src.name)   # {0:0, 1:3}
header, subs = remap_npc_record(*src.by_type['NPC_'][fid], mapping)
```

`remap_npc_record` walks `NPC_FORMID_FIELDS` and the VMAD property tree.
`SystemExit` on an unknown subrecord signature — that is deliberate. Adding a
signature to the map without knowing whether it holds a FormID is how a patch
ships silently broken references.

### `insert_run(subs, sig, payloads, successors)`

Replaces every `sig` subrecord with `payloads`, placed in canonical field order.
See `binary-facts.md` for the `AFTER_DOFT` / `AFTER_PNAM` successor tuples.

---

## A pass

Each `tools/assign_*.py` is a standalone argparse CLI:

1. `Patch(--patch)` → masters, existing overrides, and the lookup tables the
   pass needs from the patch's own records (e.g. OTFT by EditorID).
2. `SourcePlugin(--source)` + `make_remap`.
3. Resolve the curated EditorID lists from `--constants` into patch-space
   FormIDs. **Abort on a name that does not resolve** — a silently skipped
   entry is worse than a failed build.
4. Select the NPCs, from an **authored indicator**, never a name heuristic.
5. Pick per NPC with `sha256(tag:seed:formid)`.
6. `--report` a TSV of every decision, and honor `--dry-run` before writing.
7. For each NPC: reuse `patch.npcs[pfid]` if present, else
   `remap_npc_record(...)`; edit only the owned fields; `patch.set_npc`.
8. `patch.write(--out)`.

Steps 6-7 in that order matter: the report is written before anything is, so a
dry run tells you exactly what a real run would do.

---

## `patch_folder/pipeline.py`

Runs the passes in order via subprocess, printing each command so a pass can be
repeated or tweaked by hand.

- A **full build restarts from `sources/`** — reproducible, and a bad run is
  fixed by re-running, never by undoing.
- A **partial run (`--only`) continues from `output/`** so it keeps the other
  passes' work. Delete `output/` for a clean slate.
- `--seed` is shared by every pass; `--dry-run` propagates.
- Skyrim.esm is auto-located through `asset_convert.skyrim_assets.find_skyrim_data()`
  and handed to the hair pass as `--hdpt-from`, so vanilla head parts can be
  classified. Without it, unresolvable head parts are left in place and counted.

Per-pass knobs that belong to *this* patch rather than to the tools live at the
top of `pipeline.py`: `OUTFIT_RULES`, `DEFAULT_OUTFITS`, `EXCLUDE_RACES`.
