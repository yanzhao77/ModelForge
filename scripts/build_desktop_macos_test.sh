#!/usr/bin/env bash
set -euo pipefail

# Build a checksum-protected macOS test artifact. This script never uploads.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DIST_DIR="${ROOT}/release-artifacts"
VERSION="$(sed -n 's/^APP_VERSION = "\([^"]*\)"/\1/p' "${ROOT}/client/pyside6/version.py")"
ASSET="ModelForge-macOS-${VERSION}.zip"

[[ -n "${VERSION}" ]] || { echo "无法读取 APP_VERSION。" >&2; exit 1; }
cd "${ROOT}"
rm -rf build dist "${DIST_DIR}"
mkdir -p "${DIST_DIR}"

"${PYTHON_BIN}" -m PyInstaller \
  --noconfirm --clean --windowed --name ModelForge \
  --paths client/pyside6 \
  --add-data "client/pyside6/i18n:i18n" \
  --add-data "client/pyside6/theme:theme" \
  --hidden-import cryptography.fernet \
  --hidden-import httpx \
  client/pyside6/main.py

[[ -d "dist/ModelForge.app" ]] || { echo "未生成 ModelForge.app。" >&2; exit 1; }
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VERSION}" "dist/ModelForge.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string ${VERSION}" "dist/ModelForge.app/Contents/Info.plist"
codesign --force --deep --sign - "dist/ModelForge.app"
ditto -c -k --sequesterRsrc --keepParent "dist/ModelForge.app" "${DIST_DIR}/${ASSET}"
(
  cd "${DIST_DIR}"
  shasum -a 256 "${ASSET}" > checksums.txt
)
cat > "${DIST_DIR}/TEST_RELEASE_NOTES.md" <<EOF
# ModelForge ${VERSION} 测试版

此包包含统一 Models 管理、远程 OpenAI 兼容模型服务、Responses API 与 Chat Completions API 适配、简体中文默认及中英日运行时切换。

GitHub Pre-release 资产：
- ${ASSET}
- checksums.txt
EOF
echo "测试版资产：${DIST_DIR}/${ASSET}"
