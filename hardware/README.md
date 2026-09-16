# coco-egg enclosure v4

Parametric OpenSCAD design for the coco-egg zero shell (spec §6). Everything
is in [`egg.scad`](egg.scad); every dimension is a named parameter at the top.

```
make stl        # out/egg_v4_{bowl,platform,dome}.stl
make preview    # out/assembly.png, out/section.png
```
Needs OpenSCAD 2025+ with the manifold backend
(`brew install --cask openscad@snapshot`).

## Three parts, all support-free

| Part | Print orientation | Holds |
|---|---|---|
| **bowl** (85 mm tall) | as modelled, flat foot down | Pi 5 on four 6 mm stubs straight on the floor |
| **platform** (3 mm disc) | flat | 57 mm speaker, cone up, 4 screws on the frame circle; cable notch at the back. Rests on a ledge above the Pi — print/iterate it independently |
| **dome** (98 mm tall) | upside down, seam rim on the bed | 12 mm push-to-talk button at the apex; 24 slits low on the dome let the speaker out and the mic in |

Egg splits at its widest point (Ø150), friction-fit: half-wall lip on the bowl,
recess in the dome, `CLR` = 0.2 mm radial (tune to your printer).

## What v4 fixed

- **The thin pillar through the Pi.** v2/v3 had a Ø4.8 mm solid column up the
  axis from floor to seam. It was a modelling bug, not a feature: the 2D egg
  profile started at x=0, so `offset(delta=-WALL)` pulled the inner cavity off
  the axis. The profile is now the full outline (both sides) so offsets shrink
  from the skin only. Verified: the bowl STL has no geometry within 10 mm of
  the axis above the floor.
- **No more tall standoffs.** v3 stacked the Pi 34 mm above a down-firing
  speaker on Ø8 pillars. v4: Pi on the floor, everything else on the
  removable platform.
- One fewer part (collar/tray gone). Mic board goes on the platform beside the
  driver; add its pilot holes to `platform()` once the board is chosen
  (ReSpeaker Lite recommended over the XVF3800 — half the price, same USB
  plug-and-play path, has the 5 W speaker amp).

## Assembly

1. Pi 5 onto the four stubs, HDMI/USB-C edge facing the back (slot + vents).
   4× M2.5 self-tapping.
2. Driver onto the platform, cone up, 4× M2.5 self-tapping through the frame
   into the pilot holes on the Ø63 circle (`SPK_HOLE_D` — measure your driver).
   Mic board next to it.
3. Cables down through the platform's back notch to the Pi.
4. Platform onto the ledge; dome on (button wired first).

## Dimensions

- Egg Ø150 × 200 (180 standing — flat cut at z=20). Fits an Ender-3 S1 bed.
- Wall / floor 2.4 mm. Pi stubs Ø6 × 6. Platform ledge top at z=58, clears
  the Pi's USB ports (~46) by 12 mm; driver top lands ~89, seam is at 100.
- Pi 5 hole pattern 58×49; USB-C power slot and vents on the +y wall.
