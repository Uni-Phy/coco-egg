// coco-egg zero — enclosure v3 (parametric OpenSCAD)
//
// Four printed parts, all simple to print, no supports:
//   bowl   — lower egg. 57 mm speaker down-firing through a hex grille in the
//            floor (four feet lift the egg 6 mm so sound gets out, Echo-Dot
//            style), Pi 5 stacked above it on integral standoffs, USB-C power
//            slot and vents at the back, an internal ledge near the rim that
//            the tray rests on. No grille on the skin: the egg's only face is
//            the glow collar.
//   tray   — flat spider ring that drops onto the ledge and carries the
//            ReSpeaker XVF3800 (Ø100 board) on three screw bosses, mics/LEDs up.
//   collar — short translucent ring right above the board's 12 onboard LEDs:
//            the egg's glowing state band. 24 vertical slits give the mics air.
//            Print it in clear/white filament. Set COLLAR_H = 0 for a plain egg.
//   dome   — upper egg with the push-to-talk button at the apex.
//
// The egg splits at its widest point, so electronics drop in through a
// ~145 mm opening — v2 needed a separate carrier because its opening was small.
// Every seam is a half-wall lip on the lower part sliding into a matching
// recess in the upper part (friction fit, CLR radial clearance).
//
// Render:  openscad -o bowl.stl -D 'part="bowl"' egg.scad   (see Makefile)
// Preview: part="assembly" (add cut=true for a cross-section)

part = "assembly";   // bowl | tray | collar | dome | assembly
cut  = false;        // assembly only: cut away x>0 to show the interior

/* ---------- egg ---------- */
D    = 150;    // max diameter
H    = 200;    // full (uncut) egg height
E    = 0.15;   // egg-ness: 0 = ellipsoid, larger = pointier top
WALL = 2.4;    // 6 perimeters at 0.4 mm nozzle
CLR  = 0.2;    // radial clearance at every seam
LIP_H = 5;

Z_FOOT   = 20;    // flat cut at the bottom -> Ø100 foot, egg stands
FLOOR    = 2.4;
Z_SEAM   = 100;   // bowl/collar seam (at the widest point)
COLLAR_H = 18;    // 0 for the plain (no glow band) variant
Z_DOME   = Z_SEAM + COLLAR_H;
Z_LEDGE  = 88;    // tray ledge inside the bowl
LEDGE_T  = 4;
LEDGE_R  = 64;    // ledge reaches inward to this radius

/* ---------- components ---------- */
// Raspberry Pi 5: 85 x 56, holes 58 x 49, 3.5 mm in from the edges.
PI_HOLES   = [[-29, -24.5], [29, -24.5], [-29, 24.5], [29, 24.5]];
PI_STAND_H = 34;   // clears a 28 mm deep driver sitting on the floor
PI_Z       = Z_FOOT + FLOOR + PI_STAND_H;   // PCB underside
PI_USBC_X  = -31.3;   // USB-C power, on the +y (back) long edge

// Speaker: 57 mm (2.25") full-range driver, down-firing, frame screwed to the floor.
SPK_OD     = 57;
SPK_HOLE_D = 63;     // frame screw-hole circle, 4 holes at 45 deg
SPK_DEPTH  = 28;     // driver depth (ghost only)
GRILLE_R   = 26;     // hex grille radius in the floor
FOOT_H     = 6;      // feet: acoustic gap under the egg
FOOT_D     = 14;
FOOT_R     = 40;     // feet circle radius

// ReSpeaker XVF3800: Ø100, holes per Seeed 2D drawing, USB-C toward -y (front).
MIC_HOLES  = [[21.355, 24.5], [-21.355, 24.5], [0, -34]];
MIC_BOSS_H = 6;
TRAY_T     = 3;
PILOT_M3   = 2.6;   // self-tapping M3 into PLA/PETG
PILOT_M25  = 2.2;

BUTTON_D   = 12.4;  // 12 mm momentary push button at the apex

FN = 160;

/* ---------- egg math ---------- */
function egg_r(z) = let (u = 2 * z / H - 1)
    (D / 2) * sqrt(max(0, 1 - u * u)) * (1 - E * u);

N = 120;
egg_pts = concat([[0, 0]], [for (i = [0 : N]) let (z = H * i / N) [egg_r(z), z]], [[0, H]]);

module egg_solid(off = 0) {
    rotate_extrude($fn = FN)
        intersection() {
            offset(delta = off) polygon(egg_pts);
            translate([0, -5]) square([D, H + 10]);  // keep x >= 0 for extrusion
        }
}
module shell() difference() { egg_solid(0); egg_solid(-WALL); }
module slab(z0, z1) translate([-D, -D, z0]) cube([2 * D, 2 * D, z1 - z0]);

// lip: inner half of the wall, protruding LIP_H above zs (on the LOWER part)
module lip(zs) intersection() {
    difference() { egg_solid(-(WALL / 2 + CLR)); egg_solid(-WALL); }
    slab(zs, zs + LIP_H);
}
// recess: remove inner half of the wall for LIP_H above zs (on the UPPER part)
module recess(zs) intersection() { egg_solid(-WALL / 2); slab(zs - 0.01, zs + LIP_H); }

/* ---------- bowl ---------- */
module bowl() {
    z_floor = Z_FOOT + FLOOR;   // floor top surface
    intersection() {
        translate([0, 0, -FOOT_H - 1]) union() { translate([0, 0, FOOT_H + 1]) egg_solid(0); cylinder(r = D, h = FOOT_H + 1 + Z_FOOT + 1, $fn = 8); }
        difference() {
            union() {
                intersection() { shell(); slab(Z_FOOT, Z_SEAM); }
                intersection() { egg_solid(0); slab(Z_FOOT, z_floor); }   // floor
                lip(Z_SEAM);
                // tray ledge
                intersection() {
                    difference() { egg_solid(-1); cylinder(r = LEDGE_R, h = 3 * H, center = true, $fn = FN); }
                    slab(Z_LEDGE, Z_LEDGE + LEDGE_T);
                }
                // Pi standoffs (tall: the Pi sits above the driver)
                for (p = PI_HOLES) translate([p[0], p[1], z_floor - 0.01])
                    cylinder(d = 8, h = PI_STAND_H, $fn = 32);
                // feet
                for (a = [0 : 90 : 359]) translate([FOOT_R * cos(a), FOOT_R * sin(a), Z_FOOT - FOOT_H])
                    cylinder(d = FOOT_D, h = FOOT_H + 0.01, $fn = 32);
            }
            // Pi pilot holes
            for (p = PI_HOLES) translate([p[0], p[1], z_floor + 2])
                cylinder(d = PILOT_M25, h = PI_STAND_H, $fn = 16);
            // speaker frame screw pilots, through the floor
            for (a = [45 : 90 : 359]) translate([SPK_HOLE_D / 2 * cos(a), SPK_HOLE_D / 2 * sin(a), Z_FOOT - 1])
                cylinder(d = PILOT_M25, h = FLOOR + 2, $fn = 16);
            // hex grille in the floor under the driver
            for (row = [-6 : 6]) for (col = [-6 : 6])
                let (x = col * 4.6 + (row % 2 == 0 ? 0 : 2.3), y = row * 4.0)
                if (sqrt(x * x + y * y) <= GRILLE_R)
                    translate([x, y, Z_FOOT - 1]) cylinder(d = 3, h = FLOOR + 2, $fn = 12);
            // USB-C power slot at the back (Pi's HDMI/USB-C edge faces +y)
            translate([PI_USBC_X - 7, 30, PI_Z + 1.6 - 1]) cube([14, D, 9]);
            // vents at the back, above the Pi
            for (k = [-2 : 2]) translate([k * 8 - 1, 30, PI_Z + 20]) cube([2, D, 14]);
        }
    }
}

/* ---------- tray (carries the XVF3800) ---------- */
TRAY_R = egg_r(Z_LEDGE + LEDGE_T + 0.5) - WALL - 0.6;
module tray() difference() {
    union() {
        difference() { cylinder(r = TRAY_R, h = TRAY_T, $fn = FN); translate([0, 0, -1]) cylinder(r = TRAY_R - 9, h = TRAY_T + 2, $fn = FN); }
        difference() { cylinder(r = 40, h = TRAY_T, $fn = 96); translate([0, 0, -1]) cylinder(r = 26, h = TRAY_T + 2, $fn = 96); }
        for (a = [90, 210, 330]) rotate([0, 0, a]) translate([26, -4, 0]) cube([TRAY_R - 26 - 4, 8, TRAY_T]);
        for (p = MIC_HOLES) translate([p[0], p[1], TRAY_T - 0.01]) cylinder(d = 7, h = MIC_BOSS_H, $fn = 32);
    }
    for (p = MIC_HOLES) translate([p[0], p[1], -1]) cylinder(d = PILOT_M3, h = TRAY_T + MIC_BOSS_H + 2, $fn = 16);
}

/* ---------- collar (glow band) ---------- */
module collar() if (COLLAR_H > 0) difference() {
    union() { intersection() { shell(); slab(Z_SEAM, Z_DOME); } lip(Z_DOME); }
    recess(Z_SEAM);
    // 24 slits: air for the mics, and the LED light breaks through them too
    for (a = [0 : 15 : 359]) rotate([0, 0, a])
        translate([D / 2 - WALL - 6, -1, Z_SEAM + LIP_H + 2]) cube([WALL + 12, 2, COLLAR_H - LIP_H - 4]);
}

/* ---------- dome ---------- */
module dome() difference() {
    intersection() { shell(); slab(Z_DOME, H); }
    recess(Z_DOME);
    translate([0, 0, H - 30]) cylinder(d = BUTTON_D, h = 40, $fn = 48);  // button
    slab(H - 1.6, H + 5);                                                 // flat spot for the button nut
}

/* ---------- assembly preview ---------- */
module ghosts() {
    %translate([-42.5, -28, PI_Z]) cube([85, 56, 1.6 + 16]);                       // Pi 5 + connectors
    %translate([0, 0, Z_FOOT + FLOOR]) cylinder(d = SPK_OD, h = SPK_DEPTH, $fn = 64);           // driver, cone down
    %translate([0, 0, Z_LEDGE + LEDGE_T + TRAY_T + MIC_BOSS_H]) cylinder(d = 100, h = 1.2, $fn = 96); // XVF3800
}
module assembly() {
    color("Gainsboro") bowl();
    color("Silver") translate([0, 0, Z_LEDGE + LEDGE_T]) tray();
    color("LightCyan", 0.7) collar();
    color("Gainsboro") dome();
    ghosts();
}

if (part == "bowl")   bowl();
if (part == "tray")   tray();
if (part == "collar") collar();
if (part == "dome")   dome();
if (part == "assembly") {
    if (cut) difference() { assembly(); translate([0, -D, -1]) cube([D, 2 * D, H + 2]); }
    else assembly();
}
