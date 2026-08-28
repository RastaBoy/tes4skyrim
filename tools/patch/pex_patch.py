#!/usr/bin/env python3
"""Retarget a constant inside a COMPILED Papyrus script, without recompiling.

Third-party mods routinely hardcode another plugin's file name and a FormID to
decide whether that mod is installed -- `Game.GetFormFromFile(0x2F4DB2,
"RigmorCyrodiil.esm")`. Pointing such a check at one of OUR converted plugins
means changing two literals and nothing else.

    python tools/patch/pex_patch.py in.pex --out out.pex \
        --set-string "RigmorCyrodiil.esm=Oblivion.esm" \
        --set-int 3100082=60 \
        --expect-string MakeWorldspaceArrays

WHY NOT JUST RECOMPILE
----------------------
Because the .psc usually does not compile on its own machine. The case this was
written for -- `aaaShipUtilityScript` from Sailable Ship -- declares
`aaaSMUtilityScript Property SMUtil`, a type that lives in an OPTIONAL addon
(`Sailable Ship Missions.esp`) whose sources the mod does not ship. Recompiling
would force a hand-written stub of that addon's API, and any signature we got
wrong would silently break the addon for everyone who has it. Editing two
literals leaves every other byte -- all addon interop included -- untouched.

WHAT IS ACTUALLY PARSED
-----------------------
The header and the string table, structurally: Skyrim's PEX is BIG-ENDIAN, and
a string is a u16 length plus that many bytes. `--set-string` rewrites a table
ENTRY, so every reference to it (they are all by index) follows automatically
and the rest of the file is copied verbatim.

Integer literals are not in the table -- they are inline instruction operands,
a type tag `03` followed by a big-endian int32 -- so `--set-int` rewrites the
byte pattern directly. That is only safe when the pattern occurs ONCE, so this
refuses to guess: a value appearing zero or several times is an error, and the
caller is expected to have checked the .psc that the literal is unique there
too. Both edits are re-parsed and re-verified before anything is written.
"""

import argparse
import os
import struct
import sys

MAGIC = 0xFA57C0DE
INT_TAG = 3


class Pex:
    """A compiled Papyrus script, parsed as far as the string table."""

    def __init__(self, data):
        self.data = bytes(data)
        if len(self.data) < 8 or struct.unpack_from('>I', self.data, 0)[0] != MAGIC:
            raise SystemExit('not a Papyrus .pex file (bad magic)')
        self.major, self.minor, self.game = struct.unpack_from('>BBH', self.data, 4)
        pos = 16                                    # + u64 compilation time
        self.source, pos = self._wstring(pos)
        self.user, pos = self._wstring(pos)
        self.machine, pos = self._wstring(pos)
        self.table_start = pos
        count = struct.unpack_from('>H', self.data, pos)[0]
        pos += 2
        self.strings = []
        for _ in range(count):
            text, pos = self._wstring(pos)
            self.strings.append(text)
        self.table_end = pos

    def _wstring(self, pos):
        length = struct.unpack_from('>H', self.data, pos)[0]
        start = pos + 2
        return self.data[start:start + length].decode('cp1252'), start + length

    @property
    def code(self):
        """Everything after the string table: debug info, flags, objects."""
        return self.data[self.table_end:]

    def rebuild(self, strings=None, code=None):
        strings = self.strings if strings is None else list(strings)
        if len(strings) != len(self.strings):
            raise SystemExit('the string table may be rewritten, not resized: '
                             'every reference into it is an index')
        table = bytearray(struct.pack('>H', len(strings)))
        for text in strings:
            raw = text.encode('cp1252')
            if len(raw) > 0xFFFF:
                raise SystemExit(f'string "{text[:40]}..." is too long')
            table += struct.pack('>H', len(raw)) + raw
        return (self.data[:self.table_start] + bytes(table) +
                (self.code if code is None else bytes(code)))


def set_string(pex, strings, old, new):
    """Rewrite the one table entry equal to `old`."""
    hits = [i for i, s in enumerate(strings) if s == old]
    if len(hits) != 1:
        raise SystemExit(f'"{old}" appears {len(hits)} times in the string '
                         'table; expected exactly one')
    strings[hits[0]] = new
    return hits[0]


def set_int(code, old, new):
    """Rewrite the one inline int32 literal equal to `old`."""
    want = bytes([INT_TAG]) + struct.pack('>i', old)
    hits = code.count(want)
    if hits != 1:
        raise SystemExit(f'the literal {old} appears {hits} times as an int '
                         'operand; expected exactly one. Refusing to guess '
                         'which one to change')
    at = code.find(want)
    return code[:at] + bytes([INT_TAG]) + struct.pack('>i', new) + code[at + 5:], at


def parse_pair(text, cast=str):
    key, sep, value = text.partition('=')
    if not sep:
        raise SystemExit(f'"{text}" must be OLD=NEW')
    return cast(key), cast(value)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pex', help='the compiled script to read')
    ap.add_argument('--out', help='where to write it (default: report only)')
    ap.add_argument('--set-string', action='append', default=[],
                    metavar='OLD=NEW', help='rewrite one string-table entry')
    ap.add_argument('--set-int', action='append', default=[],
                    metavar='OLD=NEW', help='rewrite one inline int32 literal')
    ap.add_argument('--expect-string', action='append', default=[],
                    metavar='TEXT',
                    help='fail unless TEXT is in the string table -- the cheap '
                         'proof this is the script you meant')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    pex = Pex(open(args.pex, 'rb').read())
    print(f'{os.path.basename(args.pex)}: v{pex.major}.{pex.minor} '
          f'game {pex.game}, source "{pex.source}", '
          f'{len(pex.strings)} strings, {len(pex.data):,} bytes')

    for text in args.expect_string:
        if text not in pex.strings:
            raise SystemExit(f'"{text}" is not in this script\'s string table; '
                             'this is not the script the caller expected')
        print(f'  expect: "{text}" present')

    strings = list(pex.strings)
    for pair in args.set_string:
        old, new = parse_pair(pair)
        index = set_string(pex, strings, old, new)
        print(f'  string[{index}]: "{old}" -> "{new}"')

    code = pex.code
    for pair in args.set_int:
        old, new = parse_pair(pair, int)
        code, at = set_int(code, old, new)
        print(f'  int literal at code+0x{at:X}: {old} -> {new}')

    if not args.set_string and not args.set_int:
        print('  nothing to change')
        return 0

    out = pex.rebuild(strings, code)

    # Re-parse what we are about to write: the table has to still walk, and the
    # new values have to be there instead of the old ones.
    check = Pex(out)
    for pair in args.set_string:
        old, new = parse_pair(pair)
        if new not in check.strings or old in check.strings:
            raise SystemExit(f'verification failed for "{old}" -> "{new}"')
    for pair in args.set_int:
        old, new = parse_pair(pair, int)
        want = bytes([INT_TAG]) + struct.pack('>i', old)
        if check.code.count(want):
            raise SystemExit(f'verification failed: {old} is still there')
    delta = len(out) - len(pex.data)
    print(f'  verified: {len(out):,} bytes ({delta:+d})')

    if args.dry_run or not args.out:
        print('  DRY RUN -- nothing written' if args.dry_run
              else '  no --out given -- nothing written')
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'wb') as fh:
        fh.write(out)
    print(f'  wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
