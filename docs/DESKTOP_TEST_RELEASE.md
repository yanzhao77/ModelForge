# macOS 桌面端测试版发布指南

桌面客户端通过 GitHub Release API 检查更新。运行 `scripts/build_desktop_macos_test.sh` 只会在本地生成测试资产，**不会上传或发布**。

| 项目 | 测试版要求 |
|---|---|
| 版本号 | `client/pyside6/version.py` 使用递增测试版本，例如 `0.1.1-beta.1`。 |
| 安装资产 | 资产名包含 `macOS`，例如 `ModelForge-macOS-0.1.1-beta.1.zip`。 |
| 校验文件 | 同一 Release 中必须包含 `checksums.txt`。 |
| Release 类型 | 建议创建 GitHub **Pre-release**，完成实机回归后再创建正式版。 |
| 安全边界 | 客户端只下载并校验资产，仍由用户确认打开安装包。 |

## 本地构建

```bash
python3 -m pip install -r requirements-gui.txt -r requirements-build.txt
chmod +x scripts/build_desktop_macos_test.sh
PYTHON_BIN=python3 scripts/build_desktop_macos_test.sh
```

生成物位于 `release-artifacts/`。上传前，请在干净 macOS 环境中解压并验证登录、Models 远程模型管理和语言切换。
