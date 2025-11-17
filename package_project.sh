#!/bin/bash
# ModelForge 2.0 项目打包脚本

echo "开始打包 ModelForge 2.0 项目..."

# 创建发布目录
RELEASE_DIR="ModelForge_v2.0_Release"
rm -rf $RELEASE_DIR
mkdir -p $RELEASE_DIR

# 复制核心文件
echo "复制核心文件..."
cp -r gui $RELEASE_DIR/
cp -r database $RELEASE_DIR/
cp -r models $RELEASE_DIR/
cp -r api $RELEASE_DIR/
cp -r pytorch $RELEASE_DIR/
cp -r common $RELEASE_DIR/
cp -r interface $RELEASE_DIR/
cp -r test $RELEASE_DIR/

# 复制主程序
cp main_session.py $RELEASE_DIR/
cp main.py $RELEASE_DIR/

# 复制文档
echo "复制文档..."
cp README_NEW.md $RELEASE_DIR/README.md
cp QUICKSTART.md $RELEASE_DIR/
cp USAGE_GUIDE.md $RELEASE_DIR/
cp CHANGELOG.md $RELEASE_DIR/
cp PROJECT_SUMMARY.md $RELEASE_DIR/
cp ANALYSIS.md $RELEASE_DIR/

# 复制配置文件
cp requirements_new.txt $RELEASE_DIR/requirements.txt

# 创建 .gitignore
cat > $RELEASE_DIR/.gitignore << 'GITIGNORE'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# 数据库
*.db
*.sqlite
*.sqlite3

# IDE
.vscode/
.idea/
*.swp
*.swo

# 系统文件
.DS_Store
Thumbs.db

# 日志
*.log
log/

# 模型文件
*.gguf
*.safetensors
*.bin
models/

# 用户数据
.modelforge/
GITIGNORE

# 创建启动脚本
cat > $RELEASE_DIR/start.sh << 'STARTSH'
#!/bin/bash
# ModelForge 启动脚本

echo "启动 ModelForge 2.0..."

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "检查依赖..."
pip install -q sqlalchemy pyjwt PySide6

# 启动应用
python main_session.py
STARTSH

chmod +x $RELEASE_DIR/start.sh

# 创建 Windows 启动脚本
cat > $RELEASE_DIR/start.bat << 'STARTBAT'
@echo off
echo Starting ModelForge 2.0...

REM Check virtual environment
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Checking dependencies...
pip install -q sqlalchemy pyjwt PySide6

REM Start application
python main_session.py
STARTBAT

echo "打包完成！"
echo "发布目录: $RELEASE_DIR"
echo ""
echo "文件列表:"
ls -lh $RELEASE_DIR/
