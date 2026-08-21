# 真实 AI 运行验证说明

ModelForge 的常规 CI 不安装 `requirements-ai.txt`，也不会下载模型、训练模型或伪造 GPU 可用性。本说明定义两个**显式触发**的验证入口：CPU 真实推理与 NVIDIA GPU Tensor 冒烟。

| 验证 | 入口 | 必需环境 | 自动行为 |
|---|---|---|---|
| CPU 真实推理 | `ModelForge CPU AI Smoke` 手动工作流 | 自托管 CPU Runner、预置本地 Transformers 模型目录 | 仅本地加载与一次前向推理，不下载模型 |
| NVIDIA GPU | `ModelForge GPU Smoke` 手动或每周工作流 | 带 `self-hosted`、`linux`、`nvidia-gpu` 标签的 NVIDIA Runner | 执行 `nvidia-smi` 与 CUDA Tensor 往返，不训练 |

## CPU 手动验证

在已安装可选 AI 依赖且已存在本地模型目录的机器上运行：

```bash
MODELFORGE_CPU_SMOKE_MODEL=/absolute/path/to/model \
pytest tests/test_hardware_cpu.py -q -m real_model
```

工作流版本要求在触发时填写同一绝对路径。路径必须对自托管 Runner 可读；测试使用 `local_files_only=True`，网络不可用或模型不存在时会失败或跳过，而不是尝试下载。

## 发布包准备

`scripts/build_desktop_macos_test.sh`、`scripts/build_desktop_linux_test.sh` 和 `scripts/build_desktop_windows_test.ps1` 都只生成本地 ZIP 与 SHA-256 记录，绝不上传或发布。Windows/Linux 脚本应只在相应原生平台上构建与安装验证；macOS 正式发布仍需 Developer ID 签名和公证。
