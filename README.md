# ModelForge

ModelForge 是一个本地大模型推理与训练平台，支持多种模型格式（如 safetensors、gguf），可通过 PySide6 图形界面与模型交互，支持在线搜索增强、模型性能监控等功能。适合 AI 开发者和研究者在本地环境下高效调用和微调大模型。

## 主要特性

- 支持 HuggingFace Transformers 格式（safetensors）和 llama-cpp-python 格式（gguf）模型加载与推理
- 自动识别模型格式，智能选择推理后端
- PySide6 图形界面，支持启动过渡动画
- 支持在线搜索增强（Web Search）
- 性能监控与日志输出
- 支持 Windows 平台一键打包（Nuitka/pyinstaller）
- 代码结构清晰，便于二次开发

## 安装与环境

建议使用 Conda 环境：

```bash
conda create -n modelForge python=3.10
conda activate modelForge
pip install -r requirements.txt
```

## 运行方式

```bash
python main.py
```

## 打包说明

### Nuitka 打包

```bash
python -m nuitka --onefile --output-dir=build --mingw64 --standalone --module-parameter=torch-disable-jit=no --enable-plugin=pyqt6 --include-data-dir=.venv/Lib/site-packages/transformers=transformers --include-data-dir=.venv/Lib/site-packages/datasets=datasets --include-data-dir=.venv/Lib/site-packages/torch=torch --include-package=markdown --include-package=huggingface_hub --include-module=duckduckgo_search --windows-icon-from-ico=icon\logo.ico main.py
```

### PyInstaller 打包

```bash
pyinstaller -F -w -i icon\logo.ico main.py
```

## 依赖

- Python 3.10+
- PySide6
- torch
- transformers
- llama-cpp-python（可选，支持gguf模型）
- 其他依赖见 requirements.txt

## 目录结构

```
ModelForge3/
├── main.py                # 程序入口，界面与过渡动画
├── gui/                   # 图形界面相关代码
├── pytorch/
│   ├── model_generate.py  # 模型加载与推理主逻辑
│   ├── base_generate.py   # 推理基类
│   └── webSearcher.py     # 在线搜索增强
├── common/
│   └── const/
│       └── common_const.py # 常量配置
├── icon/                  # 图标资源
├── requirements.txt
└── README.md
```

## 常见问题

- **模型加载失败？**  
  请确认模型路径和格式，gguf模型需安装 llama-cpp-python。

- **打包后启动闪退？**  
  请检查依赖完整性，或以命令行方式运行查看报错信息。

## 许可证

本项目仅供学习与研究使用，禁止用于商业用途