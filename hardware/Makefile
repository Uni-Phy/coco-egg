# coco-egg enclosure v4 — render STLs, previews and STEP from egg.scad / egg_step.py.
# Needs OpenSCAD 2025+ (manifold backend): brew install --cask openscad@snapshot
OPENSCAD ?= openscad --backend=manifold --export-format binstl
PARTS = bowl platform dome

.PHONY: all stl preview step clean

all: stl preview

stl: $(PARTS:%=out/egg_v4_%.stl)
out/egg_v4_%.stl: egg.scad | out
	$(OPENSCAD) -o $@ -D 'part="$*"' $<

preview: out/assembly.png out/section.png
out/assembly.png: egg.scad | out
	$(OPENSCAD) -o $@ --imgsize=1400,1400 --camera=0,0,100,65,0,35,700 \
	  --colorscheme=Tomorrow --projection=p -D 'part="assembly"' $<
out/section.png: egg.scad | out
	$(OPENSCAD) -o $@ --imgsize=1400,1400 --camera=0,0,100,90,0,90,650 \
	  --colorscheme=Tomorrow --projection=o -D 'part="assembly"' -D 'cut=true' $<

out:
	mkdir -p out

step:             ## true B-rep STEP via CadQuery (python3.11 -m venv .venv-cad && .venv-cad/bin/pip install cadquery)
	.venv-cad/bin/python egg_step.py

clean:
	rm -rf out
