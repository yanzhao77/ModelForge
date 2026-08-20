# 桌面客户端 GitHub Release 更新规范

桌面客户端通过 GitHub Release API 检查更新，且不会自动替换正在运行的应用。

| 资产 | 必需 | 说明 |
|---|---:|---|
| 含 `macOS` 的 `.dmg` 或 `.zip` 安装包 | 是 | 供 macOS 客户端安装。 |
| `checksums.txt` | 是 | 每行格式：`<sha256>  <asset-name>`。 |

客户端仅在发现更高版本、安装包和校验文件齐备时才允许下载。下载后的资产被写入 `~/Library/Application Support/ModelForge/updates/` 并完成 SHA-256 校验；随后由用户确认是否打开已验证的安装包。
