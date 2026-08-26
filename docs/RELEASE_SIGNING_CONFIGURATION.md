# v0.1.2 受保护签名配置说明

本文档为后续 Windows 与 Linux 发行签名提供**配置名称、职责边界和审批条件**。它不保存、展示或导出任何证书、私钥、口令或令牌；也不触发构建、签名、上传、发布或创建 Git tag。

## 1. 适用范围

当前 `v0.1.2-dev` 仅包含发行元数据、SBOM 和签名配置预检的准备接口。正式 `v0.1.2` 只能在应用版本号更新为正式版本、固定提交 SHA 的构建资产已经验证、跨平台安装验证完成且各项受保护审批获得批准后创建。

| 平台 | 签名目标 | 受保护变量名称 | 最小权限与使用边界 |
|---|---|---|---|
| Windows | Authenticode 代码签名与时间戳 | `MF_WINDOWS_SIGNING_CERT_BASE64`、`MF_WINDOWS_SIGNING_CERT_PASSWORD`、`MF_WINDOWS_TIMESTAMP_URL` | 仅允许受保护 Windows 签名作业读取；私有证书必须作为 GitHub Environment Secret 保存，时间戳地址可作为 Environment Variable 保存。 |
| Linux | GPG 签名与指纹校验 | `MF_LINUX_GPG_PRIVATE_KEY`、`MF_LINUX_GPG_KEY_FINGERPRINT`、`MF_LINUX_GPG_PASSPHRASE` | 仅允许受保护 Linux 签名作业读取；私钥与口令必须作为 GitHub Environment Secret 保存，作业只输出已验证的指纹与签名文件。 |

> `scripts/check_release_signing_env.py` 只能报告变量**名称**的已配置/缺失状态。它不得读取、打印、落盘或上传变量内容，且不应作为签名成功的证明。

## 2. GitHub Environment 保护要求

Windows 和 Linux 分别使用独立的受保护 GitHub Environment，例如 `release-signing-windows` 与 `release-signing-linux`。每个 Environment 应设置必需审阅者；签名作业必须最小化权限、固定到待发行 tag 对应的提交 SHA，并禁止来自未受信任 pull request 的访问。

| 控制项 | 要求 |
|---|---|
| 工作流权限 | 默认 `contents: read`；仅在需要上传已审核资产时，为对应单个作业临时授予最小范围的 `contents: write`。 |
| 审批 | 每个签名 Environment 都要求人工批准；未批准时不得访问任何签名 Secret。 |
| 来源约束 | 只允许受保护分支或固定 tag SHA 触发；不得通过浮动分支名、可变 URL 或外部 PR 输入定位资产。 |
| 日志 | 禁止使用 `set -x`、回显环境、上传证书或私钥；对签名失败仅报告非敏感原因与作业标识。 |
| 产物 | 签名前验证输入文件的 SHA-256；签名后上传签名、校验和与 SBOM，不上传私钥或原始凭据。 |

## 3. 人工配置顺序

首先由拥有证书或 GPG 私钥的授权人员，在对应 GitHub Environment 中保存变量。其次由发行负责人核对环境名称、必需审阅者和工作流分支限制。之后可在受控 Runner 上运行预检脚本，仅确认变量名称是否就绪。最后，在正式发行审批中将待签名资产 SHA-256、固定提交 SHA、SBOM 与安装验证记录一并审阅。

配置完成后，仍不能自动创建 Release 或正式 `v0.1.2` 标签。签名作业、资产上传及 GitHub Release 创建都必须由用户或发行负责人发起并显式批准。

## 4. 预检命令

预检不会展示任何秘密内容。命令以非零退出表示有必需变量缺失，供受保护流水线在签名前停止：

```bash
python scripts/check_release_signing_env.py windows
python scripts/check_release_signing_env.py linux
```

## 5. v0.1.2 正式发行门槛

| 门槛 | 责任人 | 证据 |
|---|---|---|
| 版本与 tag | 发行负责人 | 应用版本为 `0.1.2`；tag 固定指向已审阅的提交 SHA。 |
| Windows 签名 | Windows 签名审批人 | Authenticode 签名与时间戳验证记录。 |
| Linux 签名 | Linux 签名审批人 | GPG 指纹、签名文件与验证记录。 |
| 资产完整性 | 发行负责人 | SHA-256、SBOM 和来源提交 SHA 一致。 |
| 安装验证 | 平台验证人员 | Windows 与 Linux 原生安装和启动验证记录。 |
| 发布批准 | 用户或发行负责人 | 明确允许创建 GitHub Release 并上传对应资产。 |

在上述门槛未齐备前，开发标签 `v0.1.2-dev` 仅用于开发快照，不视为可分发的正式版本。
