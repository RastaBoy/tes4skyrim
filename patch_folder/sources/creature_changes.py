"""Oblivion / Elsweyr creature -> vanilla Skyrim creature. PROPOSAL DATA ONLY.

*** NOTHING READS THIS MODULE YET. It is a table to argue with, not code. ***

Why it exists: the converted Oblivion creatures animate badly (generated behavior
graphs from TES4 .kf clips), and horses in particular converted into ordinary
walking actors with no mount behavior at all. This file is the shopping list for
replacing those shells with vanilla Skyrim ones -- race + skin + (for mounts) the
actor plumbing -- while KEEPING the Oblivion record's own stats, level, factions,
inventory, packages, scripts and dialogue.

The pipeline's own default stays `tes5_import/creature_races.py` (generate a race
per Oblivion creature). A separate, older reference table for the same idea lives
in `tes5_import/vanilla_creature_swap.py` + `docs/creature_race_equivalence.md`;
that one covers Oblivion/Nehrim/Morroblivion and assumes Beyond Skyrim is
installed. THIS file is scoped to the two plugins actually being patched here
(Oblivion.esm, ElsweyrAnequina.esp) and to the plugins actually installed on this
machine, and it adds the mount/horse layer that one has no data for.

--------------------------------------------------------------------------
WHAT WAS MEASURED (2026-08-27) -- every number below was computed, not recalled
--------------------------------------------------------------------------
* Oblivion.esm ships 914 CREA records in 43 mesh folders; grouped by
  (folder, body-part set) that is 49 distinct creatures.
* ElsweyrAnequina.esp ships 255 CREA records in 25 mesh folders; 39 groups.
* Skyrim.esm has 99 RACE records, 67 of them non-NPC; 124 usable creature races
  once Dawnguard, Dragonborn and Saints & Seducers are counted.
* Installed on this machine: Skyrim.esm, Dawnguard.esm, Dragonborn.esm,
  HearthFires.esm, ccbgssse025-advdsgs.esm (Saints & Seducers).
  NOT installed: Beyond Skyrim (BSAssets/BSHeartland), CC Goblins, CC Zombies,
  CC Bone Wolf, CC The Cause. Every row below sticks to what IS installed --
  which is why goblin/scamp/ogre/minotaur/imp have no exact match here even
  though docs/creature_race_equivalence.md lists Beyond Skyrim ones.

--------------------------------------------------------------------------
THE HORSE PROBLEM -- what was found
--------------------------------------------------------------------------
1. TES4 has an AUTHORED mount flag: CREA `DATA.Type == 4` ("Horse").
   Oblivion.esm sets it on 51 records; ElsweyrAnequina.esp on 26 (horses,
   zebras, elephants, camels and one running bird). `grep -rn "DATA.Type"
   tes5_import/*.py` finds NO reader for it -- the importer discards the flag
   entirely, so every mount converts to a plain walking actor. That is the
   "horses behave like NPCs" symptom.
2. RACE Mount Data is NOT the switch. All 99 Skyrim.esm races -- dog, cow,
   sabre cat, wolf included -- carry byte-identical mount offsets
   (mount -63.479/0/0, dismount -50/0/65, camera 0/-300/0), and our generated
   races already copy them from the DogRace template in creature_races.py.
   So emitting mount data on a generated race would change nothing.
3. What a vanilla horse actor actually carries (verified on WhiterunPlayerHorse
   00109E3D, EncHorseSaddledBrown 00023AB2, HorseForCarriageNew 00072A08):
       RNAM = HorseRace 000131FD          (or CartHorseRace 000DE505)
       WNAM = the coat skin ARMO          (see HORSE_COATS)
       ATKR = 000131FD                    (attack race = HorseRace)
       KWDA = ActorTypeHorse 00026110     (on the NPC_, NOT on the race)
       VTCK = CrHorseVoice 0001F232
       CNAM = EncClassHorse 0010F71E
       DOFT = HorseSaddleOutfit 00060798  (saddled) / absent (wild)
              HorseHarnessOutfit01 000C236E for cart horses
       ACBS.Flags = 0x00040018
   The mount ANIMATION comes with the vanilla skeleton + horsebehavior.hkx pair
   that HorseRace points at -- which is the whole argument for swapping the race
   instead of trying to teach the converted horse to be ridden
   (docs/horse_rideability_plan.md estimates that as a new behavior graph pair
   plus rider-side animations we have no TES4 source for).

--------------------------------------------------------------------------
DECISIONS TAKEN 2026-08-27 (rows carrying "DECIDED" are settled, not proposals)
--------------------------------------------------------------------------
* Alfiq -- REMOVED entirely, not substituted. 27 base records, 30 placed refs,
  41 leveled-list entries. Verified nothing in dialogue, quests or packages
  references them; one summon script does (ALFIQ_SUMMON_EXCEPTION).
* Fish (25 Elsweyr records) -- left converted. One fish rig for a whole
  aquarium is worse than the Oblivion meshes.
* Elephants (16 records) -- left converted, mounts and wild together.
* Camels (3) -- become horses in a random coat, keyed on the source FormID.
* Slarjei (3) -- become dogs.
* Goblins (95) and grummites (113) -- rieklings.
* Xivilai (10) -- left converted; the only candidate needs FaceGen head data.

Adding another creature mod later: put its races in SKYRIM_CREATURES (get the
ids + skins with `python tools/creature/creature_race_resolve.py --plugin <x>
--skins`), then point the relevant group rows at them. Check nothing was missed
with `python tools/creature/creature_patch_census.py -f <plugin>`.

--------------------------------------------------------------------------
HOW TO READ A SWAP ROW
--------------------------------------------------------------------------
tier:
    'exact'   same creature in both games; a player would not notice.
    'near'    same archetype, visibly different species. Opt-in.
    'none'    keep the converted creature -- either nothing installed comes
              close, or it was deliberately left alone.
    'remove'  delete the creature instead of substituting it. See REMOVALS for
              what a removal actually has to touch.
A swap MUST replace race AND skin together. A vanilla race points its ANAM/NAM3
at a vanilla skeleton and behavior project; leaving the actor on its Oblivion
body mesh gives it bone names that skeleton does not have, and it T-poses.
"""


class SkyrimCreature:
    """One vanilla creature race that can serve as a stand-in.

    Beyond the race and its skin, this carries the AI SHELL the vanilla actors
    of that race use -- voice, combat style, class, default package list and
    default outfit -- each taken by majority vote over every vanilla NPC_ that
    points at the race, with the vote recorded in `votes` so the evidence is
    visible.

    Why the shell and not just the race: the converter gives essentially every
    converted creature `csWolf` (measured 2026-08-27: 646 of 914 in Oblivion.esm
    and 245 of 255 in ElsweyrAnequina.esp; the rest get `DefaultCombatstyle`).
    A wolf combat style is correct for a wolf and wrong for everything else, and
    on a swapped actor it is the difference between a creature that hunts and
    one that stands still -- which is exactly what the first in-game test
    showed: wolves behaved, spiders did not.

    0 means no vanilla actor of this race sets that field, and the swap should
    then leave the converted value alone.

    `donor` is the most TYPICAL vanilla actor of the race -- the one agreeing
    with the majority vote on the most fields. Clone mode copies that record
    wholesale, which is the only way to reach "behaves exactly like the vanilla
    creature": the shell fields alone still left our spiders with one Oblivion
    faction where a vanilla frostbite spider has three, and a creature in no
    hostile faction has nobody to attack.
    """

    __slots__ = ('formid', 'plugin', 'family', 'name', 'skin', 'skin_edid',
                 'voice', 'voice_plugin', 'combat_style', 'npc_class',
                 'package_list', 'outfit', 'votes', 'donor', 'donor_edid')

    def __init__(self, formid, plugin, family, name, skin, skin_edid='',
                 voice=0, voice_plugin='', combat_style=0, npc_class=0,
                 package_list=0, outfit=0, votes='', donor=0, donor_edid=''):
        self.formid = formid          # id as it appears in that plugin
        self.plugin = plugin          # master that must be declared
        self.family = family          # animal / undead / daedra / mount / ...
        self.name = name              # human-readable
        self.skin = skin              # WNAM ARMO -- swap this WITH the race
        self.skin_edid = skin_edid
        self.voice = voice            # VTCK
        self.voice_plugin = voice_plugin or plugin
        self.combat_style = combat_style   # ZNAM
        self.npc_class = npc_class         # CNAM
        self.package_list = package_list   # DPLT
        self.outfit = outfit               # DOFT -- a creature's own kit
        self.votes = votes            # "field:winner/total" per field
        self.donor = donor            # the vanilla NPC_ to clone wholesale
        self.donor_edid = donor_edid

    def __repr__(self):
        return '<%s 0x%08X %s>' % (self.name, self.formid, self.plugin)


class Tes4Group:
    """One distinct TES4 creature: how many records, and what they are called."""

    __slots__ = ('count', 'mounts', 'types', 'sample')

    def __init__(self, count, mounts, types, sample):
        self.count = count            # CREA records in this group
        self.mounts = mounts          # of those, how many have DATA.Type == 4
        self.types = types            # TES4 DATA.Type histogram
        self.sample = sample          # most common FULL names

    def __repr__(self):
        return '<Tes4Group %d recs %s>' % (self.count, self.sample[:2])


class Swap:
    """Proposed replacement for one TES4 group."""

    __slots__ = ('target', 'tier', 'note', 'alt')

    def __init__(self, target, tier, note='', alt=()):
        self.target = target          # SKYRIM_CREATURES key, or None
        self.tier = tier              # exact | near | none | remove
        self.note = note
        self.alt = tuple(alt)         # other defensible targets

    def __repr__(self):
        return '<Swap %s %s>' % (self.target, self.tier)


EXACT, NEAR, NONE, REMOVE = 'exact', 'near', 'none', 'remove'

# Source plugins these tables reference, and whether they are installed here.
SOURCE_PLUGINS = {
    'Skyrim.esm':               True,
    'Dawnguard.esm':            True,    # DLC1
    'Dragonborn.esm':           True,    # DLC2
    'ccbgssse025-advdsgs.esm':  True,    # CC Saints & Seducers (SI creatures!)
    # --- not installed; rows that would need these are deliberately absent ---
    'BSAssets.esm':             False,   # Beyond Skyrim: goblin/scamp/ogre/imp
    'BSHeartland.esm':          False,   # BS Cyrodiil: minotaur/daedroth/lion
    'ccbgssse040-advobgobs.esl': False,  # CC Goblins
    'ccbgssse003-zombies.esl':  False,   # CC Plague of the Dead
    'ccbgssse067-daedinv.esm':  False,   # CC The Cause
}


# --------------------------------------------------------------------------
# 1. Every Skyrim creature race available on this machine.
#    Generated from the real plugins -- FormIDs and skins are read, not typed.
#    `formid` is the id as written in its own plugin; for the DLC/CC ones the
#    high byte is the runtime load-order index and must be re-mapped.
# --------------------------------------------------------------------------

SKYRIM_CREATURES = {
    # ---- animal ----
    'DLC1DeerGlowRace': SkyrimCreature(
        0x0200D0B2, 'Dawnguard.esm', 'animal',
        'Glowing Deer (Soul Cairn)',
        0x02002C04, 'DLC1SkinDeerGlow', 0x00041FBA, 'Skyrim.esm',
        0x00093A60, 0x0001CE1D, 0x0010D483, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x02002C02, 'DLC1EncDeerGlowing'),
    'DLC1HuskyArmoredCompanionRace': SkyrimCreature(
        0x02003D01, 'Dawnguard.esm', 'animal',
        'Husky (armored companion)',
        0x02018B31, 'SkinHuskyArmored', 0x02011687, 'Dawnguard.esm',
        0x00030004, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x0201AA74, 'DLC1HireableHunterDog1'),
    'DLC1HuskyArmoredRace': SkyrimCreature(
        0x02018B33, 'Dawnguard.esm', 'animal',
        'Husky (armored)',
        0x02018B31, 'SkinHuskyArmored', 0x02011687, 'Dawnguard.esm',
        0x00030004, 0x0001CE17, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x02018B30, 'DLC1EncHuskyArmored'),
    'DLC1HuskyBareCompanionRace': SkyrimCreature(
        0x020122B7, 'Dawnguard.esm', 'animal',
        'Husky (companion)',
        0x02018B37, 'SkinHuskyBare', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        '', 0x00000000, ''),
    'DLC1HuskyBareRace': SkyrimCreature(
        0x02018B36, 'Dawnguard.esm', 'animal',
        'Husky',
        0x02018B37, 'SkinHuskyBare', 0x02011687, 'Dawnguard.esm',
        0x00030004, 0x0001CE17, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x0200CEF3, 'DLC1RuunvaldHusky'),
    'DLC1SabreCatGlowRace': SkyrimCreature(
        0x0200D0B6, 'Dawnguard.esm', 'animal',
        'Glowing Sabre Cat (Soul Cairn)',
        0x02003C69, 'DLC1SkinSabrecat', 0x0001920C, 'Skyrim.esm',
        0x0001CDE6, 0x000131E6, 0x00095F47, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:4/4 package_list:3/4 skin_used:4/4', 0x02003C67, 'DLC1EncSabreCatVale'),
    'DLC2BoarRace': SkyrimCreature(
        0x02024038, 'Dragonborn.esm', 'animal',
        'Bristleback Boar',
        0x02024039, 'DLC2_SkinBoar', 0x02024C3E, 'Dragonborn.esm',
        0x00000000, 0x00106AED, 0x00021E81, 0x00000000,
        'voice:5/5 npc_class:3/5 package_list:3/5 skin_used:5/5', 0x0202403B, 'DLC2EncBoar01'),
    'DLC2MudcrabSolstheimRace': SkyrimCreature(
        0x0201B647, 'Dragonborn.esm', 'animal',
        'Mud Crab (Solstheim)',
        0x000BA546, 'SkinMudcrab', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        '', 0x00000000, ''),
    'BearBlackRace': SkyrimCreature(
        0x000131E8, 'Skyrim.esm', 'animal',
        'Black Bear',
        0x00000000, '', 0x0001F14E, 'Skyrim.esm',
        0x0008E665, 0x00106AED, 0x00095F47, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:2/3 skin_used:3/3 (none: inherit the race)', 0x00023A8A, 'EncBear'),
    'BearBrownRace': SkyrimCreature(
        0x000131E7, 'Skyrim.esm', 'animal',
        'Brown Bear',
        0x00000000, '', 0x0001F14E, 'Skyrim.esm',
        0x0008E665, 0x00106AED, 0x00095F47, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2 (none: inherit the race)', 0x00023A8B, 'EncBearCave'),
    'BearSnowRace': SkyrimCreature(
        0x000131E9, 'Skyrim.esm', 'animal',
        'Snow Bear',
        0x00000000, '', 0x0001F14E, 'Skyrim.esm',
        0x0008E665, 0x00106AED, 0x00095F47, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:2/3 package_list:3/3 skin_used:3/3 (none: inherit the race)', 0x00023A8C, 'EncBearSnow'),
    'C06WolfSpiritRace': SkyrimCreature(
        0x00106C10, 'Skyrim.esm', 'animal',
        'Wolf Spirit (quest)',
        0x000C02FB, 'SkinWolfBlack', 0x0001F6A7, 'Skyrim.esm',
        0x000E8C3D, 0x000131E6, 0x00095F47, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:4/4 package_list:4/4 skin_used:4/4', 0x00058303, 'EncC06WolfSpirit'),
    'DA03BarbasDogRace': SkyrimCreature(
        0x000CD657, 'Skyrim.esm', 'animal',
        'Barbas (unique dog)',
        0x0004B2C9, 'SkinDog', 0x0001F180, 'Skyrim.esm',
        0x00000000, 0x00013176, 0x00000000, 0x00000000,
        'voice:1/1 npc_class:1/1 skin_used:1/1', 0x0001BFC5, 'DA03Barbas'),
    'DeerRace': SkyrimCreature(
        0x000CF89B, 'Skyrim.esm', 'animal',
        'Deer / doe',
        0x00000000, '', 0x00041FBA, 'Skyrim.esm',
        0x00093A60, 0x0001CE1D, 0x00000000, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:3/4 skin_used:4/4 (none: inherit the race)', 0x000CF89D, 'EncDeer'),
    'DogCompanionRace': SkyrimCreature(
        0x000F1AC4, 'Skyrim.esm', 'animal',
        'Dog (companion)',
        0x0004B2C9, 'SkinDog', 0x0001F180, 'Skyrim.esm',
        0x00030004, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:2/3 skin_used:3/3', 0x0009A7AA, 'TrainedDog'),
    'DogRace': SkyrimCreature(
        0x000131EE, 'Skyrim.esm', 'animal',
        'Dog',
        0x0004B2C9, 'SkinDog', 0x0001F180, 'Skyrim.esm',
        0x00030004, 0x0001CE17, 0x00000000, 0x00000000,
        'voice:8/8 combat_style:6/8 npc_class:8/8 skin_used:8/8', 0x00054AE3, 'EncBanditDog'),
    'ElkRace': SkyrimCreature(
        0x000131ED, 'Skyrim.esm', 'animal',
        'Elk (antlered male deer)',
        0x00000000, '', 0x00041FBA, 'Skyrim.esm',
        0x00093A60, 0x0001CE1D, 0x0010D483, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:3/3 (none: inherit the race)', 0x00023A91, 'EncElk'),
    'HorkerRace': SkyrimCreature(
        0x000131FC, 'Skyrim.esm', 'animal',
        'Horker',
        0x00000000, '', 0x0001F22D, 'Skyrim.esm',
        0x000CDE5E, 0x000EDD36, 0x00000000, 0x00000000,
        'voice:3/3 combat_style:2/3 npc_class:2/3 skin_used:3/3 (none: inherit the race)', 0x000EF607, 'POIHorkerEnchanted'),
    'MG07DogRace': SkyrimCreature(
        0x000F905F, 'Skyrim.esm', 'animal',
        'Dog (quest)',
        0x000F9062, 'SkinDogMG07', 0x0001F6A7, 'Skyrim.esm',
        0x00030004, 0x0001CE17, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x000F9060, 'MG07Dog'),
    'MammothRace': SkyrimCreature(
        0x000131FF, 'Skyrim.esm', 'animal',
        'Mammoth',
        0x00059253, 'SkinMammothWild', 0x0001F287, 'Skyrim.esm',
        0x0008F6C3, 0x000F2594, 0x000EB249, 0x00000000,
        'voice:7/7 combat_style:6/7 npc_class:5/7 package_list:5/7', 0x000DD641, 'EncMammothTamed'),
    'MudcrabRace': SkyrimCreature(
        0x000BA545, 'Skyrim.esm', 'animal',
        'Mud Crab',
        0x000BA546, 'SkinMudcrab', 0x0003E8A6, 'Skyrim.esm',
        0x000BB4AF, 0x000BB4B0, 0x00021E81, 0x00000000,
        'voice:5/5 combat_style:5/5 npc_class:5/5 package_list:5/5', 0x000E4010, 'EncMudcrabMedium'),
    'SabreCatRace': SkyrimCreature(
        0x00013200, 'Skyrim.esm', 'animal',
        'Sabre Cat',
        0x00000000, '', 0x0001920C, 'Skyrim.esm',
        0x0001CDE6, 0x000131E6, 0x00000000, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:4/4 skin_used:4/4 (none: inherit the race)', 0x00023AB5, 'EncSabreCat'),
    'SabreCatSnowyRace': SkyrimCreature(
        0x00013202, 'Skyrim.esm', 'animal',
        'Snowy Sabre Cat',
        0x0009DA65, 'SkinSabrecatSnowy', 0x0001920C, 'Skyrim.esm',
        0x0001CDE6, 0x000131E6, 0x00095F47, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:3/3', 0x00023AB6, 'EncSabreCatSnow'),
    'SkeeverRace': SkyrimCreature(
        0x00013201, 'Skyrim.esm', 'animal',
        'Skeever',
        0x00000000, '', 0x00019FE5, 'Skyrim.esm',
        0x0003CEDF, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:8/8 combat_style:8/8 npc_class:8/8 package_list:7/8 skin_used:8/8 (none: inherit the race)', 0x00023AB7, 'EncSkeever'),
    'SkeeverWhiteRace': SkyrimCreature(
        0x000C3EDF, 'Skyrim.esm', 'animal',
        'White Skeever',
        0x00000000, '', 0x00019FE5, 'Skyrim.esm',
        0x0003CEDF, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1 (none: inherit the race)', 0x000490F2, 'dunHonningbrewMeaderyencSkeever'),
    'SlaughterfishRace': SkyrimCreature(
        0x00013203, 'Skyrim.esm', 'animal',
        'Slaughterfish',
        0x00000000, '', 0x00041FBB, 'Skyrim.esm',
        0x00041445, 0x000131E6, 0x00000000, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 skin_used:1/1 (none: inherit the race)', 0x00023AB8, 'EncSlaughterfish'),
    'WhiteStagRace': SkyrimCreature(
        0x00104F45, 'Skyrim.esm', 'animal',
        'White Stag',
        0x00000000, '', 0x00041FBA, 'Skyrim.esm',
        0x00093A60, 0x0001CE17, 0x00000000, 0x00000000,
        'voice:2/3 combat_style:2/3 npc_class:3/3 skin_used:3/3 (none: inherit the race)', 0x00090CE2, 'DA05QuestingBeast'),
    'WolfRace': SkyrimCreature(
        0x0001320A, 'Skyrim.esm', 'animal',
        'Wolf',
        0x0004E886, 'SkinWolf', 0x0001F6A7, 'Skyrim.esm',
        0x00000000, 0x000131E6, 0x00095F47, 0x00000000,
        'voice:21/23 npc_class:20/23 package_list:17/23', 0x00023ABE, 'EncWolf'),

    # ---- beast ----
    'DLC1VampireBeastRace': SkyrimCreature(
        0x0200283A, 'Dawnguard.esm', 'beast',
        'Vampire Lord',
        0x00000000, '', 0x02007D86, 'Dawnguard.esm',
        0x0201A345, 0x0002E00F, 0x00000000, 0x02011A89,
        'voice:4/4 combat_style:3/4 npc_class:3/4 outfit:3/4 skin_used:4/4 (none: inherit the race)', 0x0200EC1C, 'DLC1HarkonCombatMelee'),
    'DLC2WerebearBeastRace': SkyrimCreature(
        0x0201E17B, 'Dragonborn.esm', 'beast',
        'Werebear',
        0x00000000, '', 0x0001F2E6, 'Skyrim.esm',
        0x000A199D, 0x000A1993, 0x00021E81, 0x000A1986,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 outfit:2/2 skin_used:2/2 (none: inherit the race)', 0x020322B1, 'DLC2EncWerebear'),
    'WerewolfBeastRace': SkyrimCreature(
        0x000CDD84, 'Skyrim.esm', 'beast',
        'Werewolf',
        0x00000000, '', 0x0001F2E6, 'Skyrim.esm',
        0x000A199D, 0x00000000, 0x00021E81, 0x00000000,
        'voice:15/16 combat_style:15/16 package_list:14/16 skin_used:16/16 (none: inherit the race)', 0x00023ABC, 'EncWerewolf01'),

    # ---- construct ----
    'DLC1GargoyleRace': SkyrimCreature(
        0x0200A2C6, 'Dawnguard.esm', 'construct',
        'Gargoyle',
        0x0200A2C8, 'DLC1SkinGargoyle', 0x0200F8AE, 'Dawnguard.esm',
        0x020166D5, 0x0200D6F6, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x0200A2CC, 'DLC1EncGargoyle'),
    'DLC1GargoyleVariantBossRace': SkyrimCreature(
        0x02010D00, 'Dawnguard.esm', 'construct',
        'Gargoyle Brute',
        0x02010CFD, 'DLC1SkinGargoyleVariantBoss', 0x0200F8AE, 'Dawnguard.esm',
        0x00000000, 0x0200D6F6, 0x00021E81, 0x00000000,
        'voice:2/2 npc_class:2/2 package_list:2/2', 0x02014487, 'DLC1EncGargoyleSentinel'),
    'DLC1GargoyleVariantGreenRace': SkyrimCreature(
        0x02019D86, 'Dawnguard.esm', 'construct',
        'Gargoyle (green)',
        0x02019D85, 'DLC1SkinGargoyleVariantGreen', 0x0200F8AE, 'Dawnguard.esm',
        0x020166D5, 0x0200D6F6, 0x00021E81, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:4/4 package_list:4/4 skin_used:4/4', 0x0200F4D6, 'DLC1EncGargoyleSummonAmulet'),
    'DLC1LD_ForgemasterRace': SkyrimCreature(
        0x02015C34, 'Dawnguard.esm', 'construct',
        'Forgemaster',
        0x00000000, '', 0x0001F1CF, 'Skyrim.esm',
        0x0009035B, 0x00090356, 0x00021E81, 0x000F906E,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 outfit:3/3 skin_used:2/3 (none: inherit the race)', 0x02015C47, 'DLC1LD_Forgemaster02'),
    'dlc2AshGuardianRace': SkyrimCreature(
        0x02027BFC, 'Dragonborn.esm', 'construct',
        'Ash Guardian',
        0x02027118, 'DLC2SkinAshGuardian', 0x0001F1D5, 'Skyrim.esm',
        0x00070FF9, 0x0203CF6A, 0x00021E81, 0x00000000,
        'voice:5/5 combat_style:4/5 npc_class:3/5 package_list:5/5 skin_used:5/5', 0x020177B6, 'DLC2SummonAshGuardian'),

    # ---- creature ----
    'DLC1SoulCairnSoulWispRace': SkyrimCreature(
        0x02002AE0, 'Dawnguard.esm', 'creature',
        'Wispmother (Soul Cairn)',
        0x02002AE7, 'DLC1SkinSoulCairnSoulWisp', 0x00000000, '',
        0x00086F48, 0x000131E6, 0x00000000, 0x00000000,
        'combat_style:2/2 npc_class:2/2 skin_used:2/2', 0x0200EBB1, 'DLC1SoulCairnWispWALL'),
    'SprigganEarthMotherRace': SkyrimCreature(
        0x02013B77, 'Dawnguard.esm', 'creature',
        'Spriggan Earth Mother',
        0x02013B79, 'SkinSprigganEarthMother', 0x0001F288, 'Skyrim.esm',
        0x000A041D, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x02013B74, 'DLC1EncSprigganEarthMother'),
    'DLC2NetchCalfRace': SkyrimCreature(
        0x02028580, 'Dragonborn.esm', 'creature',
        'Netch Calf',
        0x02028581, 'DLC2NetchCalfSkin', 0x02024C31, 'Dragonborn.esm',
        0x02034C03, 0x000F2594, 0x000EB249, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x0202857F, 'DLC2EncNetchCalf'),
    'DLC2NetchRace': SkyrimCreature(
        0x0201FEB8, 'Dragonborn.esm', 'creature',
        'Bull Netch',
        0x0201FEBB, 'DLC2NetchSkin', 0x02024C31, 'Dragonborn.esm',
        0x02034C03, 0x000F2594, 0x000EB249, 0x00000000,
        'voice:3/3 combat_style:2/3 npc_class:3/3 package_list:3/3 skin_used:3/3', 0x0201B649, 'DLC2EncNetchBetty'),
    'DLC2SprigganBurntRace': SkyrimCreature(
        0x0201B644, 'Dragonborn.esm', 'creature',
        'Burnt Spriggan',
        0x02027E16, 'DLC2SkinSprigganBurnt', 0x0001F288, 'Skyrim.esm',
        0x0202A6D4, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:3/3', 0x0201B63F, 'DLC2EncSprigganBurnt'),
    'DLC2dunKarstaagIceWraithRace': SkyrimCreature(
        0x02029EE7, 'Dragonborn.esm', 'creature',
        'Ice Wraith (Karstaag)',
        0x000538F8, 'SkinIceWraith', 0x0001F236, 'Skyrim.esm',
        0x00058B48, 0x00073F1F, 0x00000000, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 skin_used:2/2', 0x02034B5A, 'DLC2dunKarstaagIceWraithSummoned'),
    'IceWraithRace': SkyrimCreature(
        0x000131FE, 'Skyrim.esm', 'creature',
        'Ice Wraith',
        0x000538F8, 'SkinIceWraith', 0x0001F236, 'Skyrim.esm',
        0x00058B48, 0x00073F1F, 0x00021E81, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:3/3', 0x00023AB3, 'EncIceWraith'),
    'MagicAnomalyRace': SkyrimCreature(
        0x000B6F95, 'Skyrim.esm', 'creature',
        'Magic Anomaly',
        0x000B6FA0, 'SkinMagicAnomaly', 0x0001F236, 'Skyrim.esm',
        0x00058B48, 0x00073F1F, 0x00021E81, 0x0005E99D,
        'voice:3/3 combat_style:2/3 npc_class:3/3 package_list:2/3 outfit:3/3 skin_used:3/3', 0x000B6F94, 'EncMagicAnomaly'),
    'SprigganMatronRace': SkyrimCreature(
        0x000F3903, 'Skyrim.esm', 'creature',
        'Spriggan Matron',
        0x000F3904, 'SkinSprigganMatron', 0x0001F288, 'Skyrim.esm',
        0x000A041D, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x000F3905, 'EncSprigganMatron'),
    'SprigganRace': SkyrimCreature(
        0x00013204, 'Skyrim.esm', 'creature',
        'Spriggan',
        0x00092E29, 'SkinSpriggan', 0x0001F288, 'Skyrim.esm',
        0x000A041D, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:4/4 combat_style:3/4 npc_class:4/4 package_list:3/4 skin_used:4/4', 0x00023AB9, 'EncSpriggan'),
    'SprigganSwarmRace': SkyrimCreature(
        0x0009AA44, 'Skyrim.esm', 'creature',
        'Spriggan Swarm',
        0x00086F42, 'SkinWitchlight', 0x00000000, '',
        0x00057BE8, 0x000131E6, 0x00000000, 0x00000000,
        'combat_style:1/1 npc_class:1/1 skin_used:1/1', 0x0009AA3B, 'EncSprigganSwarm'),
    'SwarmRace': SkyrimCreature(
        0x0009AA3C, 'Skyrim.esm', 'creature',
        'Insect Swarm',
        0x00086F42, 'SkinWitchlight', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        '', 0x00000000, ''),
    'WispRace': SkyrimCreature(
        0x00013208, 'Skyrim.esm', 'creature',
        'Wispmother',
        0x00042528, 'SkinWisp', 0x0001F4A3, 'Skyrim.esm',
        0x00059660, 0x0006766D, 0x00000000, 0x00000000,
        'voice:2/3 combat_style:2/3 npc_class:2/3 skin_used:2/3', 0x00023ABD, 'EncWispMother'),
    'WispShadeRace': SkyrimCreature(
        0x000F1182, 'Skyrim.esm', 'creature',
        'Wisp Shade',
        0x00042528, 'SkinWisp', 0x0001F4A3, 'Skyrim.esm',
        0x00059660, 0x0006766D, 0x00000000, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 skin_used:1/1', 0x000F1181, 'encWispShade'),
    'WitchlightRace': SkyrimCreature(
        0x00013209, 'Skyrim.esm', 'creature',
        'Witchlight (floating wisp light)',
        0x00086F42, 'SkinWitchlight', 0x00000000, '',
        0x00086F48, 0x000131E6, 0x00000000, 0x00000000,
        'combat_style:1/1 npc_class:1/1 skin_used:1/1', 0x0002C3C7, 'EncWisp'),
    'ccBGSSSE025_CorruptedSprigganRaceDementia': SkyrimCreature(
        0x051B691F, 'ccbgssse025-advdsgs.esm', 'creature',
        'Corrupted Spriggan (Dementia)',
        0x05000B4A, 'ccBGSSSE025_SkinCorruptedSprigganDementia', 0x0001F288, 'Skyrim.esm',
        0x000A041D, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x05000CDB, 'ccBGSSSE025_EncCorruptedSprigganDementia'),
    'ccBGSSSE025_CorruptedSprigganRaceMania': SkyrimCreature(
        0x051B6918, 'ccbgssse025-advdsgs.esm', 'creature',
        'Corrupted Spriggan (Mania)',
        0x05000B49, 'ccBGSSSE025_SkinCorruptedSprigganMania', 0x0001F288, 'Skyrim.esm',
        0x000A041D, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x05000B77, 'ccBGSSSE025_EncCorruptedSprigganMania'),

    # ---- critter ----
    'ChickenRace': SkyrimCreature(
        0x000A919D, 'Skyrim.esm', 'critter',
        'Chicken',
        0x000A919C, 'SkinChicken', 0x0010AA5F, 'Skyrim.esm',
        0x000A919F, 0x0001CE1D, 0x0010D483, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:3/3', 0x000A91A0, 'EncChicken'),
    'FoxRace': SkyrimCreature(
        0x00109C7C, 'Skyrim.esm', 'critter',
        'Fox',
        0x00000000, '', 0x00000000, '',
        0x00000000, 0x00017008, 0x00000000, 0x00000000,
        'npc_class:599/617 skin_used:613/617 (none: inherit the race)', 0x00015BE5, 'LvlBanditMeleeTank'),
    'HareRace': SkyrimCreature(
        0x0006DC99, 'Skyrim.esm', 'critter',
        'Hare',
        0x0006DC9B, 'SkinHare', 0x000D78AD, 'Skyrim.esm',
        0x0006E27B, 0x0001CE1D, 0x0010D483, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:3/3', 0x0006DC9D, 'EncHare'),

    # ---- daedra ----
    'DLC2DremoraRace': SkyrimCreature(
        0x02035538, 'Dragonborn.esm', 'daedra',
        'Dremora (Apocrypha)',
        0x00000000, '', 0x00000000, '',
        0x0003BE1C, 0x0001E7D0, 0x00021E81, 0x00000000,
        'combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2 (none: inherit the race)', 0x0201FF20, 'DLC2DremoraButler'),
    'DLC2LurkerRace': SkyrimCreature(
        0x02014495, 'Dragonborn.esm', 'daedra',
        'Lurker',
        0x02014497, 'DLC2SkinBenthicLurker', 0x02020767, 'Dragonborn.esm',
        0x0201E113, 0x0203183A, 0x00021E81, 0x00000000,
        'voice:6/6 combat_style:5/6 npc_class:4/6 package_list:5/6 skin_used:5/6', 0x0201B640, 'DLC2EncLurker01'),
    'DLC2SeekerRace': SkyrimCreature(
        0x0201DCB9, 'Dragonborn.esm', 'daedra',
        'Seeker',
        0x0201DCB7, 'SkinHMDaedra', 0x0203D47E, 'Dragonborn.esm',
        0x0203C6A5, 0x0203C6A3, 0x00021E81, 0x00000000,
        'voice:13/13 combat_style:13/13 npc_class:13/13 package_list:13/13 skin_used:13/13', 0x0201DCBA, 'DLC2EncSeeker02'),
    'AtronachFlameRace': SkyrimCreature(
        0x000131F5, 'Skyrim.esm', 'daedra',
        'Flame Atronach',
        0x00000000, '', 0x0001F1D3, 'Skyrim.esm',
        0x00070FF9, 0x00000000, 0x00000000, 0x00000000,
        'voice:11/11 combat_style:11/11 skin_used:11/11 (none: inherit the race)', 0x00023AA6, 'EncAtronachFlame'),
    'AtronachFrostRace': SkyrimCreature(
        0x000131F6, 'Skyrim.esm', 'daedra',
        'Frost Atronach',
        0x0005B2E7, 'SkinAtronachFrost', 0x0001F1D4, 'Skyrim.esm',
        0x00059660, 0x000AD236, 0x00021E81, 0x00000000,
        'voice:10/10 combat_style:10/10 npc_class:6/10 package_list:10/10 skin_used:10/10', 0x00023AA7, 'EncAtronachFrost'),
    'AtronachStormRace': SkyrimCreature(
        0x000131F7, 'Skyrim.esm', 'daedra',
        'Storm Atronach',
        0x0006881E, 'SkinAtronachStorm', 0x0001F1D5, 'Skyrim.esm',
        0x00075D28, 0x000AD237, 0x00021E81, 0x0010C1E0,
        'voice:9/9 combat_style:9/9 npc_class:6/9 package_list:9/9 outfit:9/9 skin_used:9/9', 0x00023AA8, 'EncAtronachStorm'),
    'DremoraRace': SkyrimCreature(
        0x000131F0, 'Skyrim.esm', 'daedra',
        'Dremora',
        0x00000000, '', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        'skin_used:25/25 (none: inherit the race)', 0x00016EF0, 'EncDremoraMelee02'),
    'ccBGSSSE025_DarkSeducerRace': SkyrimCreature(
        0x05000817, 'ccbgssse025-advdsgs.esm', 'daedra',
        'Dark Seducer (Mazken)',
        0x00000000, '', 0x00013AF1, 'Skyrim.esm',
        0x00000000, 0x00000000, 0x00021E81, 0x00000000,
        'voice:8/8 package_list:8/8 skin_used:8/8 (none: inherit the race)', 0x05000A07, 'ccBGSSSE025_EncDarkSeducerWarrior'),
    'ccBGSSSE025_GoldenSaintRace': SkyrimCreature(
        0x05000816, 'ccbgssse025-advdsgs.esm', 'daedra',
        'Golden Saint (Aureal)',
        0x00000000, '', 0x00013AF1, 'Skyrim.esm',
        0x00000000, 0x00000000, 0x00021E81, 0x05000A03,
        'voice:11/11 package_list:11/11 outfit:7/11 skin_used:11/11 (none: inherit the race)', 0x05000880, 'ccBGSSSE025_EncGoldenSaintArcher'),

    # ---- dragon ----
    'DLC1UndeadDragonRace': SkyrimCreature(
        0x020117DE, 'Dawnguard.esm', 'dragon',
        'Durnehviir (undead dragon)',
        0x02011A6E, 'SkinDragonUndead', 0x0002992B, 'Skyrim.esm',
        0x0200BFEC, 0x00000000, 0x0009C21B, 0x02011A73,
        'voice:2/2 combat_style:2/2 package_list:2/2 outfit:2/2 skin_used:2/2', 0x0200C71A, 'DLC1DurnehviirSummon'),
    'DLC2DragonBlackRace': SkyrimCreature(
        0x0202C88C, 'Dragonborn.esm', 'dragon',
        'Black Dragon',
        0x0202C88E, 'skinDLC2DragonBlack', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        '', 0x00000000, ''),
    'dlc2SpectralDragonRace': SkyrimCreature(
        0x0201F98F, 'Dragonborn.esm', 'dragon',
        'Spectral Dragon',
        0x0201F992, 'dlc2SpectralDragonSkin', 0x0001F236, 'Skyrim.esm',
        0x0201F996, 0x00073F1F, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x0201F990, 'dlc2FireWyrmCreated'),
    'AlduinRace': SkyrimCreature(
        0x000E7713, 'Skyrim.esm', 'dragon',
        'Alduin',
        0x000B1959, 'skinDragonAlduin', 0x0006F44F, 'Skyrim.esm',
        0x00000000, 0x0002F201, 0x0009C21B, 0x000B195A,
        'voice:6/6 npc_class:6/6 package_list:6/6 outfit:6/6 skin_used:6/6', 0x0004377F, 'MQ206AncientAlduin'),
    'DragonRace': SkyrimCreature(
        0x00012E82, 'Skyrim.esm', 'dragon',
        'Dragon',
        0x00000000, '', 0x0002992B, 'Skyrim.esm',
        0x00048C83, 0x0002F201, 0x0009C21B, 0x00000000,
        'voice:39/42 combat_style:38/42 npc_class:38/42 package_list:33/42 skin_used:41/42 (none: inherit the race)', 0x0008BC7E, 'EncDragonTundra'),
    'UndeadDragonRace': SkyrimCreature(
        0x001052A3, 'Skyrim.esm', 'dragon',
        'Undead Dragon',
        0x0003F815, 'SkinDragonUnderskin', 0x0002992B, 'Skyrim.esm',
        0x00048C83, 0x0002F201, 0x0009C21B, 0x000253B0,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 outfit:1/1 skin_used:1/1', 0x0009192C, 'dunLabyrinthianUndeadDragon'),

    # ---- dwarven ----
    'DLC2DwarvenBallistaRace': SkyrimCreature(
        0x0202B014, 'Dragonborn.esm', 'dwarven',
        'Dwarven Ballista',
        0x0202B017, 'SkinDwarvenBallistaCenturion', 0x0001F1D0, 'Skyrim.esm',
        0x02033257, 0x00090358, 0x00021E81, 0x000F9071,
        'voice:4/4 combat_style:3/4 npc_class:4/4 package_list:4/4 outfit:4/4 skin_used:4/4', 0x02033250, 'DLC2EncDwarvenBallista01'),
    'DwarvenCenturionRace': SkyrimCreature(
        0x000131F1, 'Skyrim.esm', 'dwarven',
        'Dwarven Centurion',
        0x000800EA, 'SkinDwarvenSteamCenturion', 0x0001F1CF, 'Skyrim.esm',
        0x0009035B, 0x00090356, 0x00021E81, 0x000F906E,
        'voice:8/8 combat_style:8/8 npc_class:8/8 package_list:8/8 outfit:7/8 skin_used:7/8', 0x00023A96, 'EncDwarvenCenturion03'),
    'DwarvenSphereRace': SkyrimCreature(
        0x000131F2, 'Skyrim.esm', 'dwarven',
        'Dwarven Sphere',
        0x0007874B, 'SkinDwarvenSphereCenturion', 0x0001F1D0, 'Skyrim.esm',
        0x0007EA48, 0x00090358, 0x00021E81, 0x00000000,
        'voice:7/7 combat_style:7/7 npc_class:7/7 package_list:7/7 skin_used:7/7', 0x00023A97, 'EncDwarvenSphere02'),
    'DwarvenSpiderRace': SkyrimCreature(
        0x000131F3, 'Skyrim.esm', 'dwarven',
        'Dwarven Spider',
        0x00081C79, 'SkinDwarvenSpiderCenturion', 0x0001F1D1, 'Skyrim.esm',
        0x000872B0, 0x00090359, 0x00021E81, 0x000F9072,
        'voice:6/6 combat_style:6/6 npc_class:6/6 package_list:6/6 outfit:5/6 skin_used:5/6', 0x00023A98, 'EncDwarvenSpider02'),

    # ---- giant ----
    'DLC2GhostFrostGiantRace': SkyrimCreature(
        0x0201CAD8, 'Dragonborn.esm', 'giant',
        'Frost Giant (Karstaag, ghost)',
        0x0201CAD9, 'DLC2FrostGiantSkin', 0x02028241, 'Dragonborn.esm',
        0x02028248, 0x02028213, 0x00021E81, 0x00000000,
        'voice:2/3 combat_style:2/3 npc_class:2/3 package_list:3/3 skin_used:3/3', 0x02019665, 'DLC2dunKarstaag'),
    'C00GiantOutsideWhiterunRace': SkyrimCreature(
        0x000CAE13, 'Skyrim.esm', 'giant',
        'Giant (quest variant)',
        0x00048D94, 'SkinGiant02', 0x0001F225, 'Skyrim.esm',
        0x00028349, 0x0001CE17, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x000C97D1, 'C00GiantForWhiterunBattle'),
    'GiantRace': SkyrimCreature(
        0x000131F9, 'Skyrim.esm', 'giant',
        'Giant',
        0x00048D94, 'SkinGiant02', 0x0001F225, 'Skyrim.esm',
        0x00028349, 0x0001CE17, 0x00021E81, 0x00000000,
        'voice:8/9 combat_style:7/9 npc_class:8/9 package_list:7/9 skin_used:6/9', 0x00030438, 'EncGiant03'),

    # ---- humanoid ----
    'FalmerFrozenVampRace': SkyrimCreature(
        0x0201AACC, 'Dawnguard.esm', 'humanoid',
        'Frozen Falmer',
        0x02006DBC, 'DLC1SkinVampireFalmer', 0x0001F1D2, 'Skyrim.esm',
        0x00000000, 0x0001CE1E, 0x00021E81, 0x00000000,
        'voice:13/13 npc_class:11/13 package_list:12/13', 0x02015127, 'DLC1_BF_FrozenFalmerShaman01'),
    'DLC2MountedRieklingRace': SkyrimCreature(
        0x020179CF, 'Dragonborn.esm', 'humanoid',
        'Mounted Riekling',
        0x02038407, 'DLC2_SkinMountedRiekling_VariantB', 0x020208DC, 'Dragonborn.esm',
        0x0201D9C7, 0x0203BD08, 0x00021E81, 0x00000000,
        'voice:8/8 combat_style:8/8 npc_class:8/8 package_list:8/8 skin_used:5/8', 0x0203CFE7, 'DLC2EncMountedRiekling03A'),
    'DLC2RieklingRace': SkyrimCreature(
        0x02017F44, 'Dragonborn.esm', 'humanoid',
        'Riekling',
        0x020354E2, 'DLC2SkinRieklingChief', 0x020208DC, 'Dragonborn.esm',
        0x0201D9C7, 0x0203BD08, 0x00021E81, 0x00000000,
        'voice:20/20 combat_style:12/20 npc_class:19/20 package_list:19/20', 0x02017F47, 'DLC2EncRiekling01Melee'),
    'DLC2ThirskRieklingRace': SkyrimCreature(
        0x0201A50A, 'Dragonborn.esm', 'humanoid',
        'Riekling (Thirsk)',
        0x02017F46, 'DLC2SkinRiekling01', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        '', 0x00000000, ''),
    'FalmerRace': SkyrimCreature(
        0x000131F4, 'Skyrim.esm', 'humanoid',
        'Falmer',
        0x00016EE7, 'SkinFalmer', 0x0001F1D2, 'Skyrim.esm',
        0x00000000, 0x0001CE1E, 0x00021E81, 0x00000000,
        'voice:37/37 npc_class:32/37 package_list:37/37', 0x00023A99, 'EncFalmer01MeleeA'),
    'HagravenRace': SkyrimCreature(
        0x000131FB, 'Skyrim.esm', 'humanoid',
        'Hagraven',
        0x00097243, 'SkinHagraven', 0x0001F22C, 'Skyrim.esm',
        0x0002A54E, 0x000A93B3, 0x00021E81, 0x00000000,
        'voice:14/15 combat_style:13/15 npc_class:14/15 package_list:14/15 skin_used:13/15', 0x00023AB0, 'EncHagraven'),

    # ---- insect ----
    'DLC1ChaurusHunterRace': SkyrimCreature(
        0x020051FB, 'Dawnguard.esm', 'insect',
        'Chaurus Hunter (flying)',
        0x020051FE, 'SkinChaurusFlyer', 0x0001F152, 'Skyrim.esm',
        0x02005AA2, 0x02005206, 0x00021E81, 0x00000000,
        'voice:4/4 combat_style:3/4 npc_class:4/4 package_list:4/4 skin_used:3/4', 0x02005204, 'DLC1EncChaurusHunter'),
    'DLC1_BF_ChaurusRace': SkyrimCreature(
        0x02015136, 'Dawnguard.esm', 'insect',
        'Chaurus (Forgotten Vale)',
        0x02016125, 'DLC1SkinChaurusFrozen', 0x0001F152, 'Skyrim.esm',
        0x0005A832, 0x00044CCA, 0x00021E81, 0x00000000,
        'voice:6/6 combat_style:6/6 npc_class:6/6 package_list:6/6 skin_used:6/6', 0x02006D06, 'DLC1_BF_FrozenChaurus01'),
    'DLC2AshHopperRace': SkyrimCreature(
        0x0201B658, 'Dragonborn.esm', 'insect',
        'Ash Hopper (scrib)',
        0x00000000, '', 0x0201F17B, 'Dragonborn.esm',
        0x020202C8, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:3/4 package_list:4/4 skin_used:4/4 (none: inherit the race)', 0x0201B657, 'DLC2EncAshHopper'),
    'DLC2ExpSpiderBaseRace': SkyrimCreature(
        0x02014449, 'Dragonborn.esm', 'insect',
        'Albino Spider',
        0x02014457, 'DLC2ExpSpiderPoisonSkin', 0x0001F21D, 'Skyrim.esm',
        0x00000000, 0x00044CCB, 0x000EB249, 0x00053900,
        'voice:26/26 npc_class:26/26 package_list:26/26 outfit:26/26', 0x0202095E, 'DLC2ExpSpiderShockJumpingFriend'),
    'DLC2ExpSpiderPackmuleRace': SkyrimCreature(
        0x02027483, 'Dragonborn.esm', 'insect',
        'Albino Spider (packmule)',
        0x0201DFEB, 'DLC2ExpSpiderRareSkin', 0x0001F21D, 'Skyrim.esm',
        0x00041446, 0x00044CCB, 0x000EB249, 0x00053900,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 outfit:1/1 skin_used:1/1', 0x020274A0, 'DLC2ExpSpiderPackmuleFriendCUT'),
    'ChaurusRace': SkyrimCreature(
        0x000131EB, 'Skyrim.esm', 'insect',
        'Chaurus',
        0x00058E2A, 'SkinChaurus', 0x0001F152, 'Skyrim.esm',
        0x0005A832, 0x00044CCA, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x000A5600, 'EncChaurus'),
    'ChaurusReaperRace': SkyrimCreature(
        0x000A5601, 'Skyrim.esm', 'insect',
        'Chaurus Reaper',
        0x00058E2A, 'SkinChaurus', 0x0001F152, 'Skyrim.esm',
        0x0005A832, 0x00044CCA, 0x00021E81, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x00023A8F, 'EncChaurusReaper'),
    'FrostbiteSpiderRace': SkyrimCreature(
        0x000131F8, 'Skyrim.esm', 'insect',
        'Frostbite Spider',
        0x00000000, '', 0x0001F21D, 'Skyrim.esm',
        0x00041446, 0x00044CCB, 0x00021E81, 0x00053900,
        'voice:10/10 combat_style:10/10 npc_class:10/10 package_list:10/10 outfit:10/10 skin_used:9/10 (none: inherit the race)', 0x00023AAA, 'EncFrostbiteSpider'),
    'FrostbiteSpiderRaceGiant': SkyrimCreature(
        0x0004E507, 'Skyrim.esm', 'insect',
        'Giant Frostbite Spider',
        0x00000000, '', 0x0002AFD9, 'Skyrim.esm',
        0x00041446, 0x00044CCB, 0x00021E81, 0x00053900,
        'voice:6/6 combat_style:6/6 npc_class:6/6 package_list:6/6 outfit:6/6 skin_used:4/6 (none: inherit the race)', 0x00023AAB, 'EncFrostbiteSpiderGiant'),
    'FrostbiteSpiderRaceLarge': SkyrimCreature(
        0x00053477, 'Skyrim.esm', 'insect',
        'Large Frostbite Spider',
        0x00000000, '', 0x0001F21D, 'Skyrim.esm',
        0x00041446, 0x00044CCB, 0x00021E81, 0x00053900,
        'voice:4/6 combat_style:6/6 npc_class:6/6 package_list:6/6 outfit:6/6 skin_used:4/6 (none: inherit the race)', 0x00041FB4, 'EncFrostbiteSpiderLarge'),
    'ccBGSSSE025_ElytraRace': SkyrimCreature(
        0x05000A76, 'ccbgssse025-advdsgs.esm', 'insect',
        'Elytra',
        0x0003636F, 'SkinFrostbiteSpider', 0x0001F21D, 'Skyrim.esm',
        0x00041446, 0x00044CCB, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2', 0x05000B4B, 'ccBGSSSE025_ElytraNymphDementia'),
    'ccBGSSSE025_ElytraRace_PET': SkyrimCreature(
        0x05000A52, 'ccbgssse025-advdsgs.esm', 'insect',
        'Elytra (pet)',
        0x0003636F, 'SkinFrostbiteSpider', 0x0001F21D, 'Skyrim.esm',
        0x00041446, 0x00044CCB, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2', 0x05000CBB, 'ccBGSSSE025_ElytraNymphMania_PET'),

    # ---- livestock ----
    'CowRace': SkyrimCreature(
        0x0004E785, 'Skyrim.esm', 'livestock',
        'Cow',
        0x0004E784, 'SkinCow', 0x0001F15F, 'Skyrim.esm',
        0x0004DB9F, 0x0001CE17, 0x00000000, 0x00000000,
        'voice:4/4 combat_style:4/4 npc_class:4/4', 0x000C39F1, 'EncCowPainted'),
    'GoatDomesticsRace': SkyrimCreature(
        0x0006FC4A, 'Skyrim.esm', 'livestock',
        'Goat (domestic)',
        0x00000000, '', 0x0001F22A, 'Skyrim.esm',
        0x00000000, 0x00013176, 0x00000000, 0x00000000,
        'voice:1/1 npc_class:1/1 skin_used:1/1 (none: inherit the race)', 0x0005E3D2, 'AudioTemplateGoat'),
    'GoatRace': SkyrimCreature(
        0x000131FA, 'Skyrim.esm', 'livestock',
        'Goat',
        0x0006FC49, 'SkinGoatDomestic', 0x0001F22A, 'Skyrim.esm',
        0x00073F1A, 0x0001CE17, 0x00000000, 0x00000000,
        'voice:5/5 combat_style:3/5 npc_class:4/5 skin_used:3/5', 0x0001CB2C, 'DA14Goat'),

    # ---- mount ----
    'CartHorseRace': SkyrimCreature(
        0x000DE505, 'Skyrim.esm', 'mount',
        'Cart Horse',
        0x00060715, 'SkinHorse', 0x0001F232, 'Skyrim.esm',
        0x0001CF32, 0x0001CE17, 0x00021E81, 0x000C236E,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 outfit:3/3 skin_used:3/3', 0x00072A08, 'HorseForCarriageNew'),
    'HorseRace': SkyrimCreature(
        0x000131FD, 'Skyrim.esm', 'mount',
        'Horse',
        0x00060715, 'SkinHorse', 0x0001F232, 'Skyrim.esm',
        0x0001CF32, 0x0010F71E, 0x00021E81, 0x00000000,
        'voice:32/32 combat_style:32/32 npc_class:32/32 package_list:31/32', 0x00023AB2, 'EncHorseSaddledBrown'),

    # ---- troll ----
    'DLC1TrollFrostRaceArmored': SkyrimCreature(
        0x020117F4, 'Dawnguard.esm', 'troll',
        'Armored Frost Troll',
        0x02016688, 'DLC1SkinTrollFrostArmored', 0x0001F289, 'Skyrim.esm',
        0x0003F1B6, 0x000131E6, 0x0002AC7A, 0x00000000,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 skin_used:2/2', 0x0200D0B9, 'DLC1EncTrollFrostArmored'),
    'DLC1TrollRaceArmored': SkyrimCreature(
        0x020117F5, 'Dawnguard.esm', 'troll',
        'Armored Troll',
        0x02016689, 'DLC1SkinTrollArmored', 0x0001F289, 'Skyrim.esm',
        0x0003F1B6, 0x000131E6, 0x00021E81, 0x02019821,
        'voice:2/2 combat_style:2/2 npc_class:2/2 package_list:2/2 outfit:2/2 skin_used:2/2', 0x0200D0B8, 'DLC1EncTrollArmored'),
    'TrollFrostRace': SkyrimCreature(
        0x00013206, 'Skyrim.esm', 'troll',
        'Frost Troll',
        0x00016EE4, 'SkinTroll', 0x0001F289, 'Skyrim.esm',
        0x0003F1B6, 0x000131E6, 0x0002AC7A, 0x00000000,
        'voice:6/6 combat_style:6/6 npc_class:6/6 package_list:6/6 skin_used:5/6', 0x00023ABB, 'EncTrollFrost'),
    'TrollRace': SkyrimCreature(
        0x00013205, 'Skyrim.esm', 'troll',
        'Troll',
        0x00016EE4, 'SkinTroll', 0x0001F289, 'Skyrim.esm',
        0x0003F1B6, 0x000131E6, 0x00021E81, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3 skin_used:2/3', 0x00023ABA, 'EncTroll'),

    # ---- undead ----
    'DLC01SoulCairnBonemanRace': SkyrimCreature(
        0x0200A94B, 'Dawnguard.esm', 'undead',
        'Boneman',
        0x000B799A, 'SkinSkeleton', 0x00000000, '',
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
        '', 0x00000000, ''),
    'DLC1BlackSkeletonRace': SkyrimCreature(
        0x02019FD3, 'Dawnguard.esm', 'undead',
        'Black Skeleton',
        0x020071CE, 'DLC1EncSoulCairnBonemanSkin', 0x000BFB2B, 'Skyrim.esm',
        0x00038A23, 0x00017008, 0x00021E81, 0x00000000,
        'voice:7/7 combat_style:6/7 npc_class:5/7 package_list:7/7 skin_used:7/7', 0x020071AA, 'DLC1LvlSoulCairnBonemanMissile'),
    'DLC1DeathHoundCompanionRace': SkyrimCreature(
        0x02003D02, 'Dawnguard.esm', 'undead',
        'Death Hound (companion)',
        0x02015FCE, 'DLC1SkinVampireWolf', 0x02011681, 'Dawnguard.esm',
        0x00057BE8, 0x00000000, 0x00021E81, 0x00000000,
        'voice:2/2 combat_style:2/2 package_list:2/2 skin_used:2/2', 0x0201AA78, 'DLC1HireableVampireDeathhound2'),
    'DLC1DeathHoundRace': SkyrimCreature(
        0x0200C5F0, 'Dawnguard.esm', 'undead',
        'Death Hound (skinless undead dog)',
        0x02015FCE, 'DLC1SkinVampireWolf', 0x02011681, 'Dawnguard.esm',
        0x00057BE8, 0x0200D6F6, 0x00021E81, 0x00000000,
        'voice:4/4 combat_style:3/4 npc_class:3/4 package_list:4/4 skin_used:4/4', 0x02004D88, 'DLC1VQ01LvlDeathHound'),
    'DLC1SoulCairnKeeperRace': SkyrimCreature(
        0x02007AF3, 'Dawnguard.esm', 'undead',
        'Keeper',
        0x00000000, '', 0x000BFB2B, 'Skyrim.esm',
        0x00000000, 0x00023C0C, 0x00021E81, 0x02007B0C,
        'voice:3/3 npc_class:2/3 package_list:3/3 outfit:3/3 skin_used:3/3 (none: inherit the race)', 0x020074F8, 'DLC01SoulCairnKeeper2H'),
    'DLC1SoulCairnSkeletonArmorRace': SkyrimCreature(
        0x0200894D, 'Dawnguard.esm', 'undead',
        'Soul Cairn Skeleton (armored)',
        0x00000000, '', 0x000BFB2B, 'Skyrim.esm',
        0x00000D0D, 0x00000000, 0x00021E81, 0x00000000,
        'voice:4/4 combat_style:4/4 package_list:3/4 skin_used:4/4 (none: inherit the race)', 0x020045B4, 'DLC1SoulCairnWrathmanSummon'),
    'DLC1SoulCairnSkeletonNecroRace': SkyrimCreature(
        0x02006AFA, 'Dawnguard.esm', 'undead',
        'Soul Cairn Skeleton',
        0x02006AFB, 'DLC1SoulCairnSkinSkeletonNecro', 0x00000000, '',
        0x00038A24, 0x00000000, 0x00000000, 0x00000000,
        'combat_style:5/7 skin_used:6/7', 0x020045B7, 'DLC1SoulCairnMistmanSummon'),
    'SkeletonArmorRace': SkyrimCreature(
        0x020023E2, 'Dawnguard.esm', 'undead',
        'Armored Skeleton',
        0x020023E0, 'SkinSkeletonArmor', 0x000BFB2B, 'Skyrim.esm',
        0x00000000, 0x00017008, 0x00000000, 0x00000000,
        'voice:21/21 npc_class:16/21', 0x02011EC7, 'DLC1dunHarkonVCSkeletonWarrior2h_Ambush'),
    'DLC2AcolyteDragonPriestRace': SkyrimCreature(
        0x0203911A, 'Dragonborn.esm', 'undead',
        'Acolyte Dragon Priest',
        0x0003B5AB, 'SkinDragonPriest', 0x00029986, 'Skyrim.esm',
        0x000BB365, 0x0001CE1C, 0x00032AE2, 0x00000000,
        'voice:3/3 combat_style:3/3 npc_class:3/3 package_list:3/3', 0x020248E9, 'DLC2AcolyteAhzidal'),
    'DLC2AshSpawnRace': SkyrimCreature(
        0x0201B637, 'Dragonborn.esm', 'undead',
        'Ash Spawn',
        0x0202B04B, 'DLC2SkinAshSpawn', 0x02031DB8, 'Dragonborn.esm',
        0x00000000, 0x00023C0C, 0x00032AE2, 0x00000000,
        'voice:10/10 npc_class:7/10 package_list:10/10 skin_used:10/10', 0x0201B636, 'DLC2EncAshSpawn1H01'),
    'DLC2HulkingDraugrRace': SkyrimCreature(
        0x0202A6FD, 'Dragonborn.esm', 'undead',
        'Hulking Draugr',
        0x0202A6FC, 'DLC2SkinHulkingDraugr', 0x0001F1CD, 'Skyrim.esm',
        0x00086F4E, 0x00023C0C, 0x00021E81, 0x00000000,
        'voice:7/7 combat_style:7/7 npc_class:7/7 package_list:7/7 skin_used:7/7', 0x02036145, 'DLC2EncDraugrHulkingM06'),
    'DLC2RigidSkeletonRace': SkyrimCreature(
        0x0203CECB, 'Dragonborn.esm', 'undead',
        'Rigid Skeleton (prop)',
        0x000B799A, 'SkinSkeleton', 0x000BFB2B, 'Skyrim.esm',
        0x00000D0D, 0x00023C0C, 0x00021E81, 0x0203CF36,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 outfit:1/1 skin_used:1/1', 0x0203CECC, 'DLC2TT2IldariRemenant'),
    'DragonPriestRace': SkyrimCreature(
        0x000131EF, 'Skyrim.esm', 'undead',
        'Dragon Priest',
        0x0003B5AB, 'SkinDragonPriest', 0x00029986, 'Skyrim.esm',
        0x000BB365, 0x0001CE1C, 0x00032AE2, 0x00000000,
        'voice:18/18 combat_style:18/18 npc_class:18/18 package_list:18/18 skin_used:18/18', 0x0002025A, 'EncDragonPriestFire'),
    'DraugrMagicRace': SkyrimCreature(
        0x000F71DC, 'Skyrim.esm', 'undead',
        'Draugr (spellcaster)',
        0x000F71DB, 'dunLabrynthianDraugrArmorFX', 0x0001F1CD, 'Skyrim.esm',
        0x00000000, 0x00017008, 0x00000000, 0x000F82F9,
        'voice:8/8 npc_class:5/8 outfit:7/8 skin_used:8/8', 0x000F82F7, 'MG07LabyrinthianDraugrMelee1HFemale'),
    'DraugrRace': SkyrimCreature(
        0x00000D53, 'Skyrim.esm', 'undead',
        'Draugr',
        0x00016EE3, 'SkinDraugr', 0x0001F1CD, 'Skyrim.esm',
        0x00000000, 0x00023C0C, 0x00032AE2, 0x00000000,
        'voice:314/314 npc_class:209/314 package_list:255/314', 0x00023BF5, 'EncDraugr04Melee1HHeadM00'),
    'RigidSkeletonRace': SkyrimCreature(
        0x000B9FD7, 'Skyrim.esm', 'undead',
        'Rigid Skeleton (prop)',
        0x000B799A, 'SkinSkeleton', 0x000BFB2B, 'Skyrim.esm',
        0x00000D0D, 0x00023C0C, 0x00021E81, 0x00000000,
        'voice:8/10 combat_style:9/10 npc_class:10/10 package_list:10/10 skin_used:10/10', 0x00026DF0, 'DA04DroktCorpse'),
    'SkeletonNecroPriestRace': SkyrimCreature(
        0x000EBE18, 'Skyrim.esm', 'undead',
        'Skeleton (necro priest)',
        0x000EBE8F, 'SkinSkeletonNecroPriest', 0x00029986, 'Skyrim.esm',
        0x000BB365, 0x0001CE1C, 0x00032AE2, 0x00000000,
        'voice:1/1 combat_style:1/1 npc_class:1/1 package_list:1/1 skin_used:1/1', 0x000EBE2E, 'DA09ShadeUnique'),
    'SkeletonNecroRace': SkyrimCreature(
        0x000EB872, 'Skyrim.esm', 'undead',
        'Skeleton (necromancer-raised)',
        0x000B799A, 'SkinSkeleton', 0x000BFB2B, 'Skyrim.esm',
        0x00000D0D, 0x00023C0C, 0x00021E81, 0x00000000,
        'voice:12/12 combat_style:8/12 npc_class:10/12 package_list:12/12', 0x000EB876, 'EncSkeletonNecro01Melee1H'),
    'SkeletonRace': SkyrimCreature(
        0x000B7998, 'Skyrim.esm', 'undead',
        'Skeleton',
        0x000B799A, 'SkinSkeleton', 0x000BFB2B, 'Skyrim.esm',
        0x00000000, 0x00023C0C, 0x00021E81, 0x00000000,
        'voice:33/33 npc_class:27/33 package_list:32/33 skin_used:31/33', 0x0002D1DE, 'EncSkeleton01Melee1H'),

}


# Oblivion.esm -- 914 CREA records in 49 groups. Measured from export/Oblivion.esm/CREA.txt.
OBLIVION_GROUPS = {
    '_template':                   Tes4Group(  5, 0,  'Creature:5',              ['(unnamed)']),
    'baliwog':                     Tes4Group( 10, 0,  'Creature:10',             ['Baliwog', 'Young Baliwog', "Mirili's Baliwog", 'Bull Baliwog']),
    'bear/black':                  Tes4Group(  7, 0,  'Creature:7',              ['Black Bear', 'West Weald Black Bear Den Hunter', 'West Weald Black Bear Cub', 'West Weald Black Bear']),
    'bear/brown':                  Tes4Group(  7, 0,  'Creature:7',              ['Brown Bear', 'West Weald Brown Bear Den Hunter', 'West Weald Brown Bear Cub', 'West Weald Brown Bear']),
    'boar':                        Tes4Group(  5, 0,  'Creature:5',              ['Boar', 'Porkchop', '(unnamed)']),
    'clannfear':                   Tes4Group( 12, 0,  'Daedra:12',               ['Clannfear', 'Clannfear Runt']),
    'daedroth':                    Tes4Group( 10, 0,  'Daedra:10',               ['Daedroth']),
    'deer/buck':                   Tes4Group(  3, 0,  'Creature:3',              ['Deer']),
    'deer/doe':                    Tes4Group(  6, 0,  'Creature:6',              ['Deer']),
    'dog/dog':                     Tes4Group( 24, 0,  'Creature:24',             ['Dog', 'Steel Fang', 'Charlotte', "Ushnar's Dog"]),
    'dog/skinned_hound':           Tes4Group(  9, 0,  'Undead:8/Creature:1',     ['Skinned Hound', 'Greater Skinned Hound', 'Hound Corpse', "Ushnar's Skinned Hound"]),
    'dog/wolf':                    Tes4Group(  8, 0,  'Creature:7/Undead:1',     ['Timber Wolf', 'Wolf', 'Ghost Hound', 'Redmaw']),
    'elytra':                      Tes4Group( 35, 0,  'Creature:35',             ['Elytra Hatchling', 'Elytra Matron', 'Elytra', 'Elytra Drone']),
    'flameatronach':               Tes4Group(  3, 0,  'Daedra:3',                ['Flame Atronach', 'FlameAtronach']),
    'fleshatronach':               Tes4Group( 18, 0,  'Daedra:15/Undead:3',      ['Flesh Atronach', 'Mangled Flesh Atronach', 'Mended Flesh Atronach', 'Sewn Flesh Atronach']),
    'frostatronach':               Tes4Group(  7, 0,  'Daedra:7',                ['Frost Atronach', 'Frostfire Atronach Gladeguard', 'Frostfire Atronach Gladelord', 'Frostfire Atronach Gladeling']),
    'gatekeeper':                  Tes4Group( 19, 0,  'Creature:19',             ['Gatekeeper', 'GateKeeper']),
    'ghost':                       Tes4Group( 15, 0,  'Undead:15',               ['Ghost', "Llathasa's Spirit", 'Benirus Manor Ghost', 'Ancestor Guardian']),
    'gnarl':                       Tes4Group( 48, 0,  'Creature:48',             ['Germinal Gnarl', 'Gnarl Prisoner', 'TestCreatureGnarl', 'Elder Gnarl']),
    'goblin':                      Tes4Group( 95, 0,  'Creature:95',             ['Goblin', 'Goblin Berserker', 'Goblin Skirmisher', 'Goblin Shaman']),
    'grummite':                    Tes4Group(113, 0,  'Creature:113',            ['Grummite Whelp', '(unnamed)', 'Grummite Deathdealer', 'Grummite Magus Whelp']),
    'horse/mount':                 Tes4Group( 51, 51, 'Horse:51',                ['Imperial Legion Horse', 'Black Horse', 'Bay Horse', 'White Horse']),
    'horse/wild':                  Tes4Group(  4, 0,  'Creature:4',              ['Paint Horse', 'Wild Paint Horse', 'Wild Bay Horse', 'Wild Chestnut Horse']),
    'hunger':                      Tes4Group( 16, 0,  'Daedra:10/Creature:6',    ['TestCreatureHunger', 'Ravenous Hunger', 'Hunger', 'Voracious Hunger']),
    'imp':                         Tes4Group(  4, 0,  'Creature:4',              ['Imp', 'Sparky', 'Juicy Imp']),
    'jyggylag':                    Tes4Group(  9, 0,  'Creature:8/Daedra:1',     ['Jyggalag']),
    'landdreugh':                  Tes4Group(  3, 0,  'Creature:3',              ['Land Dreugh', 'LandDreugh']),
    'lich':                        Tes4Group(  6, 0,  'Undead:6',                ['Lich', 'Erandur-Vangaril', 'King of Miscarcand', 'Lorgren Benirus']),
    'mehrunesdagon':               Tes4Group(  2, 0,  'Daedra:1/Giant:1',        ['Mehrunes Dagon']),
    'minotaur':                    Tes4Group( 27, 0,  'Creature:27',             ['Minotaur', 'Minotaur of the Grove', 'Minotaur Lord', 'Dreamworld Minotaur']),
    'mountainlion':                Tes4Group( 10, 0,  'Creature:10',             ['Mountain Lion', 'Starving Mountain Lion', 'MuontainLion']),
    'mudcrab':                     Tes4Group(  5, 0,  'Creature:5',              ['Mud Crab', 'Spectral Mud Crab']),
    'murkdweller':                 Tes4Group( 17, 0,  'Creature:17',             ['Diseased Scalon', 'Hulking Scalon', 'Lurking Scalon', 'Scalon Brute']),
    'ogre':                        Tes4Group( 23, 0,  'Creature:23',             ['Ogre', 'Redguard Valley Ogre Caveboss', 'Redguard Valley Ogre Rocksmasher', 'Redguard Valley Ogre Stonewrecker']),
    'rat':                         Tes4Group( 23, 0,  'Creature:23',             ['Rat', 'Sanctified Rat of Gibbering Dreams', 'Sewer Rat', "Llevana's Tunnel Rat"]),
    'scamp':                       Tes4Group( 20, 0,  'Daedra:18/Creature:2',    ['Scamp', 'Stunted Scamp', 'ScampDefault', 'Everscamp']),
    'shambles':                    Tes4Group( 19, 0,  'Undead:19',               ['Shambles', 'Decrepit Shambles', 'Replete Shambles', 'Complete Shambles']),
    'sheep':                       Tes4Group( 16, 0,  'Creature:16',             ['Sheep', 'Tod']),
    'skeleton':                    Tes4Group( 51, 0,  'Undead:51',               ['Skeleton', 'Bregor the Cremator', 'Skeleton Hero', 'Undead Blade']),
    'slaughterfish':               Tes4Group(  9, 0,  'Creature:9',              ['Slaughterfish', 'Rumare Slaughterfish Brood Mother', 'Adult Rumare Slaughterfish', 'Rumare Slaughterfish']),
    'spiderdaedra':                Tes4Group(  5, 0,  'Daedra:4/Creature:1',     ['Spider Daedra', 'Spiderling', '(unnamed)']),
    'spriggan':                    Tes4Group(  5, 0,  'Creature:4/Humanoid:1',   ['Spriggan', 'Gnarl Sapling']),
    'stormatronach':               Tes4Group(  8, 0,  'Daedra:6/Creature:2',     ['The Sunken One', 'Storm Atronach']),
    'troll':                       Tes4Group( 24, 0,  'Creature:24',             ['Troll', 'Azhklan Troll', 'Kalperklan Troll', 'Uderfrykte Matron']),
    'willothewisp':                Tes4Group(  5, 0,  'Creature:5',              ['Will-o-the-Wisp', 'Dark Broodling']),
    'wraith/gloom':                Tes4Group(  9, 0,  'Undead:9',                ['Gloom Wraith', 'Wrath of Sithis', "Llathasa's Spirit", 'Sanctified Ancient Spectre']),
    'wraith/wraith':               Tes4Group( 14, 0,  'Undead:14',               ['Faded Wraith', 'Wraith', "Llathasa's Spirit", 'Sanctified Ancient Spectre']),
    'xivilai':                     Tes4Group( 10, 0,  'Daedra:10',               ['Xivilai', 'Medrike', 'Anaxes', 'TestCreatureXivilaiHugh02']),
    'zombie':                      Tes4Group( 60, 0,  'Undead:42/Creature:17/Humanoid:1', ['Zombie', 'Deranged Zombie', 'Headless Zombie', 'Dread Zombie']),
}


# ElsweyrAnequina.esp -- 255 CREA records in 39 groups. Measured from export/ElsweyrAnequina.esp/CREA.txt.
ELSWEYR_GROUPS = {
    'anequinaragasha':             Tes4Group( 15, 0,  'Creature:15',             ['Ragasha', 'Ragasha Shaman', 'Ragasha Skirmisher', 'Ragasha Berserker']),
    'anequinaspider':              Tes4Group( 11, 0,  'Creature:11',             ['Giant Tarantula', 'Giant Desert Spider', 'Mahdahsa']),
    'boar':                        Tes4Group(  4, 0,  'Creature:4',              ['Giant Red Sow', 'Piglet', 'Black Jungle Boar', 'Giant Red Boar']),
    'camel/mount':                 Tes4Group(  2, 2,  'Horse:2',                 ['My Camel', 'Camel']),
    'camel/wild':                  Tes4Group(  1, 0,  'Creature:1',              ['Camel']),
    'clannfear':                   Tes4Group(  1, 0,  'Creature:1',              ['Nequinal Lizard']),
    'deer/antelope':               Tes4Group(  1, 0,  'Creature:1',              ['Desert Antelope']),
    'deer/sload_abomination':      Tes4Group(  1, 0,  'Creature:1',              ['Sload Abomination']),
    'deer/whitestag':              Tes4Group(  1, 0,  'Creature:1',              ['Great White Stag']),
    'dog/durzog':                  Tes4Group( 10, 0,  'Creature:10',             ['Red Durzog', 'Black Durzog', 'Green Durzog', 'Grey Durzog']),
    'dog/redwolf':                 Tes4Group(  3, 0,  'Creature:3',              ['Red Wolf', 'Red Wolf Pack Leader']),
    'elephant/mount':              Tes4Group( 12, 12, 'Horse:12',                ["Merchant's Elephant", 'Elephant', 'Pack Elephant', 'War Elephant']),
    'elephant/wild':               Tes4Group(  4, 0,  'Creature:4',              ['The Great Bull Elephant', 'Bull Elephant', 'Elephant Cow', 'Elephant Calf']),
    'ghost':                       Tes4Group(  1, 0,  'Undead:1',                ['Ghost of Infant']),
    'goblin/ape':                  Tes4Group(  5, 0,  'Creature:5',              ['Monkey', 'Tenmar Ape']),
    'horse/mount':                 Tes4Group(  9, 9,  'Horse:9',                 ['Imperial Legion Horse', "Marius Caro's Stallion", "Black Courier's Horse", "Udakhu's Courier Horse"]),
    'horse/zebra':                 Tes4Group(  3, 2,  'Horse:2/Creature:1',      ['Zebra Stallion', 'My Zebra', 'Zebra']),
    'minotaur':                    Tes4Group( 42, 0,  'Creature:42',             ['Black Minotaur', 'Golden Minotaur', 'Minotaur Bull', 'Minotaur Cow']),
    'mountainlion/alfiq':          Tes4Group( 27, 0,  'Creature:27',             ['Alfiq', 'Nipper', "Jazaska's Alfiq", "Z'lil"]),
    'mountainlion/leopard':        Tes4Group(  4, 0,  'Creature:4',              ['Leopard']),
    'mountainlion/lion':           Tes4Group( 10, 0,  'Creature:10',             ['Lioness', 'Royal Alfiq', 'Man-Eating Lioness', 'Lion']),
    'mountainlion/panther':        Tes4Group(  3, 0,  'Creature:3',              ['Black Panther', 'Black Panther Cub']),
    'mountainlion/sporecat':       Tes4Group(  3, 0,  'Creature:3',              ['Spore Cat']),
    'mountainlion/tiger':          Tes4Group(  3, 0,  'Creature:3',              ['Rabid Senche-Tiger', 'Tiger', 'Senche-Tiger']),
    'mudcrab':                     Tes4Group(  4, 0,  'Creature:4',              ['Red Sand Crab', 'Sand Crawler']),
    'pahmer':                      Tes4Group(  9, 0,  'Creature:9',              ['Pahmer', 'Dune Pahmer', "G'narr", "Ny'ari"]),
    'rat/glyptodon':               Tes4Group(  1, 0,  'Creature:1',              ['Glyptodon']),
    'rat/rat':                     Tes4Group(  3, 0,  'Creature:3',              ['Rat', 'Big Rat']),
    'runningbird/mount':           Tes4Group(  1, 1,  'Horse:1',                 ['Slarjei']),
    'runningbird/wild':            Tes4Group(  2, 0,  'Creature:2',              ['Slarjei Bird']),
    'sheep/goat':                  Tes4Group( 10, 0,  'Creature:10',             ['Nanny Goat', 'Billy Goat', 'Dead Goat', 'Billy Goat Gruff']),
    'sheep/sheep':                 Tes4Group(  4, 0,  'Creature:4',              ['Sheep']),
    'skeleton':                    Tes4Group(  1, 0,  'Undead:1',                ['Skeleton']),
    'slaughterfish':               Tes4Group( 25, 0,  'Creature:25',             ['Skipjack Tuna', 'Cod', 'Guitarfish', 'Humpback Red Snapper']),
    'spriggan':                    Tes4Group(  2, 0,  'Creature:2',              ['Spriggan of the Grotto', 'Jungle Spriggan']),
    'troll':                       Tes4Group(  3, 0,  'Creature:3',              ['Troll', 'Bridge Troll', 'Desert Troll']),
    'werecrocodile':               Tes4Group(  2, 0,  'Creature:2',              ['King of the Mere', 'Crocodilion']),
    'willothewisp':                Tes4Group(  4, 0,  'Creature:4',              ['Spirit of the East Wind', 'Spirit of the North Wind', 'Spirit of the South Wind']),
    'zombie':                      Tes4Group(  8, 0,  'Undead:8',                ['Dread Orc Zombie', 'Headless Orc Zombie', 'Orc Zombie']),
}


# --------------------------------------------------------------------------
# 4. PROPOSED SWAPS -- Oblivion.esm
#    Keys match OBLIVION_GROUPS. `None` target = keep the converted creature.
#    Hand-authored; this is the part to argue with.
# --------------------------------------------------------------------------
OBLIVION_SWAPS = {
    # ---- exact: the same creature in both games ----
    'bear/black':      Swap('BearBlackRace', EXACT,
                            'skin is SkinBearCave -- in Skyrim the black bear IS '
                            'the cave bear; not a typo'),
    'bear/brown':      Swap('BearBrownRace', EXACT),
    'boar':            Swap('DLC2BoarRace', EXACT,
                            'a bristleback is a large tusked boar; same rig. '
                            'Needs Dragonborn as a master'),
    'deer/doe':        Swap('DeerRace', EXACT,
                            'DeerRace skin is SkinReinDeer and ElkRace skin is '
                            'SkinDeer -- the vanilla names are crossed, verified'),
    'dog/dog':         Swap('DogRace', EXACT),
    'dog/wolf':        Swap('WolfRace', EXACT),
    'elytra':          Swap('ccBGSSSE025_ElytraRace', EXACT,
                            'Saints & Seducers is literally Shivering Isles '
                            'content rebuilt for Skyrim -- this is the same '
                            'creature by the same designers. 35 records covered'),
    'flameatronach':   Swap('AtronachFlameRace', EXACT),
    'frostatronach':   Swap('AtronachFrostRace', EXACT),
    'stormatronach':   Swap('AtronachStormRace', EXACT),
    'horse/mount':     Swap('HorseRace', EXACT,
                            'per-record coat + saddle in OBLIVION_MOUNT_RECORDS; '
                            'this is the swap that makes them rideable again'),
    'horse/wild':      Swap('HorseRace', EXACT,
                            'unsaddled: no DOFT, and these are DATA.Type=Creature '
                            'in TES4 so they should NOT get ActorTypeHorse'),
    'mudcrab':         Swap('MudcrabRace', EXACT,
                            'alt DLC2MudcrabSolstheimRace for the ashen variant'),
    'skeleton':        Swap('SkeletonRace', EXACT,
                            'weapon-using in both games; VNAM already permits '
                            'blades/bows. Armored variants -> SkeletonArmorRace '
                            '(Dawnguard) if the Oblivion record wears skdb parts',
                            alt=('SkeletonArmorRace', 'SkeletonNecroRace')),
    'slaughterfish':   Swap('SlaughterfishRace', EXACT),
    'spriggan':        Swap('SprigganRace', EXACT,
                            alt=('SprigganMatronRace',
                                 'ccBGSSSE025_CorruptedSprigganRaceMania')),
    'troll':           Swap('TrollRace', EXACT,
                            'a troll standing in for a troll; Skyrim\'s is a '
                            'three-eyed ape but fills the same cave-brute role'),
    'willothewisp':    Swap('WitchlightRace', EXACT,
                            'CORRECTION vs vanilla_creature_swap.py, which uses '
                            'WispRace: WispRace is the WISPMOTHER (a caster). The '
                            'small floating drain-light is WitchlightRace',
                            alt=('WispRace',)),

    # ---- near: same archetype, visibly different species ----
    'deer/buck':       Swap('ElkRace', NEAR,
                            'the Oblivion buck is antlered (antlar8point.nif), '
                            'which is what ElkRace is', alt=('DeerRace',)),
    'dog/skinned_hound': Swap('DLC1DeathHoundRace', NEAR,
                            'Dawnguard death hound is a hairless/burnt undead dog '
                            '-- much closer than a living DogRace. 9 records, 8 '
                            'of them DATA.Type=Undead in TES4'),
    'ghost':           Swap('WispShadeRace', NEAR,
                            'Skyrim has no generic ghost creature: its ghosts are '
                            'ordinary NPCs with a ghost shader. The wisp shade is '
                            'the only translucent floating humanoid race'),
    'lich':            Swap('DragonPriestRace', NEAR,
                            'robed undead spellcaster; different lore and model'),
    'minotaur':        Swap('GiantRace', NEAR,
                            'size/brute idiom only -- no bovine head anywhere in '
                            'vanilla+DLC. Beyond Skyrim CYRMinotaurRace would be '
                            'exact but is NOT installed'),
    'mountainlion':    Swap('SabreCatRace', NEAR,
                            'same big-cat rig and pounce; sabre tusks differ'),
    'ogre':            Swap('GiantRace', NEAR, 'giants are much taller'),
    'rat':             Swap('SkeeverRace', NEAR,
                            'skeever fills the rat niche but is a bigger animal'),
    'shambles':        Swap('SkeletonRace', NEAR,
                            'animated loose bones; the SI shambles is a pile, the '
                            'skeleton is articulated',
                            alt=('DLC01SoulCairnBonemanRace',)),
    'sheep':           Swap('GoatRace', NEAR,
                            'Skyrim has no sheep. GoatDomesticsRace for the tame '
                            'ones', alt=('GoatDomesticsRace',)),
    'spiderdaedra':    Swap('FrostbiteSpiderRace', NEAR,
                            'spider half only; the Dark Elf torso has no match'),
    'wraith/wraith':   Swap('WispShadeRace', NEAR, 'see ghost'),
    'wraith/gloom':    Swap('WispShadeRace', NEAR,
                            'gloom wraiths are the stronger variant; consider '
                            'DLC1SoulCairnKeeperRace for the boss-sized ones',
                            alt=('DLC1SoulCairnKeeperRace',)),
    'xivilai':         Swap(None, NONE,
                            'DECIDED 2026-08-27: leave converted. DremoraRace is '
                            'the only candidate and it is an NPC-class race on the '
                            'human skeleton, so it would need FaceGen head data '
                            'that no other row here requires',
                            alt=('DremoraRace', 'DLC2DremoraRace')),
    'zombie':          Swap('DraugrRace', NEAR,
                            'draugr are armed and armored; Oblivion zombies are '
                            'unarmed maulers. CC Plague of the Dead has a real '
                            'zombie but is not installed',
                            alt=('DLC2AshSpawnRace', 'DLC2HulkingDraugrRace')),
    'goblin':          Swap('DLC2RieklingRace', NEAR,
                            'DECIDED 2026-08-27. 95 records. Riekling = small '
                            'tribal goblinoid with spear+shield, which is what an '
                            'Oblivion goblin does. Beyond Skyrim and CC Goblins '
                            'ship a real goblin; neither is installed',
                            alt=('FalmerRace',)),
    'scamp':           Swap('DLC2RieklingRace', NEAR,
                            'small hunched daedra; nothing installed is a scamp',
                            alt=('FalmerRace',)),
    'murkdweller':     Swap('FalmerRace', NEAR,
                            'scalon = amphibious humanoid; falmer is the closest '
                            'hunched humanoid rig', alt=('DLC2LurkerRace',)),
    'grummite':        Swap('DLC2RieklingRace', NEAR,
                            'DECIDED 2026-08-27. 113 records -- the biggest group '
                            'in the plugin. Grummites are frog-folk; nothing '
                            'installed matches, and the riekling is the closest '
                            'small tribal biped', alt=('FalmerRace',)),
    'gnarl':           Swap('DLC2SprigganBurntRace', NEAR,
                            '48 records. A gnarl is a walking tree-stump; the '
                            'burnt spriggan is the woodiest thing installed',
                            alt=('SprigganRace',)),
    'daedroth':        Swap('DLC2LurkerRace', NEAR,
                            'large reptilian biped daedra -- the only one '
                            'installed with that silhouette'),
    'landdreugh':      Swap('DLC2LurkerRace', NEAR, 'crustacean biped'),
    'fleshatronach':   Swap('dlc2AshGuardianRace', NEAR,
                            'elemental golem assembled from matter; ash vs flesh'),
    'gatekeeper':      Swap('GiantRace', NEAR,
                            'unique SI boss -- size stand-in only. Probably '
                            'better left converted'),

    # ---- none installed comes close ----
    'clannfear':       Swap(None, NONE, 'raptor-lizard daedra; nothing matches'),
    'hunger':          Swap(None, NONE, 'SI unique; long-tongued quadruped'),
    'imp':             Swap(None, NONE, 'no small flying daedra in Skyrim'),
    'jyggylag':        Swap(None, NONE, 'unique SI boss'),
    'mehrunesdagon':   Swap(None, NONE, 'unique boss'),
    'baliwog':         Swap(None, NONE, 'SI amphibian', alt=('DLC2AshHopperRace',)),
    '_template':       Swap(None, NONE,
                            '5 records with no model at all -- levelled/template '
                            'shells. Never swap these'),
}


# --------------------------------------------------------------------------
# 5. PROPOSED SWAPS -- ElsweyrAnequina.esp
# --------------------------------------------------------------------------
ELSWEYR_SWAPS = {
    # ---- exact ----
    'deer/whitestag':  Swap('WhiteStagRace', EXACT,
                            'Great White Stag <-> Skyrim White Stag; the Oblivion '
                            'record even uses anequinastagwhite.nif'),
    'dog/redwolf':     Swap('WolfRace', EXACT),
    'horse/mount':     Swap('HorseRace', EXACT, 'see ELSWEYR_MOUNT_RECORDS'),
    'mudcrab':         Swap('MudcrabRace', EXACT,
                            'Red Sand Crab / Sand Crawler on the mudcrab rig'),
    'sheep/goat':      Swap('GoatRace', EXACT,
                            '10 records literally named Nanny/Billy Goat -- an '
                            'exact match Oblivion.esm itself never had',
                            alt=('GoatDomesticsRace',)),
    'skeleton':        Swap('SkeletonRace', EXACT),
    'spriggan':        Swap('SprigganRace', EXACT),
    'troll':           Swap('TrollRace', EXACT),
    'willothewisp':    Swap('WitchlightRace', EXACT,
                            'the three "Spirit of the * Wind" records',
                            alt=('WispRace',)),
    'anequinaspider':  Swap('FrostbiteSpiderRace', EXACT,
                            'Giant Tarantula / Giant Desert Spider',
                            alt=('FrostbiteSpiderRaceGiant',
                                 'DLC2ExpSpiderBaseRace')),
    'boar':            Swap('DLC2BoarRace', EXACT),

    # ---- near ----
    'elephant/mount':  Swap(None, NONE,
                            'DECIDED 2026-08-27: leave converted for now. '
                            'MammothRace is the right look (a mammoth IS a furry '
                            'elephant) but vanilla mammoths are not rideable, and '
                            '12 of these 16 records are DATA.Type=4 mounts. '
                            'Revisit together with the mount-behavior work',
                            alt=('MammothRace',)),
    'elephant/wild':   Swap(None, NONE,
                            'DECIDED 2026-08-27: left with the mounts so the herd '
                            'stays visually consistent -- swapping only the 4 wild '
                            'ones would put mammoths next to Oblivion elephants',
                            alt=('MammothRace',)),
    'horse/zebra':     Swap('HorseRace', NEAR,
                            'no zebra anywhere; SkinHorseBlacknWhiteHide is the '
                            'closest coat (black and white pinto)'),
    'minotaur':        Swap('GiantRace', NEAR, '42 records; see Oblivion minotaur'),
    'mountainlion/lion':     Swap('SabreCatRace', NEAR),
    'mountainlion/leopard':  Swap('SabreCatRace', NEAR),
    'mountainlion/panther':  Swap('SabreCatRace', NEAR),
    'mountainlion/tiger':    Swap('SabreCatRace', NEAR, 'Senche-Tiger'),
    'mountainlion/sporecat': Swap('SabreCatRace', NEAR),
    'pahmer':          Swap('SabreCatRace', NEAR, 'large feline on its own rig'),
    'rat/rat':         Swap('SkeeverRace', NEAR),
    'sheep/sheep':     Swap('GoatRace', NEAR, 'Skyrim has no sheep'),
    'slaughterfish':   Swap(None, NONE,
                            'DECIDED 2026-08-27: keep converted. 25 records of '
                            'real-world fish (tuna, cod, wrasse...). Skyrim has '
                            'exactly one fish rig, so a swap would turn the whole '
                            'aquarium into slaughterfish. They are set dressing, '
                            'not combatants', alt=('SlaughterfishRace',)),
    'zombie':          Swap('DraugrRace', NEAR, 'Orc zombies'),
    'ghost':           Swap('WispShadeRace', NEAR, 'single record, Ghost of Infant'),
    'deer/antelope':   Swap('DeerRace', NEAR,
                            'addax on the deer rig', alt=('ElkRace',)),
    'dog/durzog':      Swap('DLC1DeathHoundRace', NEAR,
                            'a durzog is a hairless reptilian war-dog; the death '
                            'hound is the only hairless dog installed',
                            alt=('DogRace',)),
    'anequinaragasha': Swap('FalmerRace', NEAR,
                            'CAREFUL: these are built from Warhammer SKAVEN meshes '
                            '(skavenchest/skavenhandl...), i.e. ratmen, not '
                            'goblins, despite two records named "Desert Goblin". '
                            'Falmer is the closest hunched tribal humanoid',
                            alt=('DLC2RieklingRace',)),
    'werecrocodile':   Swap('WerewolfBeastRace', NEAR,
                            'beast-man rig; nothing crocodilian exists',
                            alt=('DLC2WerebearBeastRace',)),
    'mountainlion/alfiq': Swap(None, REMOVE,
                            'DECIDED 2026-08-27: delete, do not substitute. An '
                            'alfiq is a HOUSE-CAT-sized Khajiit and Skyrim has no '
                            'small feline at all -- FoxRace matches the size only, '
                            'on a canine rig. See ALFIQ_REMOVAL for the measured '
                            'scope and the one script that blocks a clean sweep'),

    # ---- none ----
    'camel/mount':     Swap('HorseRace', NEAR,
                            'DECIDED 2026-08-27: camel -> horse in a random coat '
                            '(random_coat(), keyed on the source FormID so it is '
                            'stable across rebuilds). 2 records, both DATA.Type=4, '
                            'so this also restores rideability. The FULL names '
                            'still say "Camel" -- see RENAME_SUGGESTIONS'),
    'camel/wild':      Swap('HorseRace', NEAR,
                            'DECIDED 2026-08-27: same, 1 record, unsaddled'),
    'runningbird/mount': Swap('DogRace', NEAR,
                            'DECIDED 2026-08-27: Slarjei -> dog. NOTE this record '
                            'is DATA.Type=4 (a mount) and DogRace is not '
                            'mountable, so the Slarjei stops being rideable. If '
                            'that matters, this one record should go to HorseRace '
                            'instead', alt=('HorseRace',)),
    'runningbird/wild':  Swap('DogRace', NEAR,
                            'DECIDED 2026-08-27: 2 records, not mounts -- clean'),
    'clannfear':       Swap(None, NONE, 'Nequinal Lizard on the clannfear rig'),
    'goblin/ape':      Swap(None, NONE,
                            'Monkey / Tenmar Ape -- folder says goblin, meshes say '
                            'anequinaape*. No primate exists in Skyrim'),
    'rat/glyptodon':   Swap(None, NONE, 'armadillo; nothing close'),
    'deer/sload_abomination': Swap(None, NONE,
                            'anequinaskeletonshark.nif on the deer skeleton'),
}


# --------------------------------------------------------------------------
# 5b. REMOVALS -- creatures deleted outright rather than substituted.
#     Everything below was counted in export/ElsweyrAnequina.esp/ this session.
# --------------------------------------------------------------------------

ALFIQ_REMOVAL = {
    'base_records': 27,      # CREA with an anequinaalfiq*.nif body part
    'placed_refs': 30,       # ACRE (TES4 placed creature) refs, 21 distinct bases
    'leveled_lists': 15,     # LVLC lists that name an alfiq...
    'leveled_entries': 41,   # ...and how many entries have to come out
    'quest_refs': 0,         # NO INFO / QUST / PACK reference any of them
    'script_refs': 1,        # exactly one, below
    'note': (
        "Despite the individual names (J'Shani, Z'lil, K'vigi, Skooma Cat, "
        'Alfiq Guard...) NOT ONE alfiq is referenced by dialogue, a quest or an '
        'AI package -- checked every .txt in the export. They are decoration, so '
        'deleting them is safe. Three layers have to be cleaned or the game gets '
        'null references: the base records, the 30 placed ACRE refs, and the 41 '
        'leveled-list entries. Removing only the base records is the failure mode '
        'to avoid.'),
}

# The one alfiq that a clean sweep cannot simply delete.
ALFIQ_SUMMON_EXCEPTION = {
    'base': 0x010121EC,           # ANQCreatureAlfiqBrownSummon
    'script': 'ANQSummonsAlfiqBrown',
    'note': (
        'a ScriptEffectStart block does `player.PlaceAtMe '
        'ANQCreatureAlfiqBrownSummon` -- a summonable alfiq pet. Deleting the '
        'base record leaves the spell summoning nothing. Three options: (a) keep '
        'this ONE record alive (it is never placed in the world, only summoned), '
        '(b) repoint the script at another creature, (c) drop the spell too. '
        'Nothing else in the plugin depends on it.'),
}

REMOVALS = {
    'ElsweyrAnequina.esp': {'mountainlion/alfiq': ALFIQ_REMOVAL},
    'Oblivion.esm': {},
}


# --------------------------------------------------------------------------
# 5c. Cosmetic follow-ups a swap creates but does not fix by itself.
# --------------------------------------------------------------------------

# Swapping the race does not touch FULL. A camel that looks like a horse but is
# still called "Camel" reads as a bug, so these are the names worth changing at
# the same time. Suggestions only -- nothing applies them.
RENAME_SUGGESTIONS = {
    0x010AE9CC: ('My Camel', 'My Horse'),        # ANQCamelPC
    0x01017299: ('Camel', 'Horse'),              # ANQCamelMount
    0x0101727C: ('Camel', 'Horse'),              # ANQCreatureCamel
    0x01062918: ('Slarjei', 'Hound'),            # ANQSlarjeiMount
    0x0106EAB4: ('Slarjei Bird', 'Hound'),       # ANQCreatureSlarjeiBird
    0x0108A71D: ('Slarjei Bird', 'Hound'),       # ANQTRBQwazaniSlarjeiBird
}


# Skins that need care when a row above is actually implemented. Read out of
# the plugins, not remembered.
SKIN_CAVEATS = {
    'DLC2RieklingRace': (
        "the race's own WNAM is DLC2SkinRieklingChief 0x020354E2 -- the CHIEF "
        "skin. For rank-and-file rieklings use DLC2SkinRiekling01 0x02017F46, "
        "which is what DLC2ThirskRieklingRace points at"),
    'DLC2AshSpawnRace': (
        'this race has NO WNAM at all (skin FormID 0). Every ash spawn actor '
        'supplies its own skin, so a swap must pick one explicitly'),
    'DremoraRace': (
        'skin is SkinNaked 0x00000D64 -- it is an NPC-class race on the human '
        'skeleton and needs FaceGen head data like any NPC, unlike every other '
        'row in these tables'),
    'ccBGSSSE025_GoldenSaintRace': ('same as DremoraRace -- SkinNaked, humanoid'),
    'ccBGSSSE025_DarkSeducerRace': ('same as DremoraRace -- SkinNaked, humanoid'),
}


# --------------------------------------------------------------------------
# 6. MOUNTS -- the horse layer
# --------------------------------------------------------------------------

# Everything a vanilla Skyrim mount actor carries. Verified on
# WhiterunPlayerHorse 00109E3D / EncHorseSaddledBrown 00023AB2 /
# HorseForCarriageNew 00072A08 (Skyrim.esm).
VANILLA_MOUNT_ACTOR = {
    'RNAM': 0x000131FD,   # HorseRace
    'ATKR': 0x000131FD,   # attack race
    'KWDA': 0x00026110,   # ActorTypeHorse -- on the NPC_, NOT on the RACE
    'VTCK': 0x0001F232,   # CrHorseVoice
    'CNAM': 0x0010F71E,   # EncClassHorse
    'ACBS_FLAGS': 0x00040018,
    'DOFT_SADDLED': 0x00060798,   # HorseSaddleOutfit
    'DOFT_CART': 0x000C236E,      # HorseHarnessOutfit01 (CartHorseRace only)
    'PACK_PADDOCK': 0x00109AB2,   # PlayerHorseWaitInPaddock (owned horses)
}

# RACE Mount Data, for the record. MEASURED: identical on all 99 Skyrim.esm
# races, so this is a CK default and NOT what makes an actor mountable.
# creature_races.py's DogRace template already emits these exact bytes.
RACE_MOUNT_DATA_DEFAULT = {
    'mount_offset':   (-63.479, 0.0, 0.0),
    'dismount_offset': (-50.0, 0.0, 65.0),
    'camera_offset':  (0.0, -300.0, 0.0),
}

# Oblivion coat -> Skyrim coat. The AUTHORED indicator is the body NIF in the
# CREA's NIFZ list, not the FULL name (both agree here, but the NIF is what the
# converter can key on). Skin ARMO ids read out of Skyrim.esm.
HORSE_COATS = {
    # oblivion body nif   skin ARMO      skin EditorID              vanilla actor
    'horse.nif':      (0x00060715, 'SkinHorse',                'EncHorseBrown'),
    'horseblack.nif': (0x0008650D, 'SkinHorseBlackHide',       'EncHorseBlack'),
    'horsepaint.nif': (0x00086510, 'SkinHorseBlacknWhiteHide', 'EncHorseBlackAndWhite'),
    'horsegrey.nif':  (0x0008650F, 'SkinHorseGreyHide',        'EncHorseGrey'),
    'horsechestnut.nif': (0x0008650E, 'SkinHorsePalominoHide', 'EncHorsePalomino'),
}

# Draw order for random_coat(). Bay first because it is the vanilla default
# and the most common coat in both games.
RANDOM_COAT_ORDER = ('horse.nif', 'horseblack.nif', 'horsechestnut.nif',
                     'horsegrey.nif', 'horsepaint.nif')


# Named horses that have a real vanilla counterpart rather than just a coat.
HORSE_SPECIALS = {
    # Oblivion EditorID       skin ARMO    note
    'Dark10Horse': (0x00086503, 'SkinHorseShadowmere',
                    'Shadowmere exists in BOTH games. Skyrim ships the actor '
                    'Shadowmere 0009CCD7 (red eyes, own DOFT 00109C3E). The '
                    'Oblivion record already uses horseblack + lefteyered/'
                    'righteyered + DB tack, so this is the same horse'),
    'DAHircineUnicorn': (0x0008650F, 'SkinHorseGreyHide',
                    'no unicorn in Skyrim. Grey coat is the right base; the horn '
                    '(horn.nif) would have to stay as a converted extra part, or '
                    'the record stays fully converted'),
}

# What to do with the non-horse mounts. All are DATA.Type=4 in TES4.
MOUNT_SWAPS = {
    'Oblivion.esm/horse':      ('HorseRace', EXACT,
                                '51 mount records + 4 wild. Coat per record from '
                                'HORSE_COATS; straight swap'),
    'ElsweyrAnequina.esp/horse': ('HorseRace', EXACT, '9 mount records'),
    'ElsweyrAnequina.esp/zebra': ('HorseRace', NEAR,
                                'use SkinHorseBlacknWhiteHide; stripes are lost'),
    'ElsweyrAnequina.esp/camel': ('HorseRace', NEAR,
                                'DECIDED 2026-08-27: swap, coat chosen by '
                                'random_coat(source_formid). 2 mounts + 1 wild'),
    'ElsweyrAnequina.esp/runningbird': ('DogRace', NEAR,
                                'DECIDED 2026-08-27: Slarjei -> dog. The one '
                                'DATA.Type=4 record (ANQSlarjeiMount 0x01062918) '
                                'loses rideability, because DogRace has no mount '
                                'states. Send that single record to HorseRace '
                                'instead if riding it matters'),
    'ElsweyrAnequina.esp/elephant': (None, NONE,
                                'DECIDED 2026-08-27: not touched. MammothRace is '
                                'the right look but vanilla mammoths cannot be '
                                'ridden and 12 of 16 records are mounts'),
}


# --------------------------------------------------------------------------
# 7. Per-record mount census. Straight from the exports -- coat and saddle are
#    read off the NIFZ list, is_mount is TES4 CREA DATA.Type == 4.
# --------------------------------------------------------------------------


OBLIVION_MOUNT_RECORDS = [
    # (FormID, EditorID, name, coat, saddled, is_mount)
    (0x0001F11D, 'HorseBay',                          'Bay Horse',                       'bay',       True,  True),
    (0x000A55ED, 'HorseBay0StayCurrent',              'Bay Horse',                       'bay',       True,  True),
    (0x000538A5, 'HorseBay0StayPut',                  'Bay Horse',                       'bay',       True,  True),
    (0x0000CF22, 'HorseBayClaudeMaric',               'Bay Horse',                       'bay',       True,  True),
    (0x0018D4CD, 'DEADHorseBlack',                    'Black Horse',                     'black',     True,  True),
    (0x00097FC8, 'E3Horse',                           'Black Horse',                     'black',     True,  True),
    (0x0001F11A, 'HorseBlack',                        'Black Horse',                     'black',     True,  True),
    (0x000538A6, 'HorseBlack0StayPut',                'Black Horse',                     'black',     True,  True),
    (0x000BE331, 'HorseBlackCourier1',                'Black Horse',                     'black',     True,  True),
    (0x000BE547, 'HorseBlackCourier2',                'Black Horse',                     'black',     True,  True),
    (0x000BE54F, 'HorseBlackCourier3',                'Black Horse',                     'black',     True,  True),
    (0x000BE556, 'HorseBlackCourier4',                'Black Horse',                     'black',     True,  True),
    (0x0007B78E, 'MS45HorseBlossom',                  'Blossom',                         'paint',     True,  True),
    (0x00015B92, 'HorseChestnut',                     'Chestnut Horse',                  'chestnut',  True,  True),
    (0x000538A7, 'HorseChestnut0StayPut',             'Chestnut Horse',                  'chestnut',  True,  True),
    (0x0002D6DE, 'TestHorseSkeleton',                 'Horse',                           'paint',     True,  True),
    (0x000700D5, 'ImpLegionHorseAleswell',            'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D1, 'ImpLegionHorseAnvil',               'Imperial Legion Horse',           'bay',       True,  True),
    (0x0018BA8B, 'ImpLegionHorseChey',                'Imperial Legion Horse',           'bay',       True,  True),
    (0x0018BA8A, 'ImpLegionHorseChorrol',             'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D4, 'ImpLegionHorseCrossroads',          'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D7, 'ImpLegionHorseFalls',               'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D8, 'ImpLegionHorseGottshaw',            'Imperial Legion Horse',           'bay',       True,  True),
    (0x0018BA8C, 'ImpLegionHorseLey',                 'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D6, 'ImpLegionHorseNikel',               'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700CE, 'ImpLegionHorseRidge',               'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700DB, 'ImpLegionHorseRock',                'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D0, 'ImpLegionHorseRoxey',               'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700CF, 'ImpLegionHorseSardavar',            'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D2, 'ImpLegionHorseSlope',               'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D9, 'ImpLegionHorseVirtue',              'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700DA, 'ImpLegionHorseWell',                'Imperial Legion Horse',           'bay',       True,  True),
    (0x000700D3, 'ImpLegionHorseWellspring',          'Imperial Legion Horse',           'bay',       True,  True),
    (0x0004DE8E, 'HorsePCBayBravil',                  'My Bay Horse',                    'bay',       True,  True),
    (0x0004E28B, 'HorsePCBaySkingrad',                'My Bay Horse',                    'bay',       True,  True),
    (0x0004DE8F, 'HorsePCBlackCheydinhal',            'My Black Horse',                  'black',     True,  True),
    (0x0004DE90, 'HorsePCChestnutChorrol',            'My Chestnut Horse',               'chestnut',  True,  True),
    (0x0004DE91, 'HorsePCPaintBruma',                 'My Paint Horse',                  'paint',     True,  True),
    (0x0005322D, 'HorsePCPaintLeyawiin',              'My Paint Horse',                  'paint',     True,  True),
    (0x0004DE8D, 'HorsePCWhiteAnvil',                 'My White Horse',                  'grey',      True,  True),
    (0x0018AD8A, 'DEADCreatureHorsePaint',            'Paint Horse',                     'paint',     False, False),
    (0x0001F11E, 'HorsePaint',                        'Paint Horse',                     'paint',     True,  True),
    (0x000914D3, 'HorsePaint0StayCurrent',            'Paint Horse',                     'paint',     True,  True),
    (0x000538A8, 'HorsePaint0StayPut',                'Paint Horse',                     'paint',     True,  True),
    (0x0005DCC9, 'MQHorsePaint0WeynonPlayer',         "Prior Maborel's Paint Horse",     'paint',     True,  True),
    (0x00032BF4, 'Dark10Horse',                       'Shadowmere',                      'black',     True,  True),
    (0x0001EC58, 'DAHircineUnicorn',                  'Unicorn',                         'grey',      False, True),
    (0x000C01AD, 'MQHorseJauffre',                    'Weynon Priory Horse',             'chestnut',  True,  True),
    (0x000C01AC, 'MQHorseMartin',                     'Weynon Priory Horse',             'bay',       True,  True),
    (0x0001F11B, 'HorseWhite',                        'White Horse',                     'grey',      True,  True),
    (0x00115E38, 'HorseWhite0StayCurrent',            'White Horse',                     'grey',      True,  True),
    (0x000538A9, 'HorseWhite0StayPut',                'White Horse',                     'grey',      True,  True),
    (0x00015B90, 'CreatureHorseBay',                  'Wild Bay Horse',                  'bay',       False, False),
    (0x0001F11C, 'CreatureHorseChestnut',             'Wild Chestnut Horse',             'chestnut',  False, False),
    (0x00015B93, 'CreatureHorsePaint',                'Wild Paint Horse',                'paint',     False, False),
]


ELSWEYR_MOUNT_RECORDS = [
    # (FormID, EditorID, name, coat, saddled, is_mount)
    (0x01017299, 'ANQCamelMount',                     'Camel',                           'anequinacamel', False, True),
    (0x0101727C, 'ANQCreatureCamel',                  'Camel',                           'anequinacamel', False, False),
    (0x010AE9CC, 'ANQCamelPC',                        'My Camel',                        'anequinacamel', False, True),
    (0x010030F7, 'ANQCreatureElephantBull',           'Bull Elephant',                   'anequinaelephant', False, False),
    (0x0105AF0A, 'ANQElephantCorralBull',             'Elephant',                        'anequinaelephant', False, True),
    (0x0100582B, 'ANQElephantCorralCow',              'Elephant',                        'anequinaelephant', False, True),
    (0x010030F9, 'ANQCreatureElephantCalf',           'Elephant Calf',                   'anequinaelephant', False, False),
    (0x010030F8, 'ANQCreatureElephantCow',            'Elephant Cow',                    'anequinaelephant', False, False),
    (0x0105AF07, 'ANQElephantMount',                  'Elephant Mount',                  'anequinaelephant', False, True),
    (0x010017C1, 'ANQElephantMerchant',               "Merchant's Elephant",             'anequinaelephant', True,  True),
    (0x0100F48E, 'ANQElephantMerchant1',              "Merchant's Elephant",             'anequinaelephant', True,  True),
    (0x0100F496, 'ANQElephantMerchant2',              "Merchant's Elephant",             'anequinaelephant', True,  True),
    (0x0100F4A2, 'ANQElephantMerchant3',              "Merchant's Elephant",             'anequinaelephant', False, True),
    (0x0105AF09, 'ANQElephantPC',                     'My Elephant',                     'anequinaelephant', True,  True),
    (0x01018949, 'ANQCORElephantPack',                'Pack Elephant',                   'anequinaelephant', True,  True),
    (0x01001C85, 'ANQElephantPack',                   'Pack Elephant',                   'anequinaelephant', True,  True),
    (0x0107698F, 'ANQHG09ElephantBull',               'The Great Bull Elephant',         'anequinaelephant', False, False),
    (0x01001C87, 'ANQElephantWar',                    'War Elephant',                    'anequinaelephant', True,  True),
    (0x01001C86, 'ANQElephantWarAxe',                 'War Elephant',                    'anequinaelephant', True,  True),
    (0x01062918, 'ANQSlarjeiMount',                   'Slarjei',                         'anequinarunningbird', False, True),
    (0x0106EAB4, 'ANQCreatureSlarjeiBird',            'Slarjei Bird',                    'anequinarunningbird', False, False),
    (0x0108A71D, 'ANQTRBQwazaniSlarjeiBird',          'Slarjei Bird',                    'anequinarunningbird', False, False),
    (0x010BDE18, 'ANQTG02HorseBlackCourier',          "Black Courier's Horse",           'black',     True,  True),
    (0x010B196A, 'ANQTG02HorseOldNag',                'Flea-Bitten Nag',                 'paint',     False, True),
    (0x0100F483, 'ANQImpLegionHorseDarkarn',          'Imperial Legion Horse',           'bay',       True,  True),
    (0x010BDE0C, 'ANQImpLegionHorseRiverhold',        'Imperial Legion Horse',           'bay',       True,  True),
    (0x010B5DAC, 'ANQLGNHorseRiverkeep',              'Imperial Legion Horse',           'bay',       True,  True),
    (0x010BDE2D, 'ANQTG02HorseWhite',                 "Marius Caro's Horse",             'grey',      False, True),
    (0x010BDE17, 'ANQTG02MariusCarosHorse',           "Marius Caro's Stallion",          'grey',      True,  True),
    (0x010BE66D, 'ANQZebraPC',                        'My Zebra',                        'horse',     True,  True),
    (0x010BDE20, 'ANQTG02HorseBlack',                 "Udakhu's Courier Horse",          'black',     False, True),
    (0x010BDE28, 'ANQTG02HorseBay',                   "Udakhu's Legion Horse",           'bay',       False, True),
    (0x01000FF3, 'ANQCreatureZebra',                  'Zebra',                           'horse',     False, False),
    (0x01076989, 'ANQHG03ZebraStallion',              'Zebra Stallion',                  'horse',     True,  True),
]


# --------------------------------------------------------------------------
# 8. Helpers -- grouping and lookup, so the tables above can actually be applied
#    to a CREA record instead of being read by eye.
# --------------------------------------------------------------------------

PLUGIN_GROUPS = {
    'Oblivion.esm': ('OBLIVION_GROUPS', 'OBLIVION_SWAPS'),
    'ElsweyrAnequina.esp': ('ELSWEYR_GROUPS', 'ELSWEYR_SWAPS'),
}


def _folder_of(model_path):
    """'Creatures\\MountainLion\\Skeleton.NIF' -> 'mountainlion'."""
    parts = [p for p in (model_path or '').replace('/', '\\').split('\\') if p]
    return parts[-2].lower() if len(parts) >= 2 else ''


def group_key_oblivion(folder, nifz, data_type):
    """Which OBLIVION_GROUPS row a CREA belongs to.

    `folder` from _folder_of(Model.MODL), `nifz` the lowercased NIFZ list,
    `data_type` the TES4 CREA DATA.Type int (4 == Horse).
    """
    nz = set(nifz or ())
    if folder == 'dog':
        if 'skeletal hound.nif' in nz:
            return 'dog/skinned_hound'
        if 'wolfbody.nif' in nz:
            return 'dog/wolf'
        return 'dog/dog'
    if folder == 'bear':
        return 'bear/black' if 'blackbearbody.nif' in nz else 'bear/brown'
    if folder == 'deer':
        return 'deer/buck' if 'skinbuck.nif' in nz else 'deer/doe'
    if folder == 'wraith':
        return 'wraith/gloom' if 'wraithlord.nif' in nz else 'wraith/wraith'
    if folder == 'horse':
        return 'horse/mount' if data_type == 4 else 'horse/wild'
    return folder or '_template'


def group_key_elsweyr(folder, nifz, data_type, full=''):
    """Which ELSWEYR_GROUPS row a CREA belongs to.

    Elsweyr reuses Oblivion folder names for completely different animals
    (`goblin` holds apes, `sheep` holds goats, `deer` holds a shark), so the
    body-part set is the only honest key -- see the folder/body-set warning in
    docs/creature_race_equivalence.md.
    """
    nz = set(nifz or ())
    low = (full or '').lower()
    if folder == 'mountainlion':
        for key, tok in (('alfiq', 'alfiq'), ('leopard', 'leopard'),
                         ('panther', 'panther'), ('tiger', 'tiger'),
                         ('sporecat', 'bloodcat')):
            if any(tok in n for n in nz):
                return 'mountainlion/' + key
        return 'mountainlion/lion'
    if folder == 'dog':
        return 'dog/durzog' if any('durzog' in n for n in nz) else 'dog/redwolf'
    if folder == 'deer':
        if any('stag' in n for n in nz):
            return 'deer/whitestag'
        if any('addax' in n for n in nz):
            return 'deer/antelope'
        return 'deer/sload_abomination'
    if folder == 'rat':
        return 'rat/glyptodon' if any('glyptodon' in n for n in nz) else 'rat/rat'
    if folder == 'sheep':
        return 'sheep/goat' if any('goat' in n for n in nz) else 'sheep/sheep'
    if folder == 'goblin':
        return 'goblin/ape'
    if folder == 'horse':
        if 'zebra' in low:
            return 'horse/zebra'
        return 'horse/mount' if data_type == 4 else 'horse/wild'
    if folder == 'anequinarunningbird':
        return 'runningbird/mount' if data_type == 4 else 'runningbird/wild'
    if folder == 'anequinaelephant':
        return 'elephant/mount' if data_type == 4 else 'elephant/wild'
    if folder == 'anequinacamel':
        return 'camel/mount' if data_type == 4 else 'camel/wild'
    return folder or '_template'


def resolve(plugin, group, allow_near=False):
    """(SkyrimCreature, Swap) proposed for `group`, or (None, Swap|None)."""
    swaps = {'Oblivion.esm': OBLIVION_SWAPS,
             'ElsweyrAnequina.esp': ELSWEYR_SWAPS}.get(plugin)
    if swaps is None:
        raise KeyError('no swap table for %r' % plugin)
    swap = swaps.get(group)
    if swap is None or swap.target is None:
        return None, swap
    if swap.tier == NEAR and not allow_near:
        return None, swap
    return SKYRIM_CREATURES[swap.target], swap


def horse_coat(nifz):
    """(skin_formid, skin_edid, vanilla_actor) for a TES4 horse's NIFZ list."""
    for nif, row in HORSE_COATS.items():
        if nif in set(nifz or ()):
            return row
    return HORSE_COATS['horse.nif']


def random_coat(source_formid):
    """A stable pseudo-random coat for a creature that has none of its own.

    Used for the camels. The draw is keyed on the AUTHORED source FormID and
    uses crc32 rather than hash(), so it is identical on every machine and on
    every rebuild -- a coat that moved between builds would look like a bug.
    """
    import zlib
    idx = zlib.crc32(b'%08X' % (source_formid & 0xFFFFFF)) % len(RANDOM_COAT_ORDER)
    return HORSE_COATS[RANDOM_COAT_ORDER[idx]]


def coverage(plugin):
    """Records per tier for one plugin."""
    groups, swaps = ({'Oblivion.esm': (OBLIVION_GROUPS, OBLIVION_SWAPS),
                      'ElsweyrAnequina.esp': (ELSWEYR_GROUPS, ELSWEYR_SWAPS)}
                     [plugin])
    tally = {EXACT: 0, NEAR: 0, NONE: 0, REMOVE: 0, 'unmapped': 0}
    for key, grp in groups.items():
        swap = swaps.get(key)
        if swap is None:
            tally['unmapped'] += grp.count
        else:
            tally[swap.tier] += grp.count
    return tally


def report():
    """Print the whole proposal. `python patch_folder/sources/creature_changes.py`"""
    print('Skyrim creature races available: %d' % len(SKYRIM_CREATURES))
    by_plugin = {}
    for c in SKYRIM_CREATURES.values():
        by_plugin[c.plugin] = by_plugin.get(c.plugin, 0) + 1
    for p, n in sorted(by_plugin.items()):
        print('   %-28s %3d' % (p, n))

    for plugin, (groups, swaps) in (
            ('Oblivion.esm', (OBLIVION_GROUPS, OBLIVION_SWAPS)),
            ('ElsweyrAnequina.esp', (ELSWEYR_GROUPS, ELSWEYR_SWAPS))):
        total = sum(g.count for g in groups.values())
        tally = coverage(plugin)
        print('\n=== %s -- %d CREA in %d groups ===' % (plugin, total, len(groups)))
        print('    exact %d recs | near %d | keep %d | remove %d | unmapped %d'
              % (tally[EXACT], tally[NEAR], tally[NONE], tally[REMOVE],
                 tally['unmapped']))
        for key in sorted(groups, key=lambda k: -groups[k].count):
            grp = groups[key]
            swap = swaps.get(key)
            if swap is None:
                target, tier = '(unmapped)', '?'
            elif swap.tier == REMOVE:
                target, tier = 'DELETE', swap.tier
            elif swap.target is None:
                target, tier = 'keep converted', swap.tier
            else:
                target, tier = swap.target, swap.tier
            mount = ' MOUNT:%d' % grp.mounts if grp.mounts else ''
            print('  %-26s %4d%-9s %-6s %-34s %s'
                  % (key, grp.count, mount, tier, target,
                     grp.sample[0] if grp.sample else ''))

    print('\n=== mounts ===')
    print('  Oblivion.esm         %d of %d horse-folder records are DATA.Type=4'
          % (sum(1 for r in OBLIVION_MOUNT_RECORDS if r[5]),
             len(OBLIVION_MOUNT_RECORDS)))
    print('  ElsweyrAnequina.esp  %d of %d mount-folder records are DATA.Type=4'
          % (sum(1 for r in ELSWEYR_MOUNT_RECORDS if r[5]),
             len(ELSWEYR_MOUNT_RECORDS)))
    for key, (target, tier, note) in sorted(MOUNT_SWAPS.items()):
        print('  %-36s %-6s %s' % (key, tier, target or 'keep converted'))

    print()
    print('=== removals ===')
    for plugin, rows in sorted(REMOVALS.items()):
        for group, info in sorted(rows.items()):
            print('  %s / %s' % (plugin, group))
            print('     %d base records, %d placed refs, %d entries in %d '
                  'leveled lists' % (info['base_records'], info['placed_refs'],
                                     info['leveled_entries'],
                                     info['leveled_lists']))
            print('     quest/dialogue refs: %d   script refs: %d'
                  % (info['quest_refs'], info['script_refs']))

    print()
    print('=== renames a swap would leave behind ===')
    for fid, (old, new) in sorted(RENAME_SUGGESTIONS.items()):
        print('  0x%08X  %-14s -> %s' % (fid, old, new))


if __name__ == '__main__':
    report()
