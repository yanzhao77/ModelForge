# ModelForge v0.1.2 跨平台构建与签名验证开发计划

**状态：** 规划稿，尚未申请或配置任何证书、私钥、签名服务或发布密钥。  
**范围：** Windows x64 与 Linux x86_64 桌面端的原生构建、签名、验证、CI 和 Release 准备。  
**非范围：** 自动创建 Release、自动下载模型、真实训练、CPU/GPU 推理验证，以及 macOS 公证；它们保留在独立的外部验证清单中。

> 本计划将“构建”和“签名”分离：无凭据的构建作业只产生可复核的候选资产；带签名凭据的受保护作业只对已验证的精确输入进行签名。私钥永不写入仓库、日志、普通 CI 缓存或公开构建产物。

## 1. 目标与 v0.1.2 交付边界

| 平台 | v0.1.2 必交付资产 | 签名方式 | 最低支持范围 | 发布前验证 |
|---|---|---|---|---|
| Windows | `ModelForge-windows-x64-<version>.zip` 与 `ModelForge-Setup-<version>.exe` | Authenticode + RFC 3161 时间戳 | Windows 10/11 x64 | 干净 Windows 11 VM：签名、哈希、安装、启动、登录和核心工作区 smoke |
| Linux | `ModelForge-<version>-x86_64.AppImage` 与 Ubuntu 22.04+ `.deb` | GPG 内嵌/分离签名、发布公钥与 SHA-256 | Ubuntu 22.04/24.04 x86_64；AppImage 为通用分发 | 干净 Ubuntu 22.04 与 24.04 环境：签名、哈希、安装/运行和核心工作区 smoke |
| 公共材料 | `checksums.txt`、SBOM、构建来源记录和签名验证说明 | SHA-256 + 发布者公钥/证书链 | 所有下载者 | 第三方下载后独立重算/验证 |

现有 ZIP 测试脚本继续用于开发者本地快速验证；v0.1.2 不应把 ZIP 本身误当作 Windows Authenticode 签名对象。Windows 要对可执行文件、安装器和包含的可执行依赖进行签名并验证；Linux 要同时提供可验证的签名和公钥指纹。

## 2. 基础工程改造

### 2.1 版本、命名与来源

在 `client/pyside6/version.py` 将版本提升至 `0.1.2` 后，所有平台构建脚本从该文件读取唯一版本号。新增 `release-manifest.json`，至少包含：版本、Git tag、完整提交 SHA、构建 UTC 时间、Python/PyInstaller/Qt 版本、目标 OS/架构、产物文件名、SHA-256、SBOM 路径与签名状态。

构建在干净工作树中只允许以下两种输入：受保护 tag 对应的提交，或 CI 显式传入的完整 SHA。每个产物名必须包含版本和平台/架构，禁止覆盖同名历史资产。`checksums.txt` 由单一任务重建而非使用追加模式，以避免重复或残留的哈希条目。

### 2.2 可复现与供应链基线

在开始签名前，将 Python 构建依赖锁定为带哈希的受审计集合，并记录 `pip freeze`、PyInstaller 版本、Qt 版本和操作系统镜像版本。构建任务必须设置 `SOURCE_DATE_EPOCH` 为 tag 提交时间；若 PyInstaller 仍产生不可完全字节复现的二进制，应比较文件清单、签名输入哈希、SBOM 和运行行为，并在 manifest 中声明“可追溯构建”而非声称字节级可复现。

每个平台生成 CycloneDX 或 SPDX SBOM，并把 SBOM 的 SHA-256 写入 release manifest。构建、测试、签名、验证和上传分别输出机器可读 JSON 日志；日志只能含版本、哈希、签名结果和公钥指纹，不能含密码、PFX、Token、私钥或认证头。

## 3. Windows 构建与 Authenticode 签名

### 3.1 运行器与构建产物

使用受控 Windows 11 x64 Runner。无签名构建可在受控 GitHub-hosted Windows Runner 上运行；含证书的签名必须在隔离的自托管 Windows 签名 Runner 或受管理的云 HSM/签名服务上执行。Runner 需要 Python 3.11、固定 PyInstaller 版本、Windows SDK 的 `signtool.exe`、Inno Setup（或最终选定的安装器工具）和 PowerShell 7。

将现有 `build_desktop_windows_test.ps1` 重构为以下非交互步骤：建立干净虚拟环境；执行 PyInstaller；生成便携 ZIP；生成安装器；写入 release manifest；计算 SHA-256；执行未签名的离屏启动测试。安装器脚本必须写明应用标识、版本、升级行为、卸载入口、用户数据保留策略和安装范围（默认每用户，除非另行批准）。

### 3.2 证书与密钥方案

首选使用组织实名的 OV/EV 代码签名证书，并将私钥保存在硬件令牌、Azure Key Vault/Managed HSM 或等价的受管理签名服务中。若选择 PFX，PFX 只能位于受保护签名环境的短期秘密存储中，必须设置强密码、最小权限、轮换期和撤销流程；它不能作为普通 GitHub Secret 长期导出或写入构建日志。

在签名开始前，产品负责人须确认发布者法定名称、证书类型、证书供应商、时间戳服务、证书到期日和密钥托管方式。EV/硬件令牌、Trusted Signing 或云 HSM 的具体接入方式不同，不能在未取得相应账户和法律主体资料时假设可自动配置。

### 3.3 签名、时间戳与验证

Windows SDK 的 SignTool 需要在签名时明确指定文件摘要 `/fd` 和时间戳摘要 `/td`；Microsoft 建议使用 SHA-256。[1] 签名任务应对主程序、可执行的辅助程序、安装器和需要 Windows 代码完整性验证的 DLL/EXE 逐项签名。示例命令如下，其中证书选择与时间戳 URL 必须由受保护环境提供：

```powershell
signtool sign /fd SHA256 /tr $env:TIMESTAMP_RFC3161_URL /td SHA256 \
  /sha $env:CODESIGN_CERT_THUMBPRINT .\dist\ModelForge\ModelForge.exe
signtool sign /fd SHA256 /tr $env:TIMESTAMP_RFC3161_URL /td SHA256 \
  /sha $env:CODESIGN_CERT_THUMBPRINT .\release\ModelForge-Setup-0.1.2.exe
signtool verify /pa /all /v .\dist\ModelForge\ModelForge.exe
signtool verify /pa /all /v .\release\ModelForge-Setup-0.1.2.exe
```

`signtool verify` 会检查签名信任、吊销状态及可选策略；验证结果必须作为发布门槛保存。[1] 时间戳验证、发布者名称匹配和 SHA-256 重算均为必经步骤。SmartScreen 具有声誉维度，即使签名有效，新的发布者或新文件仍可能显示下载/运行提示；计划不得把“无 SmartScreen 提示”作为可自动保证的验收条件。[2]

### 3.4 Windows 安装 smoke

在未安装 Python、未安装源代码、未使用开发者证书缓存的干净 Windows 11 VM 中执行：验证签名；重算 ZIP 与安装器哈希；安装；启动；登录；检查无模型引导；验证远程提供商；切换默认模型和三语言；创建 Agent 定义但不启动 Run；卸载并确认用户数据策略。测试记录必须包含 Windows build、证书主题/指纹（不含私钥）、时间戳、应用版本、SHA-256 和已脱敏日志。

## 4. Linux 构建与 GPG 验证

### 4.1 分发格式与兼容策略

v0.1.2 推荐采用“**AppImage + Debian 包**”双轨：AppImage 面向通用 x86_64 下载者，`.deb` 面向 Ubuntu 22.04/24.04 的原生安装体验。已有 Linux ZIP 仅保留为开发者调试产物，不作为对外主分发格式。RPM、Flatpak 和 APT 仓库属于后续版本候选，不应在 v0.1.2 无验证基础设施时并入首发范围。

Linux 构建基线固定在 Ubuntu 22.04 x86_64 容器/Runner，并在 Ubuntu 24.04 进行兼容验证。AppImage 使用 AppDir 元数据、桌面文件、图标和启动器打包；`.deb` 使用明确的包名、版本、架构、依赖、桌面入口和卸载语义。每种格式必须从同一受保护 tag 构建，使用同一 release manifest 中记录的 SHA-256。

### 4.2 GPG 密钥与签名策略

创建专用发布 GPG 子密钥，离线保管主密钥；发布子密钥放在硬件令牌或受控签名主机。公开 GPG 公钥、完整 fingerprint、到期日、撤销证书位置和轮换政策。私钥不得导入普通 GitHub-hosted Runner；受保护 Linux 签名 Runner 使用 `gpg-agent`、硬件令牌或受控短期密钥会话完成签名。

AppImage 规范支持在创建时通过配置好的 `gpg/gpg2` 使用 `appimagetool --sign` 内嵌签名；验证需要独立于 AppImage 的外部工具。[3] 除内嵌签名外，仍应生成 `*.asc` 分离签名与 `checksums.txt`，以便下载者先验证文件。对于 `.deb`，v0.1.2 至少提供 detached GPG 签名和 SHA-256；当引入 APT 仓库时，签名应迁移到仓库 `Release` 元数据并通过用户安装的 keyring 验证。

### 4.3 Linux 构建与验证命令

```bash
# 受保护签名环境：AppImage 内嵌签名
appimagetool-x86_64.AppImage ModelForge.AppDir --sign

# 对公开资产生成分离签名和哈希
gpg --batch --armor --detach-sign ModelForge-0.1.2-x86_64.AppImage
gpg --batch --armor --detach-sign model-forge_0.1.2_amd64.deb
sha256sum ModelForge-0.1.2-x86_64.AppImage model-forge_0.1.2_amd64.deb > checksums.txt

# 消费端：先导入经过独立确认的公钥 fingerprint，再验证
gpg --verify ModelForge-0.1.2-x86_64.AppImage.asc ModelForge-0.1.2-x86_64.AppImage
sha256sum -c checksums.txt
./validate ModelForge-0.1.2-x86_64.AppImage
```

AppImage 官方文档说明，`--appimage-signature` 只能显示签名，不会验证其有效性；需要外部验证工具验证签名。[3] 因此 v0.1.2 Release Notes 必须提供公钥 fingerprint、`gpg --verify` 示例和外部 `validate` 工具说明。

### 4.4 Linux 安装 smoke

在干净 Ubuntu 22.04 与 24.04 VM/容器中分别执行 GPG 与 SHA-256 验证。AppImage 必须能够显示版本、启动并通过核心工作区 smoke；`.deb` 需要通过 `dpkg -i` 安装、依赖修复、菜单/启动器检查、升级/卸载和用户数据策略检查。任何 glibc、FUSE、Qt 插件或 Wayland/X11 兼容问题都必须被记录为阻塞问题，而不是在 Release Notes 中模糊声明“Linux 支持”。

## 5. CI/CD 与环境分层

| 作业 | Runner 与权限 | 输入 | 输出 | 失败即阻塞 |
|---|---|---|---|---|
| `desktop-build-windows` | 无签名 Windows x64 | 受保护 tag SHA | 未签名 ZIP、安装器、manifest、SBOM、哈希 | 是 |
| `desktop-test-windows` | 干净 Windows VM | 未签名或已签名资产 | 离屏/安装 smoke 日志 | 是 |
| `desktop-sign-windows` | 受保护签名 Runner | 已验证 SHA 的 Windows 资产 | 已签名资产、签名验证报告 | 是 |
| `desktop-build-linux` | Ubuntu 22.04 x86_64 | 同一 tag SHA | AppImage、`.deb`、manifest、SBOM、哈希 | 是 |
| `desktop-test-linux` | Ubuntu 22.04 + 24.04 | Linux 资产 | 安装/启动 smoke 日志 | 是 |
| `desktop-sign-linux` | 受保护 GPG Runner | 已验证 SHA 的 Linux 资产 | `asc`、内嵌签名、fingerprint 报告 | 是 |
| `release-verify` | 无私钥 Runner | 全部已签资产 | 交叉平台验收矩阵 | 是 |
| `release-publish` | GitHub Environment `release` | 审核通过的 manifest | Pre-release/Release 上传 | 是，且需要人工批准 |

签名和发布环境采用 GitHub Environments 的人工审批、最小权限和审计日志。无签名构建可以并行；签名和发布必须串行、绑定固定 SHA。所有 Runner 使用短生命周期工作目录，在作业结束后清理未签名二进制、临时证书缓存和 GPG agent 会话。

## 6. v0.1.2 分阶段实施顺序

| 阶段 | 工作内容 | 完成定义 |
|---|---|---|
| A：发布决策 | 确认 Windows 证书方案、发布者名称、时间戳服务；确认 Linux 发行格式和 GPG fingerprint | 决策记录获得负责人批准，未配置真实密钥 |
| B：构建标准化 | 重构现有 Windows/Linux 脚本，加入架构命名、干净输出、manifest、SBOM 和 checksum 重建 | 两平台无签名资产可由固定 tag 构建并通过离屏启动 |
| C：Windows 签名 | 配置受保护签名环境、签名安装器/二进制、`signtool verify` 和干净 VM smoke | 证书链、时间戳、签名验证和安装 smoke 全部通过 |
| D：Linux 签名 | 构建 AppImage/`.deb`、配置 GPG 发布子密钥、公钥与 detached/内嵌签名 | Ubuntu 22.04/24.04 验证签名、安装/启动/卸载通过 |
| E：发布自动化 | 编排受保护 CI、SBOM、来源记录、Release 草稿和人工批准 | 对候选 tag 生成可审阅的发布清单，不自动对外发布 |
| F：发布演练 | 在非生产 tag 完成端到端构建、签名、下载、第三方验证和回滚演练 | 演练记录无 P0/P1 问题，签名密钥未泄露 |

## 7. v0.1.2 发布门槛

只有当下列全部条件满足时，v0.1.2 才可从 Pre-release 升级为正式发布：Windows 和 Linux 构建均来自同一 tag；全部资产有 SHA-256、SBOM 和来源 manifest；Windows 安装器与可执行文件已通过 Authenticode、RFC 3161 时间戳和 `signtool verify`；Linux AppImage/`.deb` 已通过 GPG 与 SHA-256 验证；四个干净环境 smoke 均通过；CI、依赖审计、全量测试和 Docker 健康检查为绿色；Release Notes 含公钥/证书验证说明、兼容性、升级/卸载路径和已知限制；发布负责人在受保护环境中明确批准。

## 8. 需要用户确认的决策

| 决策 | 选项 | 建议 |
|---|---|---|
| Windows 证书 | EV/OV 证书 + 硬件令牌；云 HSM/Key Vault；受管 Trusted Signing | 优先云 HSM/受管签名，避免导出 PFX |
| Windows 分发 | 仅签名 ZIP；签名安装器 + ZIP；MSIX | v0.1.2 采用签名安装器 + ZIP，后续再评估 MSIX |
| Linux 格式 | 仅 AppImage；仅 `.deb`；AppImage + `.deb` | v0.1.2 采用 AppImage + Ubuntu `.deb` |
| Linux 密钥 | 软件 GPG 子密钥；硬件令牌；组织 HSM | 优先离线主密钥 + 硬件/受控发布子密钥 |
| CI Runner | 全部自托管；构建托管、签名自托管；全云受管签名 | 构建可托管，签名与发布受保护并最小权限 |
| 发布节奏 | 先跨平台 Pre-release；直接正式版 | 先进行带签名的 v0.1.2 Pre-release，再基于验收升级 |

## References

[1] [Microsoft Learn：SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)  
[2] [Microsoft Learn：SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)  
[3] [AppImage Documentation：Signing AppImages](https://docs.appimage.org/packaging-guide/optional/signatures.html)
