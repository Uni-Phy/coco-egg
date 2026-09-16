#!/usr/bin/env python3
"""coco-egg enclosure v4 -> STEP (true B-rep), via CadQuery / OpenCascade.

OpenSCAD only writes meshes. This is a port of egg.scad's v4 geometry to
CadQuery so the parts exist as real solids with analytic surfaces, holes and
faces — what you want to open in Fusion/FreeCAD/SolidWorks or hand to a
moulder. Parameters are copied from egg.scad and must be kept in sync; the
SCAD file stays the print source of truth, this is the CAD exchange copy.

    make step        # -> out/egg_v4_{bowl,platform,dome}.step + egg_v4_assembly.step
"""
from __future__ import annotations

import math
import pathlib
import sys

import cadquery as cq

# ---------- parameters (mirror egg.scad) ----------
D, H, E = 150.0, 200.0, 0.15
WALL, CLR, LIP_H = 2.4, 0.2, 5.0
Z_FOOT, FLOOR, Z_SEAM = 20.0, 2.4, 100.0
Z_LEDGE, LEDGE_T, LEDGE_W = 58.0, 4.0, 8.0

PI_HOLES = [(-29, -24.5), (29, -24.5), (-29, 24.5), (29, 24.5)]
PI_STUB_H, PI_STUB_D = 6.0, 6.0
PI_Z = Z_FOOT + FLOOR + PI_STUB_H
PI_USBC_X = -31.3

SPK_HOLE_D, SPK_CUT_D, PLAT_T = 63.0, 50.0, 3.0
BUTTON_D, PILOT_M25 = 12.4, 2.2

OUT = pathlib.Path(__file__).parent / "out"
BIG = 2 * D


# ---------- egg profile ----------
def egg_r(z: float) -> float:
    u = 2 * z / H - 1
    return (D / 2) * math.sqrt(max(0.0, 1 - u * u)) * (1 - E * u)


def profile(off: float, n: int = 160) -> list[tuple[float, float]]:
    """(r, z) points of the egg outline offset by `off` along its normal.

    Parametrised by angle so the poles are regular points: r = R sinθ(1+E cosθ),
    z = H/2 (1 - cosθ). Endpoints land exactly on the axis.
    """
    R = D / 2
    pts = []
    for i in range(n + 1):
        t = math.pi * i / n
        s, c = math.sin(t), math.cos(t)
        r = R * s * (1 + E * c)
        z = H / 2 * (1 - c)
        dr = R * (c * (1 + E * c) - E * s * s)
        dz = H / 2 * s
        L = math.hypot(dr, dz)
        nx, nz = dz / L, -dr / L            # outward normal
        pts.append((r + off * nx, z + off * nz))
    pts[0] = (0.0, pts[0][1])               # pin the poles to the axis
    pts[-1] = (0.0, pts[-1][1])
    return pts


def egg_solid(off: float = 0.0) -> cq.Workplane:
    pts = profile(off)
    wp = cq.Workplane("XZ").moveTo(*pts[0]).spline(pts[1:], includeCurrent=True).close()
    return wp.revolve(360, (0, 0, 0), (0, 1, 0))


def slab(z0: float, z1: float) -> cq.Workplane:
    return cq.Workplane("XY").box(BIG, BIG, z1 - z0, centered=(True, True, False)).translate((0, 0, z0))


def cyl(d: float, h: float, x=0.0, y=0.0, z=0.0) -> cq.Workplane:
    return cq.Workplane("XY").circle(d / 2).extrude(h).translate((x, y, z))


def shell() -> cq.Workplane:
    return egg_solid(0).cut(egg_solid(-WALL))


def lip(zs: float) -> cq.Workplane:
    return egg_solid(-(WALL / 2 + CLR)).cut(egg_solid(-WALL)).intersect(slab(zs, zs + LIP_H))


def recess(zs: float) -> cq.Workplane:
    return egg_solid(-WALL / 2).intersect(slab(zs - 0.01, zs + LIP_H))


# ---------- parts ----------
def bowl() -> cq.Workplane:
    z_floor = Z_FOOT + FLOOR
    body = shell().intersect(slab(Z_FOOT, Z_SEAM))
    body = body.union(egg_solid(0).intersect(slab(Z_FOOT, z_floor)))
    body = body.union(lip(Z_SEAM))
    ledge_ring = egg_solid(-1).cut(
        cyl(2 * (egg_r(Z_LEDGE) - WALL - LEDGE_W), 3 * H, z=-H))
    body = body.union(ledge_ring.intersect(slab(Z_LEDGE - LEDGE_T, Z_LEDGE)))
    for x, y in PI_HOLES:
        body = body.union(cyl(PI_STUB_D, PI_STUB_H, x, y, z_floor - 0.01))
    for x, y in PI_HOLES:
        body = body.cut(cyl(PILOT_M25, PI_STUB_H + 1, x, y, z_floor + 1))
    # USB-C power slot at the back
    body = body.cut(cq.Workplane("XY").box(14, D, 9, centered=False)
                    .translate((PI_USBC_X - 7, 30, PI_Z + 1.6 - 1)))
    # vents beside the Pi's ports
    for k in range(-3, 4):
        body = body.cut(cq.Workplane("XY").box(2, D, 14, centered=False)
                        .translate((k * 8 + 14, 30, PI_Z + 4)))
    return body


def platform() -> cq.Workplane:
    r = egg_r(Z_LEDGE) - WALL - CLR
    p = cq.Workplane("XY").circle(r).extrude(PLAT_T)
    p = p.cut(cyl(SPK_CUT_D, PLAT_T + 2, z=-1))
    for a in (45, 135, 225, 315):
        p = p.cut(cyl(PILOT_M25, PLAT_T + 2,
                      SPK_HOLE_D / 2 * math.cos(math.radians(a)),
                      SPK_HOLE_D / 2 * math.sin(math.radians(a)), -1))
    p = p.cut(cq.Workplane("XY").box(16, 20, PLAT_T + 2, centered=False)
              .translate((-8, r - 12, -1)))
    return p


def dome() -> cq.Workplane:
    body = shell().intersect(slab(Z_SEAM, H))
    body = body.cut(recess(Z_SEAM))
    body = body.cut(cyl(BUTTON_D, 40, z=H - 30))
    body = body.cut(slab(H - 1.6, H + 5))
    # 24 slits just above the seam
    slit = (cq.Workplane("XY").box(WALL + 12, 2, 16, centered=False)
            .translate((D / 2 - WALL - 6, -1, Z_SEAM + LIP_H + 3)))
    slits = slit
    for a in range(15, 360, 15):
        slits = slits.union(slit.rotate((0, 0, 0), (0, 0, 1), a))
    return body.cut(slits)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    parts = {"bowl": bowl, "platform": platform, "dome": dome}
    only = sys.argv[1:] or list(parts)
    made = {}
    for name in only:
        print(f"building {name}...", flush=True)
        made[name] = parts[name]()
        path = OUT / f"egg_v4_{name}.step"
        cq.exporters.export(made[name], str(path))
        bb = made[name].val().BoundingBox()
        print(f"  wrote {path.name}: z {bb.zmin:.1f}..{bb.zmax:.1f}, "
              f"volume {made[name].val().Volume() / 1000:.1f} cm³")
    if set(made) == set(parts):
        asm = cq.Assembly(name="coco-egg-v4")
        asm.add(made["bowl"], name="bowl", color=cq.Color(0.86, 0.86, 0.86))
        asm.add(made["platform"], name="platform", color=cq.Color(0.75, 0.75, 0.75),
                loc=cq.Location(cq.Vector(0, 0, Z_LEDGE)))
        asm.add(made["dome"], name="dome", color=cq.Color(0.86, 0.86, 0.86))
        asm.save(str(OUT / "egg_v4_assembly.step"))
        print("  wrote egg_v4_assembly.step")


if __name__ == "__main__":
    main()
