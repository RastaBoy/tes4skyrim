#!/usr/bin/env python
"""Diff the WORLD POSE of every mesh node between a source NIF and its conversion.

Structural dumps say what blocks a converted mesh has; they do not say where
the geometry ends up once a clip plays.  This evaluates the scene graph the
way the engine does -- at rest, and at the end frame of every NiControllerSequence
-- and reports any node whose world transform moved.  It is how an animated-mesh
regression (a door swinging through its own hinge, a gate that opens displaced)
is measured rather than guessed at.

    python tools/nif/anim_pose_diff.py <source.nif> <converted.nif> [--seq NAME]
                                       [--time T] [--all-nodes] [--ignore-accum]
    python tools/nif/anim_pose_diff.py -f Oblivion.esm architecture/bravil   # sweep

Sweep mode (`-f PLUGIN` plus path fragments, or `--list FILE`) pairs every
matching mesh under the plugin's extracted tree with the same path under its
output tree and prints only the mismatches -- the regression check to run after
touching anything in the animation or transform passes.

`--ignore-accum` drops each sequence's ACCUM-ROOT controlled block before
evaluating the converted mesh.  Gamebryo's accum root is the clip's root-motion
channel, and an engine may either write it to the node or consume it for
accumulation; a conversion that is correct only under one reading is not
correct.  Run both ways -- a mesh that matches with and without the flag is
right whichever the engine does.

Row-vector convention throughout (world = L_node * L_parent * ... * L_root),
matching PyFFI's m_ij naming.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from asset_convert import pyffi_monkey_patch          # noqa: F401,E402
from pyffi.formats.nif import NifFormat               # noqa: E402
from output_layout import asset_root, plugin_out_root  # noqa: E402

NO_VALUE = -3.4028234663852886e+38   # Gamebryo's "channel has no value"


# --------------------------------------------------------------------------
# scene graph
# --------------------------------------------------------------------------

def _cb_name(seq, cb, attr='node_name'):
    """Controlled-block node name, from the bytes field or the string palette."""
    val = getattr(cb, attr, b'')
    if isinstance(val, bytes) and val:
        return val
    sp = getattr(seq, 'string_palette', None)
    if sp is None:
        return b''
    try:
        buf = bytes(sp.palette.palette)
        off = getattr(cb, attr + '_offset')
        if off in (0xffffffff, -1):
            return b''
        return buf[off:buf.index(b'\x00', off)]
    except Exception:
        return b''


def _mmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def _vmul(v, b):
    return [sum(v[k] * b[k][j] for k in range(3)) for j in range(3)]


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, s], [0, -s, c]]


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, -s], [0, 1, 0], [s, 0, c]]


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, s, 0], [-s, c, 0], [0, 0, 1]]


def _quat(w, x, y, z):
    return [[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
            [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
            [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]]


def _node_local(n):
    m = n.rotation
    return ([[m.m_11, m.m_12, m.m_13],
             [m.m_21, m.m_22, m.m_23],
             [m.m_31, m.m_32, m.m_33]],
            [n.translation.x, n.translation.y, n.translation.z],
            float(n.scale))


def _compose(child, parent):
    """child-first: the single local equivalent to applying child then parent."""
    Rc, Tc, Sc = child
    Rp, Tp, Sp = parent
    t = _vmul(Tc, Rp)
    return (_mmul(Rc, Rp),
            [t[i] * Sp + Tp[i] for i in range(3)],
            Sc * Sp)


def _sample(keys, t, lerp):
    if not keys:
        return None
    if t <= keys[0].time:
        return keys[0].value
    if t >= keys[-1].time:
        return keys[-1].value
    for i in range(len(keys) - 1):
        if keys[i].time <= t <= keys[i + 1].time:
            span = keys[i + 1].time - keys[i].time
            f = (t - keys[i].time) / span if span > 1e-9 else 0.0
            return lerp(keys[i].value, keys[i + 1].value, f)
    return keys[-1].value


def _interp_local(ip, t, fallback):
    """The local transform a NiTransformInterpolator yields at time *t*."""
    R, T, S = fallback
    d = getattr(ip, 'data', None)

    if d is not None and d.translations.num_keys:
        def _lerp(a, b, f):
            return (a.x + f * (b.x - a.x), a.y + f * (b.y - a.y),
                    a.z + f * (b.z - a.z))
        v = _sample(list(d.translations.keys), t, _lerp)
        T = list(v) if isinstance(v, tuple) else [v.x, v.y, v.z]
    elif ip.translation.x > NO_VALUE:
        T = [ip.translation.x, ip.translation.y, ip.translation.z]

    got = False
    if d is not None:
        if d.rotation_type == 4 and any(c.num_keys for c in d.xyz_rotations):
            ang = []
            for curve in d.xyz_rotations:
                v = _sample(list(curve.keys), t, lambda a, b, f: a + f * (b - a))
                ang.append(v or 0.0)
            R = _mmul(_mmul(_rx(ang[0]), _ry(ang[1])), _rz(ang[2]))
            got = True
        elif d.num_rotation_keys:
            keys = list(d.quaternion_keys)
            q = keys[-1].value if t >= keys[-1].time else keys[0].value
            for i in range(len(keys) - 1):
                if keys[i].time <= t <= keys[i + 1].time:
                    q = (keys[i].value if (t - keys[i].time)
                         < (keys[i + 1].time - t) else keys[i + 1].value)
                    break
            R = _quat(q.w, q.x, q.y, q.z)
            got = True
    if not got and ip.rotation.w > NO_VALUE:
        R = _quat(ip.rotation.w, ip.rotation.x, ip.rotation.y, ip.rotation.z)

    if d is not None and d.scales.num_keys:
        S = _sample(list(d.scales.keys), t, lambda a, b, f: a + f * (b - a))
    elif ip.scale > NO_VALUE:
        S = ip.scale
    return (R, T, S)


def _scene(path):
    data = NifFormat.Data()
    with open(path, 'rb') as fh:
        data.read(fh)
    root = data.roots[0]
    parent, order = {}, [root]

    def walk(n):
        for c in (getattr(n, 'children', None) or ()):
            if c is None or not hasattr(c, 'translation'):
                continue
            parent[id(c)] = n
            order.append(c)
            walk(c)
    walk(root)
    ctrl = getattr(root, 'controller', None)
    while ctrl is not None and not isinstance(ctrl, NifFormat.NiControllerManager):
        ctrl = getattr(ctrl, 'next_controller', None)
    return root, parent, order, ctrl


def sequence_names(path):
    _, _, _, mgr = _scene(path)
    if mgr is None:
        return []
    return [bytes(s.name or b'') for s in mgr.controller_sequences]


def world_poses(path, seq_name=None, t=0.0, ignore_accum=False, all_nodes=False):
    """{node name: [world transform, ...]} at time *t* of *seq_name*."""
    root, parent, order, mgr = _scene(path)
    anim = {}
    if seq_name and mgr is not None:
        for seq in mgr.controller_sequences:
            if bytes(seq.name or b'') != seq_name:
                continue
            accum = bytes(getattr(seq, 'target_name', b'') or b'')
            for cb in seq.controlled_blocks:
                nm = _cb_name(seq, cb)
                if not isinstance(cb.interpolator, NifFormat.NiTransformInterpolator):
                    continue
                if ignore_accum and nm == accum:
                    continue
                anim[nm] = cb.interpolator
    out = {}
    for node in order:
        if not (all_nodes or isinstance(node, (NifFormat.NiTriShape,
                                               NifFormat.NiTriStrips))):
            continue
        acc, cur = None, node
        while cur is not None:
            loc = _node_local(cur)
            nm = bytes(getattr(cur, 'name', b'') or b'')
            if nm in anim:
                loc = _interp_local(anim[nm], t, loc)
            acc = loc if acc is None else _compose(acc, loc)
            cur = parent.get(id(cur))
        out.setdefault(bytes(getattr(node, 'name', b'') or b''), []).append(acc)
    return out


def _fmt(p):
    R, T, S = p
    return ('T(%.2f, %.2f, %.2f) Rz %.2f row0(%.3f, %.3f, %.3f) S %.3f'
            % (T[0], T[1], T[2], math.degrees(math.atan2(R[0][1], R[0][0])),
               R[0][0], R[0][1], R[0][2], S))


def diff(src, out, seq=None, t=0.0, ignore_accum=False, all_nodes=False,
         tol_t=0.5, tol_r=0.02):
    """[(node name, source pose, converted pose)] for every node that moved."""
    a = world_poses(src, seq, t, all_nodes=all_nodes)
    b = world_poses(out, seq, t, ignore_accum=ignore_accum, all_nodes=all_nodes)
    bad = []
    for name in sorted(set(a) | set(b)):
        pa, pb = a.get(name), b.get(name)
        if not pa or not pb:
            continue
        for i in range(min(len(pa), len(pb))):
            Ra, Ta, _ = pa[i]
            Rb, Tb, _ = pb[i]
            if (max(abs(Ta[j] - Tb[j]) for j in range(3)) > tol_t
                    or max(abs(Ra[r][c] - Rb[r][c])
                           for r in range(3) for c in range(3)) > tol_r):
                bad.append((name.decode('latin-1'), pa[i], pb[i]))
    return bad


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _report(src, out, args):
    """Compare one pair over every pose; return True if anything differs."""
    if args.seq is not None:
        poses = [(args.seq.encode('latin-1'), args.time, args.seq)]
    else:
        poses = [(None, 0.0, 'REST')]
        for nm in sequence_names(src):
            poses.append((nm, args.time, nm.decode('latin-1')))
    modes = [(False, 'A')] if not args.ignore_accum else [(True, 'B')]
    if args.both:
        modes = [(False, 'A'), (True, 'B')]
    dirty = False
    for seq, t, label in poses:
        for ig, tag in modes:
            d = diff(src, out, seq, t, ignore_accum=ig, all_nodes=args.all_nodes)
            if not d:
                if args.verbose:
                    print(f'  [{tag}] {label}: identical')
                continue
            dirty = True
            print(f'  [{tag}] {label}: {len(d)} node(s) moved')
            for name, pa, pb in d[:args.max_report]:
                print(f'      {name}')
                print(f'        src {_fmt(pa)}')
                print(f'        out {_fmt(pb)}')
    return dirty


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='*',
                    help='SOURCE.nif CONVERTED.nif, or path fragments with -f')
    ap.add_argument('-f', '--plugin', metavar='PLUGIN',
                    help='Sweep mode: pair the plugin\'s export tree with its '
                         'output tree')
    ap.add_argument('--list', metavar='FILE',
                    help='Sweep mode: path fragments, one per line')
    ap.add_argument('--extract-dir', default='export')
    ap.add_argument('--output-dir', default='output')
    ap.add_argument('--seq', help='Only this sequence (default: rest + all)')
    ap.add_argument('--time', type=float, default=99.0,
                    help='Sequence time to sample; the default clamps to the '
                         'end frame')
    ap.add_argument('--ignore-accum', action='store_true',
                    help='Drop the accum-root entry from the CONVERTED mesh')
    ap.add_argument('--both', action='store_true',
                    help='Report under both readings of the accum entry')
    ap.add_argument('--all-nodes', action='store_true',
                    help='Compare every node, not only geometry (noisy: the '
                         'rotation-wrap pass renames nothing but moves the '
                         'root transform onto an identically named wrapper)')
    ap.add_argument('--max-report', type=int, default=3)
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args(argv)

    if not a.plugin:
        if len(a.paths) != 2:
            ap.error('give SOURCE.nif CONVERTED.nif, or -f PLUGIN with fragments')
        return 1 if _report(a.paths[0], a.paths[1], a) else 0

    plugin = Path(a.plugin).name
    src_root = Path(asset_root(a.extract_dir, plugin)) / 'meshes'
    out_root = (Path(plugin_out_root(a.output_dir, plugin, str(a.extract_dir)))
                / 'meshes' / 'tes4')
    frags = [p.replace('\\', '/').lower().lstrip('/') for p in a.paths]
    if a.list:
        for line in Path(a.list).read_text(encoding='utf-8').splitlines():
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            norm = line.replace('\\', '/').lower()
            frags.append(norm.split('/meshes/', 1)[1] if '/meshes/' in norm
                         else norm)
    if not frags:
        frags = ['']

    checked = dirty = 0
    for nif in sorted(src_root.rglob('*.nif')):
        rel = nif.relative_to(src_root)
        norm = '/'.join(p.lower() for p in rel.parts)
        if not any(f in norm for f in frags):
            continue
        conv = out_root / rel
        if not conv.is_file():
            continue
        checked += 1
        try:
            hit = _report(str(nif), str(conv), a)
        except Exception as exc:
            print(f'{rel}: ERROR {exc}')
            dirty += 1
            continue
        if hit:
            print(f'^^ {rel}')
            dirty += 1
    print(f'\n{checked} pair(s) compared, {dirty} with a moved node')
    return 1 if dirty else 0


if __name__ == '__main__':
    raise SystemExit(main())
