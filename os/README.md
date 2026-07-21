# coco-egg OS layer

Provisioning scripts for the device image. Base OS for v0 is Raspberry Pi
OS Lite 64-bit (spec §7); the DietPi automation pattern and the WiFi
provisioning manager are adapted/reused from
[Uni-Phy/common-os](https://github.com/Uni-Phy/common-os).

- `first-boot/coco-egg-setup.sh` — governor/swap tuning, Ollama, ShellHub, audio deps
- `wifi-manager/wifi-manager.sh` — hotspot⇆station auto-switching (reused
  verbatim from common-os; solves spec §11 network onboarding via AP mode)
- `shellhub/install-agent.sh` — fleet agent enrolment (spec §9)

Deliberately NOT carried over from common-os: Cloudflare tunnel
(ShellHub replaces it), web UI (node-side concern, not device).
