"""A dependent plugin must REUSE a master's folder-keyed generated records.

Some generated records are keyed on something a plugin shares with its master
rather than on one of its own source records — a creature folder, which a
dependent plugin inherits wholesale from `creature_projects.json`. Deriving
those again ships a second copy of a record the master already has.

For most types that is only waste. For MOVT it is a load error: the CK requires
a movement type's MNAM to be unique, and 40 duplicated MOVTs parked the CK on a
modal "File in use" retry dialog forever while loading ElsweyrAnequina.esp
(docs/ck_file_in_use_stall.md) — the load never finished.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tes5_import.writer import PluginWriter, derive_payload
from tes5_import.master_manifest import (MasterManifest, manifest_path,
                                         write_manifest)

# What load_master_manifests builds for a standalone TES4 master converted
# with one new master (Skyrim.esm) prepended: the master's own records sit at
# source index 0 / output index 1, and this plugin names them the same way.
STANDALONE_MASTER_INDEX_MAP = ({0: 0}, {1: 1})

MOVT_KEY = ('MOVT', ('rat', 'TES4ratDefault'))
VTYP_KEY = ('CREA_VTYP', 'rat')
OWN_KEY = ('MOVT', ('pahmer', 'TES4pahmerDefault'))


def _master_with_manifest(tmp_path, drop_derived=False):
    """A converted master plus its manifest on disk. Returns (writer, path)."""
    master = PluginWriter(masters=['Skyrim.esm'])
    for site, key in (MOVT_KEY, VTYP_KEY):
        master.derive_formid(site, key)
    out = str(tmp_path / 'Oblivion.esm')
    path = write_manifest(out, 'Oblivion.esm', master.manifest(),
                          master.derived_map())
    if drop_derived:
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
        del payload['derived']
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    return master, path


def _dependent(path):
    mm = MasterManifest()
    mm.load(path, STANDALONE_MASTER_INDEX_MAP, 'Oblivion.esm')
    dep = PluginWriter(masters=['Skyrim.esm', 'Oblivion.esm'])
    dep.set_master_derived(mm.derived_map())
    return dep, mm


def test_manifest_carries_the_derived_section(tmp_path):
    _, path = _master_with_manifest(tmp_path)
    with open(path, encoding='utf-8') as f:
        payload = json.load(f)
    assert derive_payload(*MOVT_KEY) in payload['derived']


def test_dependent_plugin_reuses_the_masters_id(tmp_path):
    master, path = _master_with_manifest(tmp_path)
    dep, _ = _dependent(path)
    for site, key in (MOVT_KEY, VTYP_KEY):
        fid, from_master = dep.derive_shared(site, key)
        assert from_master, f'{site} was minted again instead of reused'
        assert fid == master.derive_formid(site, key)
        # ...and in the MASTER's index space, not the dependent's
        assert (fid >> 24) & 0xFF == master.own_index


def test_a_key_the_master_lacks_is_still_minted_here(tmp_path):
    _, path = _master_with_manifest(tmp_path)
    dep, _ = _dependent(path)
    fid, from_master = dep.derive_shared(*OWN_KEY)
    assert not from_master
    assert (fid >> 24) & 0xFF == dep.own_index


def test_inherited_ids_are_not_re_exported(tmp_path):
    """A grandchild must resolve an id through the file that OWNS it.

    Re-exporting a master's id in our own manifest would offer it under our
    index map, which names a different file.
    """
    _, path = _master_with_manifest(tmp_path)
    dep, _ = _dependent(path)
    dep.derive_shared(*MOVT_KEY)
    dep.derive_shared(*OWN_KEY)
    exported = dep.derived_map()
    assert derive_payload(*MOVT_KEY) not in exported
    assert derive_payload(*OWN_KEY) in exported


def test_derive_formid_never_returns_a_masters_id(tmp_path):
    """Sharing is opt-in per call site.

    `derive_formid` must stay pure: silently answering with a master's id would
    turn every unaudited caller into an override of the master's record.
    """
    _, path = _master_with_manifest(tmp_path)
    dep, _ = _dependent(path)
    assert (dep.derive_formid(*MOVT_KEY) >> 24) & 0xFF == dep.own_index


def test_manifest_without_the_section_falls_back_and_is_reported(tmp_path):
    """A master converted before this existed must not silently do nothing."""
    _, path = _master_with_manifest(tmp_path, drop_derived=True)
    dep, mm = _dependent(path)
    assert mm.masters_without_derived == ['Oblivion.esm']
    fid, from_master = dep.derive_shared(*MOVT_KEY)
    assert not from_master
    assert (fid >> 24) & 0xFF == dep.own_index


def test_index_map_restates_the_masters_ids(tmp_path):
    """The master's ids arrive in THIS plugin's index space, not its own."""
    master, path = _master_with_manifest(tmp_path)
    mm = MasterManifest()
    # A master sitting at a different slot: output index 1 -> 4 here.
    mm.load(path, ({0: 3}, {1: 4}), 'Oblivion.esm')
    want = (master.derive_formid(*MOVT_KEY) & 0x00FFFFFF) | (4 << 24)
    assert mm.derived_map()[derive_payload(*MOVT_KEY)] == want


@pytest.mark.parametrize('folder,inherited,expect_shared', [
    ('rat', True, True),       # master's folder, untouched by us
    ('rat', False, False),     # we converted this folder ourselves
])
def test_share_folder_fid_respects_our_own_conversions(tmp_path, folder,
                                                       inherited,
                                                       expect_shared):
    """A folder THIS plugin converted is authoritative for its own records.

    Its speeds, ragdoll bones and behavior path may differ from the master's,
    so the master's record would describe the wrong animal.
    """
    from tes5_import import creature_races

    _, path = _master_with_manifest(tmp_path)
    dep, _ = _dependent(path)
    saved = set(creature_races._INHERITED_FOLDERS)
    try:
        creature_races._INHERITED_FOLDERS.clear()
        if inherited:
            creature_races._INHERITED_FOLDERS.add(folder)
        _fid, from_master = creature_races.share_folder_fid(
            dep, 'MOVT', ('rat', 'TES4ratDefault'), folder)
        assert from_master is expect_shared
    finally:
        creature_races._INHERITED_FOLDERS.clear()
        creature_races._INHERITED_FOLDERS.update(saved)
