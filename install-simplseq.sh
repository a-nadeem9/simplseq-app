#!/usr/bin/env bash
set -euo pipefail

VERSION="${SIMPLSEQ_VERSION:-v0.1.0-dev}"
TARBALL="simplseq-app-${VERSION}.tar.gz"
CHECKSUMS="SHA256SUMS.txt"
DEFAULT_BASE_URL="https://github.com/a-nadeem9/simplseq-app/releases/download/${VERSION}"
BASE_URL="${SIMPLSEQ_INSTALL_BASE_URL:-$DEFAULT_BASE_URL}"
AUTH_TOKEN="${SIMPLSEQ_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"

CACHE_DIR="${HOME}/.cache/simplseq/${VERSION}"
SIMPLSEQ_HOME="${HOME}/.local/share/simplseq"
VERSION_DIR="${SIMPLSEQ_HOME}/versions/${VERSION}"
ENV_DIR="${SIMPLSEQ_HOME}/envs/${VERSION}"
LOG_DIR="${SIMPLSEQ_HOME}/logs"
BIN_DIR="${HOME}/.local/bin"
LOG_FILE="${LOG_DIR}/install-${VERSION}.log"
MICROMAMBA="${SIMPLSEQ_HOME}/bin/micromamba"

say() {
  printf '\n== %s ==\n' "$1"
}

banner() {
  cat <<EOF
======================================================
  >_ SIMPLseq App ${VERSION}
     Linux / WSL browser workflow setup
     Nextflow + Conda/Mamba runtime
======================================================
EOF
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

fetch_asset() {
  local name="$1"
  local target="$2"
  if [[ "$BASE_URL" =~ ^https?:// || "$BASE_URL" =~ ^file:// ]]; then
    if [[ -n "$AUTH_TOKEN" && "$BASE_URL" =~ github.com ]]; then
      curl -fsSL \
        -H "Authorization: Bearer ${AUTH_TOKEN}" \
        -H "Accept: application/octet-stream" \
        "${BASE_URL%/}/${name}" -o "$target"
    else
      curl -fsSL "${BASE_URL%/}/${name}" -o "$target"
    fi
  else
    cp "${BASE_URL%/}/${name}" "$target"
  fi
}

if [[ "$(uname -s)" != "Linux" ]]; then
  fail "This v0.1-dev installer currently supports Linux/WSL only."
fi

mkdir -p "$CACHE_DIR" "$SIMPLSEQ_HOME/bin" "$SIMPLSEQ_HOME/versions" "$SIMPLSEQ_HOME/envs" "$LOG_DIR" "$BIN_DIR"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

banner
echo "Base URL: $BASE_URL"
echo "Install log: $LOG_FILE"

say "Downloading release files"
fetch_asset "$TARBALL" "$CACHE_DIR/$TARBALL"
fetch_asset "$CHECKSUMS" "$CACHE_DIR/$CHECKSUMS"

say "Verifying checksum"
tr -d '\r' < "$CACHE_DIR/$CHECKSUMS" > "$CACHE_DIR/${CHECKSUMS}.unix"
grep "  ${TARBALL}$" "$CACHE_DIR/${CHECKSUMS}.unix" > "$CACHE_DIR/${TARBALL}.sha256" \
  || fail "No checksum entry found for $TARBALL"
(cd "$CACHE_DIR" && sha256sum -c "${TARBALL}.sha256")

say "Installing app files"
TMP_INSTALL="$(mktemp -d)"
trap 'rm -rf "$TMP_INSTALL"' EXIT
tar -xzf "$CACHE_DIR/$TARBALL" -C "$TMP_INSTALL"
EXTRACTED="$(find "$TMP_INSTALL" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[[ -n "$EXTRACTED" ]] || fail "Tarball did not contain an app directory."
rm -rf "${VERSION_DIR}.tmp"
cp -a "$EXTRACTED" "${VERSION_DIR}.tmp"
rm -rf "$VERSION_DIR"
mv "${VERSION_DIR}.tmp" "$VERSION_DIR"
ln -sfn "$VERSION_DIR" "${SIMPLSEQ_HOME}/current"

say "Installing micromamba"
if [[ ! -x "$MICROMAMBA" ]]; then
  MM_TMP="$(mktemp -d)"
  curl -fsSL "https://micro.mamba.pm/api/micromamba/linux-64/latest" -o "$MM_TMP/micromamba.tar.bz2"
  python3 - "$MM_TMP" <<'PY'
import sys
import tarfile
from pathlib import Path

tmp = Path(sys.argv[1])
with tarfile.open(tmp / "micromamba.tar.bz2", "r:bz2") as archive:
    archive.extractall(tmp)
PY
  cp "$MM_TMP/bin/micromamba" "$MICROMAMBA"
  chmod +x "$MICROMAMBA"
  rm -rf "$MM_TMP"
fi

say "Creating managed runtime"
export MAMBA_ROOT_PREFIX="${SIMPLSEQ_HOME}/mamba_root"
export CONDA_PKGS_DIRS="${SIMPLSEQ_HOME}/pkgs"
mkdir -p "$MAMBA_ROOT_PREFIX" "$CONDA_PKGS_DIRS"
cd "$VERSION_DIR"
if [[ -x "$ENV_DIR/bin/python" ]]; then
  "$MICROMAMBA" install -y -p "$ENV_DIR" -f "$VERSION_DIR/environment.yml"
else
  "$MICROMAMBA" create -y -p "$ENV_DIR" -f "$VERSION_DIR/environment.yml"
fi

say "Creating launcher"
cat > "$BIN_DIR/simplseq" <<EOF
#!/usr/bin/env bash
set -euo pipefail

SIMPLSEQ_HOME="\${HOME}/.local/share/simplseq"
VERSION="${VERSION}"
PROJECT_ROOT="\${SIMPLSEQ_HOME}/current"
ENV_DIR="\${SIMPLSEQ_HOME}/envs/\${VERSION}"

export SIMPLSEQ_PROJECT_ROOT="\${PROJECT_ROOT}"
export SIMPLSEQ_ENV_DIR="\${ENV_DIR}"
export PYTHONPATH="\${PROJECT_ROOT}/src\${PYTHONPATH:+:\${PYTHONPATH}}"
export PATH="\${ENV_DIR}/bin:\${PATH}"

exec "\${ENV_DIR}/bin/python" -m simplseq "\$@"
EOF
chmod +x "$BIN_DIR/simplseq"

say "Checking PATH"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  if [[ -f "$HOME/.bashrc" ]] && ! grep -q 'SIMPLseq App launcher path' "$HOME/.bashrc"; then
    cat >> "$HOME/.bashrc" <<'EOF'

# SIMPLseq App launcher path
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
EOF
  fi
  echo "$BIN_DIR is not currently on PATH in this shell."
  echo "Open a new shell, or run:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi

say "Verifying SIMPLseq"
"$BIN_DIR/simplseq" --help >/dev/null
"$BIN_DIR/simplseq" check
"$BIN_DIR/simplseq" run-headless --help >/dev/null

say "Setup complete"
cat <<'EOF'
Start SIMPLseq App with:

    simplseq run
EOF
