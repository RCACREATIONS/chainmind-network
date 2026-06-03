#!/usr/bin/env bash
# ChainMind Node — macOS / Linux installer
#
# One-command install:
#   curl -fsSL https://chainmind.com.ng/install.sh | bash
#
# Or with wget:
#   wget -qO- https://chainmind.com.ng/install.sh | bash
#
# What it does:
#   1. Detects your platform (macOS Intel / Apple Silicon / Linux x64)
#   2. Downloads the right binary from GitHub Releases (or mirror)
#   3. Installs to ~/.local/share/chainmind
#   4. Creates a symlink in ~/.local/bin/chainmind-node (or /usr/local/bin if you have write access)
#   5. Verifies SHA-256 checksum
#   6. Prints next steps

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
MANIFEST_PRIMARY="https://chainmind.com.ng/api/release/latest.json"
MANIFEST_MIRROR="https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json"
INSTALL_DIR="${CHAINMIND_INSTALL_DIR:-$HOME/.local/share/chainmind}"
BIN_DIR="${CHAINMIND_BIN_DIR:-$HOME/.local/bin}"

# ── Colors ────────────────────────────────────────────────────────────────────
PURPLE='\033[95m'
CYAN='\033[96m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Banner ────────────────────────────────────────────────────────────────────
banner() {
  echo -e ""
  echo -e "${PURPLE}${BOLD}  ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗███╗   ███╗██╗███╗   ██╗██████╗${RESET}"
  echo -e "${PURPLE}${BOLD} ██╔════╝██║  ██║██╔══██╗██║████╗  ██║████╗ ████║██║████╗  ██║██╔══██╗${RESET}"
  echo -e "${PURPLE}${BOLD} ██║     ███████║███████║██║██╔██╗ ██║██╔████╔██║██║██╔██╗ ██║██║  ██║${RESET}"
  echo -e "${PURPLE}${BOLD} ╚██████╗██║  ██║██║  ██║██║██║ ╚████║██║ ╚═╝ ██║██║██║ ╚████║██████╔╝${RESET}"
  echo -e "${PURPLE}${BOLD}  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═════╝${RESET}"
  echo -e "${CYAN}  Decentralised AI Network — Node Installer${RESET}"
  echo ""
}

# ── Helpers ───────────────────────────────────────────────────────────────────
need() {
  if ! command -v "$1" &>/dev/null; then
    echo -e "${RED}  ✗ Required tool not found: $1${RESET}"
    echo    "    Install it and re-run this script."
    exit 1
  fi
}

fetch_json() {
  local url="$1"
  if command -v curl &>/dev/null; then
    curl -fsSL --connect-timeout 10 "$url" 2>/dev/null
  elif command -v wget &>/dev/null; then
    wget -qO- "$url" 2>/dev/null
  fi
}

fetch_file() {
  local url="$1" dest="$2"
  if command -v curl &>/dev/null; then
    curl -fL --progress-bar -o "$dest" "$url"
  elif command -v wget &>/dev/null; then
    wget --show-progress -qO "$dest" "$url"
  fi
}

sha256_file() {
  local f="$1"
  if command -v sha256sum &>/dev/null; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v shasum &>/dev/null; then
    shasum -a 256 "$f" | awk '{print $1}'
  else
    echo ""
  fi
}

# ── Platform detection ────────────────────────────────────────────────────────
detect_platform() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
    Darwin)
      case "$arch" in
        arm64) echo "macos_arm64" ;;
        *)     echo "macos_x64"   ;;
      esac
      ;;
    Linux)
      echo "linux_x64"
      ;;
    *)
      echo -e "${RED}  ✗ Unsupported OS: $os${RESET}"
      exit 1
      ;;
  esac
}

# ── JSON parsing (no jq required) ────────────────────────────────────────────
json_get() {
  local json="$1" key="$2"
  echo "$json" | grep -o "\"${key}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
               | head -1 \
               | sed 's/.*: *"\([^"]*\)".*/\1/'
}

# ── Main ──────────────────────────────────────────────────────────────────────
banner

PLATFORM="$(detect_platform)"
echo -e "  Platform          : ${CYAN}${PLATFORM}${RESET}"
echo -e "  Install directory : ${CYAN}${INSTALL_DIR}${RESET}"
echo -e "  Bin directory     : ${CYAN}${BIN_DIR}${RESET}"
echo ""

# 1. Fetch manifest
echo -e "  ${CYAN}Fetching latest release info…${RESET}"
MANIFEST="$(fetch_json "$MANIFEST_PRIMARY")" || true
if [ -z "$MANIFEST" ]; then
  echo -e "  ${YELLOW}Primary server unreachable, trying mirror…${RESET}"
  MANIFEST="$(fetch_json "$MANIFEST_MIRROR")"
fi
if [ -z "$MANIFEST" ]; then
  echo -e "${RED}  ✗ Could not fetch release manifest. Check your internet connection.${RESET}"
  exit 1
fi

VERSION="$(json_get "$MANIFEST" "version")"
ASSET_URL="$(echo "$MANIFEST" | grep -o "\"${PLATFORM}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 | sed 's/.*"\([^"]*\)".*/\1/')"
EXPECTED_CS="$(echo "$MANIFEST" | grep -A10 '"checksums"' | grep "\"${PLATFORM}\"" | head -1 | sed 's/.*"\([0-9a-f]*\)".*/\1/')"

if [ -z "$VERSION" ] || [ -z "$ASSET_URL" ]; then
  echo -e "${RED}  ✗ Could not parse manifest for platform ${PLATFORM}.${RESET}"
  exit 1
fi

echo -e "  ${GREEN}Latest version : ${VERSION}${RESET}"
echo ""

# 2. Create dirs
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# Determine binary name
BINARY_NAME="ChainMind-Node"
DEST="${INSTALL_DIR}/${BINARY_NAME}"

# 3. Download
echo -e "  ${CYAN}Downloading binary…${RESET}"
if [[ "$ASSET_URL" == *.zip ]]; then
  TMP_ZIP="${INSTALL_DIR}/chainmind-tmp.zip"
  fetch_file "$ASSET_URL" "$TMP_ZIP"
  if command -v unzip &>/dev/null; then
    unzip -qo "$TMP_ZIP" -d "$INSTALL_DIR"
  else
    need unzip
  fi
  rm -f "$TMP_ZIP"
  # After unzip the binary should be inside
  BIN_FILE="$(find "$INSTALL_DIR" -maxdepth 1 -name 'ChainMind-Node' | head -1)"
  [ -n "$BIN_FILE" ] && mv "$BIN_FILE" "$DEST"
else
  fetch_file "$ASSET_URL" "$DEST"
fi

# 4. Verify checksum
if [ -n "$EXPECTED_CS" ] && [ "$EXPECTED_CS" != "REPLACE_WITH_SHA256_AFTER_BUILD" ]; then
  echo -e "  ${CYAN}Verifying checksum…${RESET}"
  ACTUAL_CS="$(sha256_file "$DEST")"
  if [ "$ACTUAL_CS" != "$EXPECTED_CS" ]; then
    echo -e "${RED}  ✗ Checksum mismatch!${RESET}"
    echo    "    Expected : $EXPECTED_CS"
    echo    "    Got      : $ACTUAL_CS"
    rm -f "$DEST"
    exit 1
  fi
  echo -e "  ${GREEN}✔ Checksum verified${RESET}"
fi

# 5. Make executable
chmod +x "$DEST"

# 6. Write VERSION
echo "$VERSION" > "${INSTALL_DIR}/VERSION"

# 7. Create symlink
LINK="${BIN_DIR}/chainmind-node"
ln -sf "$DEST" "$LINK"
echo -e "  ${GREEN}✔ Symlink created: ${LINK}${RESET}"

# 8. PATH notice
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo ""
  echo -e "  ${YELLOW}⚠  ${BIN_DIR} is not on your PATH.${RESET}"
  echo    "  Add this to your shell config (~/.bashrc, ~/.zshrc, etc.):"
  echo ""
  echo -e "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
  echo ""
  echo    "  Then reload with:  source ~/.bashrc"
else
  echo -e "  ${GREEN}✔ ${BIN_DIR} is already on PATH${RESET}"
fi

# 9. Done
echo ""
echo -e "  ${GREEN}${BOLD}✔ ChainMind Node v${VERSION} installed successfully!${RESET}"
echo ""
echo -e "  Run it with:  ${CYAN}chainmind-node${RESET}"
echo -e "  Or directly:  ${CYAN}${DEST}${RESET}"
echo ""
