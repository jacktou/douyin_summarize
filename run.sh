#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "虚拟环境未创建，请先运行: bash setup.sh"
    exit 1
fi

.venv/bin/python3 main.py "$@"
