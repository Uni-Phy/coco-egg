# coco-egg enclosure v3

Parametric OpenSCAD design for the coco-egg zero shell (spec §6). Everything
is in [`egg.scad`](egg.scad); every dimension is a named parameter at the top.
v2's files lived in Downloads and were lost — v3 lives here.

```
make stl        # out/egg_v3_{bowl,tray,collar,dome}.stl
make preview    # out/assembly.png, out/section.png
```
Needs OpenSCAD 2025+ with the manifold backend
(`brew install --cask openscad@snapshot`).

## Parts (4, all support-free)

| Part | Print orientation | Filament | Holds |
|---|---|---|---|
| **bowl** | as modelled, feet down | opaque | speaker (down-firing, in the floor), Pi 5 on 34 mm standoffs |
| **tray** | flat | any | ReSpeaker XVF3800 on 3 bosses, mics/LEDs up |
| **collar** | flat (ring) | **clear / white translucent** | nothing — it's the glow band over the board's 12 onboard LEDs, slitted for the mics |
| **dome** | upside down, seam rim on the bed | opaque | 12 mm push-to-talk button at the apex |

The egg splits at its widest point (Ø150), so every component drops in from
the top. Seams are friction-fit: a half-wall lip on the lower part slides into a
recess in the upper part, 0.2 mm radial clearance (`CLR` — tune to your printer).

Plain (no glow) variant: set `COLLAR_H = 0` and print bowl + tray + dome only.

## Assembly order

1. Screw the 57 mm driver to the bowl floor, cone down over the hex grille
   (4× M2.5 self-tapping into the pilot holes on the Ø63 circle).
2. Drop the Pi 5 onto the standoffs, HDMI/USB-C edge facing the back (the wall
   slot and vents). 4× M2.5 self-tapping.
3. Tray onto the ledge, then the XVF3800 onto the tray bosses (3× M3
   self-tapping), USB-C edge facing the front.
4. Cables: XVF3800 USB-C → Pi USB-A, speaker JST → XVF3800, button → GPIO.
   **Use right-angle USB-C plugs** — a straight plug at the board edge hits the
   wall (24 mm clearance).
5. Collar, then dome (button wired first).

## Dimensions that matter

- Egg Ø150 × 200 (186 standing: flat foot at z=20, 6 mm feet). Fits an Ender-3 S1
  bed (220×220) with room; tallest part (dome) is ~88 mm.
- Wall 2.4 mm (6 perimeters at 0.4). Floor 2.4 mm.
- XVF3800 per Seeed's 2D drawing: Ø100 board, mounting holes at (±21.36, 24.5)
  and (0, −34), mics on a 66×66 square, 12 LEDs on a ~Ø78 circle.
- Pi 5 hole pattern 58×49.

## Known trade-offs (fix with real prints)

- Speaker frame dimensions vary by driver — `SPK_HOLE_D` is set for a typical
  57 mm frame with holes on Ø63. Measure yours.
- The foot region's outward flare is a ~50° overhang for the first few layers;
  it printed fine on v2, expect the same.
- Collar glow depends on the filament: clear PETG glows brightest, white PLA
  diffuses most evenly.
