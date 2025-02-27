# ModelForge
About Call local model for interaction and training
第一次提交：初始化界面完成，加载本地model进行交互
load_model按键可用，help下about可用，添加about信息

Nuitka打包命令
python -m nuitka --onefile --output-dir=build --mingw64 --standalone --module-parameter=torch-disable-jit=no --enable-plugin=pyqt6 --include-data-dir=.venv/Lib/site-packages/transformers=transformers --include-data-dir=.venv/Lib/site-packages/datasets=datasets --include-data-dir=.venv/Lib/site-packages/torch=torch --include-package=markdown --include-package=huggingface_hub --include-module=duckduckgo_search --windows-icon-from-ico=icon\logo.ico main.py
Nuitka-Options: Used command line options: --onefile --output-dir=build --standalone --mingw64  --windows-console-mode=disable --enable-plugin=pyqt6 --include-data-dir=.venv/Lib/site-packages/transformers=transformers
Nuitka-Options: --include-data-dir=.venv/Lib/site-packages/datasets=datasets --include-data-dir=.venv/Lib/site-packages/torch=torch --include-package=markdown --include-package=huggingface_hub --include-module=duckduckgo_search 
Nuitka-Options: --windows-icon-from-ico=C:\workspace\pythonDownloads\ModelForge\icon\logo.ico main.py
Nuitka-Plugins:pyqt6: Support for PyQt6 is not perfect, e.g. Qt threading does not work, so prefer PySide6 if you can.
Nuitka: Starting Python compilation with Nuitka '2.6.7' on Python (flavor CPython Official), '3.11' commercial grade 'not installed'.
Nuitka-Plugins:WARNING: options-nanny: Module has parameter: Torch JIT is disabled by default in standalone mode, make a choice explicit with '--module-parameter=torch-disable-jit=yes|no'

conda打包命令
# conda create -n modelForge python=3.10
# conda activate modelForge
# Pyinstaller -F -w -i C:\workspace\pythonDownloads\ModelForge\icon\logo.ico main.py

