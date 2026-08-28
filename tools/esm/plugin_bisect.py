"""Carve records out of a built plugin so a load failure can be bisected.

The engine builds its FormID table while PARSING a plugin, so a malformed
record hangs the game on the main menu with no crash and no log. xEdit reports
such a file as clean, and resaving in xEdit rewrites the group tree -- which
changes two variables at once and makes a manual bisect ambiguous.

This removes records IN PLACE and fixes up every enclosing GRUP size, so the
only thing that changes is the set of records present.

  --keep-blocks   keep only these exterior blocks (repeatable, "Y,X")
  --drop-blocks   drop these exterior blocks (repeatable, "Y,X")
  --drop-subs     drop these sub-blocks (repeatable, "Y,X")
  --drop-half     drop the first or second half of a block's sub-blocks
  --only-sig      drop every record of this signature inside the target blocks
  --drop-formid   drop ONE record by FormID, wherever it sits, together with
                  the children GRUP that belongs to it (a WRLD's World
                  Children, a CELL's Cell Children, a DIAL's Topic Children) --
                  those are labelled with the owner's FormID and are invalid
                  without it

Usage:
  python tools/esm/plugin_bisect.py Plugin.esp --drop-blocks -1,-2 -o out.esp
  python tools/esm/plugin_bisect.py Plugin.esp --drop-subs -4,-8 -4,-7 -o out.esp
  python tools/esm/plugin_bisect.py Plugin.esp --drop-blocks -1,-2 \
      --output-dir output -o "C:/path/to/Data/Plugin.esp"
"""
import argparse
import os
import struct
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HEADER = 24


def _pair(text):
    y, x = text.split(',')
    return (int(y), int(x))


def carve(data, keep_blocks, drop_blocks, drop_subs, drop_sigs,
          drop_formids, verbose):
    """Rebuild `data`, omitting whatever the filters reject."""
    hdr = struct.unpack_from('<I', data, 4)[0]
    head = data[:_HEADER + hdr]
    dropped = {'blocks': 0, 'subs': 0, 'records': 0}
    # FormIDs whose OWN children group must go with them. Filled as each such
    # record is dropped, because the group follows the record it belongs to.
    orphaned = set()

    def rebuild(off, end, blk=None, sub=None):
        """Return the bytes for [off, end) after filtering."""
        out = []
        while off < end:
            sig = data[off:off + 4]
            size = struct.unpack_from('<I', data, off + 4)[0]
            if sig == b'GRUP':
                gtype = struct.unpack_from('<i', data, off + 12)[0]
                label = data[off + 8:off + 12]
                nblk, nsub = blk, sub
                if gtype == 4:
                    nblk = struct.unpack('<hh', label)
                    nsub = None
                    if drop_blocks and nblk in drop_blocks:
                        dropped['blocks'] += 1
                        if verbose:
                            print(f"  drop block {nblk} ({size:,} bytes)")
                        off += size
                        continue
                    if keep_blocks and nblk not in keep_blocks:
                        dropped['blocks'] += 1
                        off += size
                        continue
                elif gtype == 5:
                    nsub = struct.unpack('<hh', label)
                    if drop_subs and nsub in drop_subs:
                        dropped['subs'] += 1
                        if verbose:
                            print(f"  drop sub-block {nsub} ({size:,} bytes)")
                        off += size
                        continue
                if (gtype in (1, 6, 7)
                        and struct.unpack('<I', label)[0] in orphaned):
                    # The record that owns this group has just been dropped.
                    if verbose:
                        print(f"  drop children GRUP type {gtype} of "
                              f"{struct.unpack('<I', label)[0]:08X} "
                              f"({size:,} bytes)")
                    off += size
                    continue
                inner = rebuild(off + _HEADER, off + size, nblk, nsub)
                # An EMPTY children group is legal and the CK writes them, so
                # keep one that was already empty; only prune a group this
                # carve emptied. Otherwise a no-op run silently rewrites the
                # group tree -- two variables at once, which is exactly what
                # this tool exists to avoid.
                if inner or size == _HEADER:
                    # A GRUP's size COUNTS its own 24-byte header.
                    hdr_bytes = bytearray(data[off:off + _HEADER])
                    struct.pack_into('<I', hdr_bytes, 4, len(inner) + _HEADER)
                    out.append(bytes(hdr_bytes))
                    out.append(inner)
                off += size
                continue

            # A plain record.
            fid = struct.unpack_from('<I', data, off + 12)[0]
            if fid in drop_formids:
                dropped['records'] += 1
                orphaned.add(fid)
                if verbose:
                    print(f"  drop {sig.decode('latin1')} {fid:08X} "
                          f"({size:,} bytes)")
                off += _HEADER + size
                continue
            in_target = (not (keep_blocks or drop_blocks or drop_subs)
                         or blk is not None)
            if drop_sigs and sig in drop_sigs and in_target:
                dropped['records'] += 1
                off += _HEADER + size
                continue
            out.append(data[off:off + _HEADER + size])
            off += _HEADER + size
        return b''.join(out)

    body = rebuild(_HEADER + hdr, len(data))
    return _restate_hedr(head, body), dropped


def _restate_hedr(head, body):
    """Rewrite the TES4 header's record count for the carved body.

    HEDR's second field counts RECORDS AND GROUPS, not records alone -- the
    same number `verify_npc_patch` checks. Leaving the original there ships a
    header that disagrees with the file.
    """
    n = 0
    off = 0
    while off + _HEADER <= len(body):
        size = struct.unpack_from('<I', body, off + 4)[0]
        n += 1
        off += _HEADER + (0 if body[off:off + 4] == b'GRUP' else size)
    out = bytearray(head)
    j = _HEADER
    while j + 6 <= len(out):
        stype = bytes(out[j:j + 4])
        slen = struct.unpack_from('<H', out, j + 4)[0]
        if stype == b'HEDR':
            struct.pack_into('<i', out, j + 6 + 4, n)
            break
        j += 6 + slen
    return bytes(out) + body


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('plugin')
    ap.add_argument('--output-dir', default=os.path.join(SCRIPT_DIR, 'output'))
    ap.add_argument('-o', '--out', required=True, help='file to write')
    ap.add_argument('--keep-blocks', nargs='*', default=[], metavar='Y,X')
    ap.add_argument('--drop-blocks', nargs='*', default=[], metavar='Y,X')
    ap.add_argument('--drop-subs', nargs='*', default=[], metavar='Y,X')
    ap.add_argument('--drop-sig', nargs='*', default=[],
                    help='record signatures to drop inside the target blocks')
    ap.add_argument('--drop-formid', nargs='*', default=[], metavar='HEX',
                    help='drop these records by FormID, with their children '
                         'GRUP (WRLD/CELL/DIAL)')
    ap.add_argument('-q', '--quiet', action='store_true')
    args = ap.parse_args()

    path = os.path.join(args.output_dir, args.plugin, args.plugin)
    if not os.path.isfile(path):
        path = args.plugin
    if not os.path.isfile(path):
        print(f"not found: {args.plugin}")
        return 1
    with open(path, 'rb') as f:
        data = f.read()

    out, dropped = carve(
        data,
        {_pair(t) for t in args.keep_blocks},
        {_pair(t) for t in args.drop_blocks},
        {_pair(t) for t in args.drop_subs},
        {s.encode('ascii')[:4] for s in args.drop_sig},
        {int(t, 16) for t in args.drop_formid},
        not args.quiet)

    with open(args.out, 'wb') as f:
        f.write(out)
    print(f"{path}\n  {len(data):,} -> {len(out):,} bytes  "
          f"(dropped {dropped['blocks']} blocks, {dropped['subs']} sub-blocks, "
          f"{dropped['records']} records)\n  wrote {args.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
