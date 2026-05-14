#!/usr/bin/env bash
set -euo pipefail

VERSION="${SIMPLSEQ_VERSION:-v1.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/../release_artifacts/${VERSION}}"
APP_DIR="simplseq-nf-app-${VERSION}"
TARBALL="simplseq-nf-app-${VERSION}.tar.gz"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$OUT_DIR" "$TMP_DIR/$APP_DIR"

rsync -a "$ROOT_DIR/" "$TMP_DIR/$APP_DIR/" \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.venv/' \
  --exclude '.venv-*/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.egg-info/' \
  --exclude 'release_artifacts/' \
  --exclude 'release_build*/' \
  --exclude 'ui_snapshots/' \
  --exclude 'results*/' \
  --exclude 'outputs/' \
  --exclude 'work/' \
  --exclude '.nextflow*' \
  --exclude 'data/*' \
  --exclude 'test-data/' \
  --exclude 'test-data-*/' \
  --exclude '*.fastq' \
  --exclude '*.fastq.gz' \
  --exclude '*.fq' \
  --exclude '*.fq.gz' \
  --exclude '*.md5' \
  --exclude 'samples.csv' \
  --exclude '*_samples.csv'

tar -C "$TMP_DIR" -czf "$OUT_DIR/$TARBALL" "$APP_DIR"
sed "s/^VERSION=\"\${SIMPLSEQ_VERSION:-.*}\"/VERSION=\"\${SIMPLSEQ_VERSION:-${VERSION}}\"/" \
  "$ROOT_DIR/install-simplseq.sh" > "$OUT_DIR/install-simplseq.sh"
chmod +x "$OUT_DIR/install-simplseq.sh"

(
  cd "$OUT_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$TARBALL" > SHA256SUMS.txt
  else
    shasum -a 256 "$TARBALL" > SHA256SUMS.txt
  fi
)

cat "$OUT_DIR/SHA256SUMS.txt"
