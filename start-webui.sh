#!/bin/bash
# 启动入库前端。若已在运行则直接打开浏览器，不重复启动。
cd "$(dirname "$0")" || exit 1

PORT=8917
URL="http://127.0.0.1:${PORT}/"

# 端口已被占用 → 服务已在运行 → 只开浏览器
if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${PORT} "; then
    echo "服务已在运行，打开 $URL"
    command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" >/dev/null 2>&1 &
    exit 0
fi

# 检查 python
if ! command -v python3 >/dev/null 2>&1; then
    echo "错误: 找不到 python3"
    read -rp "按回车关闭…" _
    exit 1
fi

exec python3 webui/server.py
