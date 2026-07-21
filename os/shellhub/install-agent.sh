#!/bin/bash
# Install the ShellHub agent (docker) and enrol into the coco namespace.
# Spec §9: ShellHub = remote access + audit. It is NOT the OTA system (§10).
set -e
: "${SHELLHUB_SERVER:?Set SHELLHUB_SERVER (e.g. https://cloud.shellhub.io or self-hosted URL)}"
: "${SHELLHUB_TENANT:?Set SHELLHUB_TENANT (namespace tenant id)}"

command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

docker rm -f shellhub-agent 2>/dev/null || true
docker run -d --name shellhub-agent --restart on-failure --privileged \
  --network host --pid host -v /:/host \
  -e SHELLHUB_SERVER_ADDRESS="$SHELLHUB_SERVER" \
  -e SHELLHUB_TENANT_ID="$SHELLHUB_TENANT" \
  -e SHELLHUB_PRIVATE_KEY=/host/etc/coco/shellhub.key \
  shellhubio/agent:latest

echo "ShellHub agent running. Device will appear in namespace $SHELLHUB_TENANT."
