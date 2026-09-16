// coco-egg zero — enclosure v4 (simplified, parametric OpenSCAD)
//
// Three printed parts, no supports:
//   bowl     — lower egg. Pi 5 on four SHORT stubs (6 mm) straight on the
//              floor; USB-C power slot + vents at the back; an internal ledge
//              above the Pi where the platform rests.
//   platform — flat disc that drops onto the ledge. Carries the 57 mm speaker
//              cone-up (4 pilot holes on the frame circle) with a cable notch.
//              Print it later / iterate it freely — nothing else depends on it.
//   dome     — upper egg. Push-to-talk button at the apex, a band of slits low
//              on the dome lets the speaker out and the mic in.
//
// v3 had the Pi up on 34 mm pillars above a down-firing speaker; the thin
// pillars crossing the Pi footprint were fragile and hard to trust. v4 puts
// the Pi on the floor and everything else on one removable shelf.
//
// Split is at the widest point: friction-fit half-wall lip on the bowl into a
// recess in the dome, CLR radial clearance.
//
// Render:  make -C hardware stl      (or: openscad -o bowl.stl -D 'part="bowl"' egg.scad)
// Preview: part="assembly", add cut=true for a cross-section.

part = "assembly";   // bowl | platform | dome | assembly
cut  = false;

/* ---------- egg ---------- */
D    = 150;    // max diameter
H    = 200;    // full (uncut) egg height
E    = 0.15;   // egg-ness: 0 = ellipsoid, larger = pointier top
WALL = 2.4;
CLR  = 0.2;    // radial clearance at the seam and around the platform
LIP_H = 5;

Z_FOOT  = 20;      // flat cut at the bottom -> Ø~100 foot, egg stands on it
FLOOR   = 2.4;
Z_SEAM  = 100;     // bowl/dome seam, at the widest point
Z_LEDGE = 58;      // platform ledge (top face) — clears the Pi's USB ports
LEDGE_T = 4;
LEDGE_W = 8;       // how far the ledge reaches in from the wall

/* ---------- components ---------- */
// Raspberry Pi 5: 85 x 56, holes 58 x 49. USB-C power on the +y (back) edge.
PI_HOLES   = [[-29, -24.5], [29, -24.5], [-29, 24.5], [29, 24.5]];
PI_STUB_H  = 6;
PI_STUB_D  = 6;
PI_Z       = Z_FOOT + FLOOR + PI_STUB_H;   // PCB underside
PI_USBC_X  = -31.3;

// Speaker: 57 mm (2.25") full-range driver, cone up, frame screwed to the platform.
SPK_OD     = 57;
SPK_HOLE_D = 63;   // frame screw-hole circle — measure your driver
SPK_CUT_D  = 50;   // hole under the driver (magnet clearance + back-wave vent)
SPK_DEPTH  = 28;   // ghost only
PLAT_T     = 3;

BUTTON_D   = 12.4; // 12 mm momentary push button at the apex
PILOT_M25  = 2.2;  // self-tapping M2.5 into PLA/PETG

FN = 160;

/* ---------- egg math ---------- */
function egg_r(z) = let (u = 2 * z / H - 1)
    (D / 2) * sqrt(max(0, 1 - u * u)) * (1 - E * u);

N = 120;
// Full left+right outline, so offset() shrinks it from the skin only. A
// half-profile starting at x=0 gets pulled off the axis by a negative offset,
// which left a Ø2·|off| solid column up the middle of every hollow (the
// "thin pillar crossing the Pi" seen in v2/v3 sections).
egg_pts = concat([for (i = [0 : N]) let (z = H * i / N) [egg_r(z), z]],
                 [for (i = [N : -1 : 0]) let (z = H * i / N) [-egg_r(z), z]]);

module egg_solid(off = 0) {
    rotate_extrude($fn = FN)
        intersection() {
            offset(delta = off) polygon(egg_pts);
            translate([0, -5]) square([D, H + 10]);   // keep x >= 0 for extrusion
        }
}
module shell() difference() { egg_solid(0); egg_solid(-WALL); }
module slab(z0, z1) translate([-D, -D, z0]) cube([2 * D, 2 * D, z1 - z0]);

module lip(zs) intersection() {          // on the lower part
    difference() { egg_solid(-(WALL / 2 + CLR)); egg_solid(-WALL); }
    slab(zs, zs + LIP_H);
}
module recess(zs) intersection() { egg_solid(-WALL / 2); slab(zs - 0.01, zs + LIP_H); }

/* ---------- bowl ---------- */
module bowl() {
    z_floor = Z_FOOT + FLOOR;
    difference() {
        union() {
            intersection() { shell(); slab(Z_FOOT, Z_SEAM); }
            intersection() { egg_solid(0); slab(Z_FOOT, z_floor); }        // floor
            lip(Z_SEAM);
            // platform ledge: a ring bonded to the inner wall
            intersection() {
                difference() {
                    egg_solid(-1);
                    cylinder(r = egg_r(Z_LEDGE) - WALL - LEDGE_W, h = 3 * H, center = true, $fn = FN);
                }
                slab(Z_LEDGE - LEDGE_T, Z_LEDGE);
            }
            // Pi stubs
            for (p = PI_HOLES) translate([p[0], p[1], z_floor - 0.01])
                cylinder(d = PI_STUB_D, h = PI_STUB_H, $fn = 24);
        }
        for (p = PI_HOLES) translate([p[0], p[1], z_floor + 1])
            cylinder(d = PILOT_M25, h = PI_STUB_H + 1, $fn = 16);
        // USB-C power slot at the back
        translate([PI_USBC_X - 7, 30, PI_Z + 1.6 - 1]) cube([14, D, 9]);
        // vents at the back, beside the Pi's ports
        for (k = [-3 : 3]) translate([k * 8 + 14, 30, PI_Z + 4]) cube([2, D, 14]);
    }
}

/* ---------- platform (speaker shelf) ---------- */
PLAT_R = egg_r(Z_LEDGE) - WALL - CLR;
module platform() difference() {
    cylinder(r = PLAT_R, h = PLAT_T, $fn = FN);
    translate([0, 0, -1]) cylinder(d = SPK_CUT_D, h = PLAT_T + 2, $fn = 96);
    for (a = [45 : 90 : 359]) translate([SPK_HOLE_D / 2 * cos(a), SPK_HOLE_D / 2 * sin(a), -1])
        cylinder(d = PILOT_M25, h = PLAT_T + 2, $fn = 16);
    // cable notch at the back (speaker + mic leads down to the Pi)
    translate([-8, PLAT_R - 12, -1]) cube([16, 20, PLAT_T + 2]);
}

/* ---------- dome ---------- */
module dome() difference() {
    intersection() { shell(); slab(Z_SEAM, H); }
    recess(Z_SEAM);
    translate([0, 0, H - 30]) cylinder(d = BUTTON_D, h = 40, $fn = 48);   // button
    slab(H - 1.6, H + 5);                                                  // flat for the nut
    // sound/mic slits: a band of 24 vertical slots just above the seam
    for (a = [0 : 15 : 359]) rotate([0, 0, a])
        translate([D / 2 - WALL - 6, -1, Z_SEAM + LIP_H + 3]) cube([WALL + 12, 2, 16]);
}

/* ---------- assembly preview ---------- */
module ghosts() {
    %translate([-42.5, -28, PI_Z]) cube([85, 56, 1.6 + 16]);                       // Pi 5 + ports
    %translate([0, 0, Z_LEDGE + PLAT_T]) cylinder(d = SPK_OD, h = SPK_DEPTH, $fn = 64); // driver, cone up
}
module assembly() {
    color("Gainsboro") bowl();
    color("Silver") translate([0, 0, Z_LEDGE]) platform();
    color("Gainsboro") dome();
    ghosts();
}

if (part == "bowl")     bowl();
if (part == "platform") platform();
if (part == "dome")     dome();
if (part == "assembly") {
    if (cut) difference() { assembly(); translate([0, -D, -1]) cube([D, 2 * D, H + 2]); }
    else assembly();
}
