# ModelForge v0.1.1-beta.1 Pre-release 就绪报告

**审阅日期：** 2026-08-21  
**候选标签：** `v0.1.1-beta.1`  
**标签目标提交：** `dd570e79d82dc13679af55e0e1af473f4d53df61`  
**当前开发分支：** `master`（包含候选提交的后续开发，不应用作此既有测试包的标签目标）

> 该测试包内置版本为 `0.1.1-beta.1`，而发布资产是在 `dd570e7` 的“prepare desktop 0.1.1-beta.1 test build”提交中准备的。为保留版本与二进制来源的一致性，Pre-release 标签应指向 `dd570e7`；不应把已有 ZIP 关联到后续 `master` 提交。

## 1. 发布资产核对

| 资产 | 本地路径 | SHA-256 | 核对结果 |
|---|---|---|---|
| macOS arm64 测试包 | `release-artifacts/ModelForge-macOS-0.1.1-beta.1.zip` | `981b8622bf9a31a4bf0b2d8ae6b08754544b9d834eb320f55a58fe1864557718` | 与 `checksums.txt` 一致 |
| 校验文件 | `release-artifacts/checksums.txt` | 见上行 | 已包含 ZIP 的 SHA-256 |
| Release Notes | `release-artifacts/TEST_RELEASE_NOTES.md` | 不适用 | 已准备为 GitHub Pre-release 正文 |

此外，ZIP 内 `ModelForge.app/Contents/Info.plist` 的 `CFBundleShortVersionString` 与 `CFBundleVersion` 均为 `0.1.1-beta.1`。GitHub 仓库当前没有同名标签，也没有任何既有 Release。

## 2. 本次测试版范围

本资产面向 **macOS arm64** 测试。它包含桌面端更新后的工作区、统一 Models 管理、OpenAI 兼容远程模型配置、Responses 与 Chat Completions 适配、简体中文默认界面及中英日运行时切换。API Key 仅由后端加密保存，客户端不会回显密钥。

此次发布不包含 Windows 或 Linux 安装包，也不捆绑本地模型、训练数据或任何 API Key。测试包用于手动验收，不会在安装或首次启动时自动下载模型、创建 Agent Run 或启动训练。

## 3. 发布前人工检查

| 检查项 | 通过条件 | 当前状态 |
|---|---|---|
| 哈希校验 | `shasum -a 256` 与表中值一致 | 已完成 |
| 包版本 | `Info.plist` 显示 `0.1.1-beta.1` | 已完成 |
| 代码标签 | 标签指向 `dd570e7` | 待创建 |
| GitHub Release | 新建且标记为 Pre-release | 待用户确认 |
| macOS 安装 smoke | 启动、登录、Models、远程提供商与语言切换通过 | 待人工执行 |
| 签名与公证 | 如需减少 Gatekeeper 警告则完成签名/公证 | 不在本测试版范围 |

## 4. 发布后的验收步骤

测试者应从 GitHub Release 下载 ZIP 与 `checksums.txt`，然后执行：

```bash
shasum -a 256 ModelForge-macOS-0.1.1-beta.1.zip
unzip ModelForge-macOS-0.1.1-beta.1.zip
open ModelForge.app
```

随后应依次验证登录、无模型时的配置引导、添加或验证一个远程模型提供商、默认模型切换、中文/英文/日文切换，以及 Agent 定义创建。Agent 创建不应自动创建或启动 Run；如验证出现失败，应提交操作系统版本、应用版本、复现步骤和已脱敏日志。

## 5. GitHub 发布操作（需用户确认）

以下命令会在 GitHub 上创建对外可见的 Pre-release 并上传资产。因此，只有在用户明确回复同意后才可执行：

```bash
gh release create v0.1.1-beta.1 \
  --repo yanzhao77/ModelForge \
  --target dd570e79d82dc13679af55e0e1af473f4d53df61 \
  --title "ModelForge v0.1.1-beta.1" \
  --notes-file release-artifacts/TEST_RELEASE_NOTES.md \
  --prerelease \
  release-artifacts/ModelForge-macOS-0.1.1-beta.1.zip \
  release-artifacts/checksums.txt
```

发布后应立即检查 Release 页面显示为 **Pre-release**，确认仅上传了 macOS ZIP 与校验文件，并使用新建标签下载后再次复核 SHA-256。若 GitHub 自动生成的标签目标与上表不一致，应停止发布并处理标签归属问题。

## 6. 已知限制与后续门槛

此包未签名、未公证；首次打开时 macOS 可能显示 Gatekeeper 警告。Windows/Linux 原生安装、CPU 本地模型 smoke、NVIDIA GPU smoke 和真实训练均未作为本 Pre-release 的通过条件。详细外部环境要求见 [EXTERNAL_RELEASE_VALIDATION.md](EXTERNAL_RELEASE_VALIDATION.md)。
