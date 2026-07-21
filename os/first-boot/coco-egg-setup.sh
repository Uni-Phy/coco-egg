#!/bin/bash
# coco-egg first-boot provisioning.
# Adapted from Uni-Phy/common-os config/Automation_Custom_Script.sh —
# we keep its performance tuning + Ollama pattern, drop the Cloudflare
# tunnel (ShellHub replaces it, spec §9) and the web UI.
set -e
LOG=/var/log/coco-egg-setup.log
log() { echo "$(date): $1" | tee -a "$LOG"; }

log "1/5 System update"
apt-get update && apt-get upgrade -y

log "2/5 Performance tuning (from common-os)"
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true
# Swap headroom for the local LLM
if [ -f /etc/dphys-swapfile ]; then
  sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
  systemctl restart dphys-swapfile || true
fi

log "3/5 Ollama (local tutor LLM server)"
command -v ollama >/dev/null || curl -fsSL https://ollama.ai/install.sh | sh
systemctl enable --now ollama || true
# Model pull is deferred to the content-pack sync (large download).

log "4/5 ShellHub agent (fleet access, spec §9)"
bash "$(dirname "$0")/../shellhub/install-agent.sh" || log "WARN: ShellHub install failed — device will be unmanaged"

log "5/5 Audio deps + app"
apt-get install -y alsa-utils libportaudio2 python3-venv
# App container/service installation lands here (deploy/Dockerfile) at M1.

log "coco-egg first boot complete"
