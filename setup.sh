#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== 抖音视频分析工具 - 环境部署 ==="

# 1. 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "[1/4] 创建虚拟环境..."
    python3 -m venv .venv
else
    echo "[1/4] 虚拟环境已存在，跳过"
fi

# 2. 激活并安装依赖
echo "[2/4] 安装 Python 依赖..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# 3. 检查系统依赖
echo "[3/4] 检查系统依赖..."
missing=""
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"

if [ -n "$missing" ]; then
    echo "  缺少系统依赖:$missing"
    echo "  请手动安装:"
    echo "    macOS:   brew install$missing"
    echo "    Ubuntu:  sudo apt install -y$missing"
    exit 1
fi
echo "  ffmpeg: $(ffmpeg -version 2>&1 | head -1)"

# 4. 下载 whisper 模型（首次会自动下载，这里预热）
echo "[4/4] 预载 whisper small 模型（首次约 500MB）..."
.venv/bin/python3 -c "
from faster_whisper import WhisperModel
print('  加载模型中...')
m = WhisperModel('small', device='cpu', compute_type='int8')
print('  模型就绪')
" 2>&1 | grep -v "^$"

echo ""
echo "=== 部署完成 ==="
echo ""
echo "使用方法:"
echo "  1. 确保 config.yaml 和 cookies.txt 已配置"
echo "  2. 运行:"
echo "     .venv/bin/python3 main.py \"https://www.douyin.com/video/VIDEO_ID\""
echo "     .venv/bin/python3 main.py \"https://www.douyin.com/user/SEC_UID\" -n 3"
echo ""
echo "  或使用快捷脚本:"
echo "     ./run.sh \"https://www.douyin.com/video/VIDEO_ID\""
