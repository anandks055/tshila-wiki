#!/usr/bin/env bash
# One-time (or periodic) sync of markdown articles TO the Oracle VM.
# Run from the university server (outbound rsync only — no inbound ports needed).
#
# Usage:
#   bash deploy/oracle-vm/sync-articles.sh ubuntu@<oracle-vm-public-ip>
#
# Requires SSH key access to the VM. First run may take a while (~1.2 GB).

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <user>@<oracle-vm-host>"
  exit 1
fi

REMOTE="$1"
SOURCE_DIR="${SOURCE_DIR:-/home/anandks/wiki-articles}"
DEST_DIR="/data/wiki-articles"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Source directory not found: ${SOURCE_DIR}"
  exit 1
fi

echo "==> Ensuring destination exists on ${REMOTE}"
ssh "${REMOTE}" "sudo mkdir -p ${DEST_DIR} && sudo chown -R \$(whoami):\$(whoami) ${DEST_DIR}"

echo "==> Syncing ${SOURCE_DIR} -> ${REMOTE}:${DEST_DIR}"
rsync -avz --progress \
  --include="*.md" \
  --exclude="*" \
  "${SOURCE_DIR}/" "${REMOTE}:${DEST_DIR}/"

echo "==> Done. Article count on VM:"
ssh "${REMOTE}" "find ${DEST_DIR} -maxdepth 1 -name '*.md' | wc -l"
