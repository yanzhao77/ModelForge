# ModelForge 外部环境验证与 Beta 发布执行清单

**适用版本：** `master`（0.1.1-beta.1 发布验证与 0.1.2 后续迭代）  
**原则：** 本清单中的模型下载、真实推理、训练、GPU 作业和 GitHub Release 创建均须由用户或已获明确授权的发布负责人显式启动。客户端和 CI 不得因检查本清单而自动执行这些动作。

> 本地质量门禁与 GitHub `ModelForge CI #24` 已通过；该结论只覆盖静态检查、依赖审计、测试、桌面离屏验证和 Docker 健康检查。它不等同于真实模型推理、GPU、Windows/Linux 安装、代码签名或 GitHub Release 已验证。

## 1. 当前状态与发布边界

| 范围 | 当前状态 | 发布前缺口 |
|---|---|---|
| macOS arm64 测试包 | 已生成 `ModelForge-macOS-0.1.1-beta.1.zip`、`checksums.txt` 与测试说明 | 需要人工安装 smoke；尚未签名/公证 |
| Windows 测试包 | `build_desktop_windows_test.ps1` 已就绪 | 必须在原生 Windows 构建、校验、安装并启动 |
| Linux 测试包 | `build_desktop_linux_test.sh` 已就绪 | 必须在原生 Linux 构建、校验、安装并启动 |
| CPU AI smoke | 工作流和 opt-in 测试已就绪 | 需要自托管 Runner 与明确的预置本地模型路径 |
| GPU smoke | 工作流已手动触发且排队 | 需要带 `self-hosted`、`linux`、`nvidia-gpu` 标签的在线 NVIDIA Runner |
| GitHub Pre-release | 尚未创建 | 需要用户确认标签、测试资产和 Release Notes 内容 |

## 2. Windows 原生构建与安装验证

在 Windows 11 x64 机器上，使用 PowerShell 打开仓库根目录后执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\scripts\build_desktop_windows_test.ps1 -Version 0.1.1-beta.1
Get-FileHash .\release-artifacts\ModelForge-Windows-0.1.1-beta.1.zip -Algorithm SHA256
```

解压生成的 ZIP 后，应完成下表中的人工 smoke。若任一项失败，不应创建 GitHub Release。

| 验证项 | 通过条件 |
|---|---|
| 启动 | 应用可启动，且未出现 Qt 平台插件或 DLL 缺失错误 |
| 登录 | 可访问后端；认证失败时显示可恢复错误且不泄露 Token |
| 模型就绪 | 无模型时显示配置引导；配置一个已验证远程模型或本地模型后进入 `READY` |
| Agent | 创建定义仅写入定义；不会自动创建或启动 Run；可选择历史 Run 并回放 |
| 关闭/恢复 | 关闭后重开，非敏感向导进度可以恢复，API Key 不回显 |

## 3. Linux 原生构建与安装验证

在与目标发行版匹配的 Linux x86_64 环境中执行：

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
bash scripts/build_desktop_linux_test.sh --version 0.1.1-beta.1
sha256sum release-artifacts/ModelForge-Linux-0.1.1-beta.1.zip
```

解压后以 `QT_QPA_PLATFORM=offscreen` 完成最小启动预检，再在带显示服务的桌面会话完成与 Windows 相同的五项人工 smoke。应记录发行版、桌面环境、Python 版本、Qt 版本与校验值。

## 4. CPU AI smoke（显式触发）

CPU Runner 必须是受控自托管环境，并预置一个**已批准的、固定 revision 的小型本地模型**。工作流只读取 `MODELFORGE_CPU_MODEL_PATH`，不会下载模型；模型所有者应提前确认其许可证、磁盘占用和访问权限。

| 前置条件 | 验收要求 |
|---|---|
| Runner 标签 | `self-hosted`、`linux`、`cpu-ai` |
| 模型路径 | `MODELFORGE_CPU_MODEL_PATH` 指向可读的本地模型；路径不提交到仓库 |
| 资源限制 | 记录 CPU、内存、超时和缓存上限；默认仅执行最小推理 smoke |
| 触发方式 | 由用户在 Actions 页面手动运行 `ModelForge CPU AI Smoke` |
| 训练 | 默认不执行；若要验证训练，必须另行确认模型、数据集、最长时长和磁盘上限 |

## 5. GPU smoke（显式触发）

当前 GPU Smoke 处于排队状态，原因是没有匹配的 Runner。为避免伪造 GPU 通过，只有在下列检查完成后才应让该工作流执行。

```bash
nvidia-smi
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"
```

| 前置条件 | 验收要求 |
|---|---|
| Runner 标签 | `self-hosted`、`linux`、`nvidia-gpu` |
| 驱动与 CUDA | `nvidia-smi` 正常，PyTorch 可见 CUDA，版本写入运行日志 |
| 模型与缓存 | 只使用批准的本地缓存或固定小模型；不在 smoke 内临时下载大模型 |
| 结果 | 工作流显示成功，日志包含 GPU 可见性与最小推理/硬件断言 |
| 失败处理 | 保留日志，不以 CPU 成功替代 GPU 通过；修复 Runner 后由用户再次手动触发 |

## 6. GitHub Pre-release 创建门槛

创建 `v0.1.1-beta.1` Pre-release 是对外发布操作，必须先获得用户的明确确认。发布负责人应在创建前逐项确认：

- `master` 指向已通过 CI 的提交，且本地工作区无未提交发布相关改动。
- macOS ZIP 的 SHA-256 与 `release-artifacts/checksums.txt` 一致。
- `TEST_RELEASE_NOTES.md` 明确标注测试版、macOS arm64、未签名/未公证、Windows/Linux 尚待验证、GPU 未验证等限制。
- 已决定是否把 Windows/Linux 未验证资产排除在该 Beta 之外；默认建议仅上传已验证的 macOS 资产。

建议上传的资产如下：

1. `ModelForge-macOS-0.1.1-beta.1.zip`
2. `checksums.txt`
3. `TEST_RELEASE_NOTES.md`

> 不应将未在原生系统完成安装 smoke 的 Windows/Linux 资产加入 Pre-release，也不应将“GPU 工作流排队”表述为 GPU 验证通过。

## 7. 记录模板

每次外部验证应在 Issue、Release 草稿或受控测试记录中写入：提交 SHA、日期、操作者、操作系统/Runner、硬件、模型标识（不写 API Key）、命令、校验值、结果、日志链接和已知限制。任何密钥、Token、认证头或加密密文均不得出现在记录中。
