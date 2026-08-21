#!/usr/bin/env bash
set -euo pipefail

# Build a checksum-protected Linux test package. This script never uploads.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DIST_DIR="${ROOT}/release-artifacts"
VERSION="$(sed -n 's/^APP_VERSION = "\([^"]*\)"/\1/p' "${ROOT}/client/pyside6/version.py")"
ASSET="ModelForge-linux-${VERSION}.zip"

[[ -n "${VERSION}" ]] || { echo "Unable to read APP_VERSION." >&2; exit 1; }
cd "${ROOT}"
rm -rf build dist
mkdir -p "${DIST_DIR}"

"${PYTHON_BIN}" -m PyInstaller \
  --noconfirm --clean --windowed --name ModelForge \
  --paths client/pyside6 \
  --add-data "client/pyside6/i18n:i18n" \
  --add-data "client/pyside6/theme:theme" \
  --hidden-import cryptography.fernet \
  --hidden-import httpx \
  client/pyside6/main.py

[[ -d "dist/ModelForge" ]] || { echo "ModelForge directory was not generated." >&2; exit 1; }
(
  cd dist
  zip -r -q "${DIST_DIR}/${ASSET}" ModelForge
)
(
  cd "${DIST_DIR}"
  shasum -a 256 "${ASSET}" >> checksums.txt
)
echo "Linux test asset: ${DIST_DIR}/${ASSET}"
