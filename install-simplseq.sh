#!/usr/bin/env bash
set -euo pipefail

VERSION="${SIMPLSEQ_VERSION:-v1.0}"
TARBALL="simplseq-nf-app-${VERSION}.tar.gz"
CHECKSUMS="SHA256SUMS.txt"
DEFAULT_BASE_URL="https://github.com/a-nadeem9/simplseq-nf-app/releases/download/${VERSION}"
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
UNAME_S="$(uname -s)"
UNAME_M="$(uname -m)"

say() {
  printf '\n== %s ==\n' "$1"
}

banner() {
  cat <<EOF
======================================================
  >_ SIMPLseq-nf App ${VERSION}
     Linux / WSL / macOS browser workflow setup
     Nextflow + Conda/Mamba runtime
======================================================
EOF
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

case "$UNAME_S" in
  Linux)
    PLATFORM_LABEL="Linux / WSL"
    MAMBA_SUBDIR="linux-64"
    PROFILE_FILE="${HOME}/.bashrc"
    SHA256_CHECK=(sha256sum -c)
    ;;
  Darwin)
    PLATFORM_LABEL="macOS"
    PROFILE_FILE="${HOME}/.zshrc"
    SHA256_CHECK=(shasum -a 256 -c)
    case "$UNAME_M" in
      arm64) MAMBA_SUBDIR="osx-arm64" ;;
      x86_64) MAMBA_SUBDIR="osx-64" ;;
      *) fail "Unsupported macOS CPU architecture: $UNAME_M" ;;
    esac
    ;;
  *)
    fail "This installer supports Linux/WSL and macOS only."
    ;;
esac

fetch_asset() {
  local name="$1"
  local target="$2"
  if [[ "$BASE_URL" =~ ^https?:// || "$BASE_URL" =~ ^file:// ]]; then
    if [[ -n "$AUTH_TOKEN" && "$BASE_URL" =~ github.com ]]; then
      fetch_github_release_asset "$name" "$target"
    else
      curl -fsSL "${BASE_URL%/}/${name}" -o "$target"
    fi
  else
    cp "${BASE_URL%/}/${name}" "$target"
  fi
}

fetch_github_release_asset() {
  local name="$1"
  local target="$2"
  local release_path owner repo tag api_url release_json asset_url

  release_path="${BASE_URL#https://github.com/}"
  owner="${release_path%%/*}"
  release_path="${release_path#*/}"
  repo="${release_path%%/*}"
  tag="${release_path#*releases/download/}"
  tag="${tag%%/*}"

  [[ -n "$owner" && -n "$repo" && -n "$tag" && "$tag" != "$release_path" ]] \
    || fail "Cannot parse GitHub release URL for private asset download: $BASE_URL"

  api_url="https://api.github.com/repos/${owner}/${repo}/releases/tags/${tag}"
  release_json="$(mktemp)"
  curl -fsSL \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "$api_url" -o "$release_json"

  asset_url="$(
    awk -v asset_name="$name" '
      BEGIN { RS = "\\{"; FS = "," }
      index($0, "\"name\":\"" asset_name "\"") || index($0, "\"name\": \"" asset_name "\"") {
        if (match($0, /\"url\"[[:space:]]*:[[:space:]]*\"[^\"]+\"/)) {
          s = substr($0, RSTART, RLENGTH)
          sub(/.*\"url\"[[:space:]]*:[[:space:]]*\"/, "", s)
          sub(/\"$/, "", s)
          print s
          exit
        }
      }
    ' "$release_json"
  )"
  rm -f "$release_json"

  [[ -n "$asset_url" ]] || fail "No GitHub release asset found for $name"
  curl -fsSL \
        -H "Authorization: Bearer ${AUTH_TOKEN}" \
        -H "Accept: application/octet-stream" \
        "$asset_url" -o "$target"
}

mkdir -p "$CACHE_DIR" "$SIMPLSEQ_HOME/bin" "$SIMPLSEQ_HOME/versions" "$SIMPLSEQ_HOME/envs" "$LOG_DIR" "$BIN_DIR"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

banner
echo "Platform: $PLATFORM_LABEL ($MAMBA_SUBDIR)"
echo "Base URL: $BASE_URL"
echo "Install log: $LOG_FILE"

say "Downloading release files"
fetch_asset "$TARBALL" "$CACHE_DIR/$TARBALL"
fetch_asset "$CHECKSUMS" "$CACHE_DIR/$CHECKSUMS"

say "Verifying checksum"
tr -d '\r' < "$CACHE_DIR/$CHECKSUMS" > "$CACHE_DIR/${CHECKSUMS}.unix"
grep "  ${TARBALL}$" "$CACHE_DIR/${CHECKSUMS}.unix" > "$CACHE_DIR/${TARBALL}.sha256" \
  || fail "No checksum entry found for $TARBALL"
(cd "$CACHE_DIR" && "${SHA256_CHECK[@]}" "${TARBALL}.sha256")

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
  curl -fsSL "https://micro.mamba.pm/api/micromamba/${MAMBA_SUBDIR}/latest" -o "$MM_TMP/micromamba.tar.bz2"
  tar -xjf "$MM_TMP/micromamba.tar.bz2" -C "$MM_TMP"
  cp "$MM_TMP/bin/micromamba" "$MICROMAMBA"
  chmod +x "$MICROMAMBA"
  rm -rf "$MM_TMP"
fi

say "Creating managed runtime"
export MAMBA_ROOT_PREFIX="${SIMPLSEQ_HOME}/mamba_root"
export CONDA_PKGS_DIRS="${SIMPLSEQ_HOME}/pkgs"
mkdir -p "$MAMBA_ROOT_PREFIX" "$CONDA_PKGS_DIRS"
cd "$VERSION_DIR"
LOCK_FILE="$VERSION_DIR/locks/linux-64-explicit.txt"
if [[ "$UNAME_S" == "Linux" && -f "$LOCK_FILE" && "${SIMPLSEQ_USE_LOCK:-1}" != "0" ]]; then
  if [[ -x "$ENV_DIR/bin/python" ]]; then
    "$MICROMAMBA" install -y -p "$ENV_DIR" -f "$LOCK_FILE"
  else
    "$MICROMAMBA" create -y -p "$ENV_DIR" -f "$LOCK_FILE"
  fi
  "$ENV_DIR/bin/python" -m pip install -e "$VERSION_DIR"
else
  if [[ -x "$ENV_DIR/bin/python" ]]; then
    "$MICROMAMBA" install -y -p "$ENV_DIR" -f "$VERSION_DIR/environment.yml"
  else
    "$MICROMAMBA" create -y -p "$ENV_DIR" -f "$VERSION_DIR/environment.yml"
  fi
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
export SIMPLSEQ_VERSION="\${VERSION}"
export PYTHONPATH="\${PROJECT_ROOT}/src\${PYTHONPATH:+:\${PYTHONPATH}}"
export PATH="\${ENV_DIR}/bin:\${PATH}"

exec "\${ENV_DIR}/bin/python" -m simplseq "\$@"
EOF
chmod +x "$BIN_DIR/simplseq"

say "Checking PATH"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  touch "$PROFILE_FILE"
  if ! grep -q 'SIMPLseq-nf App launcher path' "$PROFILE_FILE"; then
    cat >> "$PROFILE_FILE" <<'EOF'

# SIMPLseq-nf App launcher path
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
EOF
  fi
  echo "$BIN_DIR is not currently on PATH in this shell."
  echo "Open a new shell, or run:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
  echo "PATH update written to: $PROFILE_FILE"
fi

say "Verifying SIMPLseq"
"$BIN_DIR/simplseq" --help >/dev/null
"$BIN_DIR/simplseq" check
"$BIN_DIR/simplseq" run-headless --help >/dev/null

say "Setup complete"
cat <<'EOF'
Start SIMPLseq-nf App with:

    simplseq run
EOF
