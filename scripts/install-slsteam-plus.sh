#!/bin/bash
# 安装 SLSsteam-Plus（用现成的 .so 文件）
# 用法: bash scripts/install-slsteam-plus.sh <SLSsteam.so路径> [library-inject.so路径]
set -e
SLSDIR="$HOME/.local/share/SLSsteam"

if [ $# -lt 1 ]; then
    echo "用法: $0 <SLSsteam.so路径> [library-inject.so路径]"
    echo
    echo "获取 .so 的三种方式:"
    echo "  1. 从本仓库的 Release 下载"
    echo "  2. 从上游下载: https://github.com/Hintay/SLSsteam-Plus/releases"
    echo "  3. 自己编译: bash scripts/build-slsteam-plus.sh"
    exit 1
fi

SO="$1"
INJ="${2:-}"

[ -f "$SO" ] || { echo "✗ 文件不存在: $SO"; exit 1; }

echo "== 安装 SLSsteam-Plus =="
mkdir -p "$SLSDIR"

# 备份旧的
if [ -s "$SLSDIR/SLSsteam.so" ]; then
    ts=$(date +%Y%m%d-%H%M%S)
    cp "$SLSDIR/SLSsteam.so" "$SLSDIR/SLSsteam.so.$ts.bak"
    echo "  ✓ 已备份旧库 → SLSsteam.so.$ts.bak"
fi

# 安装主库
cp "$SO" "$SLSDIR/SLSsteam.so"
chmod 755 "$SLSDIR/SLSsteam.so"
echo "  ✓ SLSsteam.so ($(stat -c%s "$SLSDIR/SLSsteam.so") 字节)"

# 安装注入器
if [ -n "$INJ" ] && [ -f "$INJ" ]; then
    cp "$INJ" "$SLSDIR/library-inject.so"
    echo "  ✓ library-inject.so ($(stat -c%s "$SLSDIR/library-inject.so") 字节)"
elif [ ! -s "$SLSDIR/library-inject.so" ]; then
    echo "  ⚠ 没有 library-inject.so —— 只装主库可能不够"
    echo "    请把 library-inject.so 也传进来作为第二个参数"
fi

# 启动器
mkdir -p "$SLSDIR/path"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/launcher.sh" ]; then
    cp "$SCRIPT_DIR/launcher.sh" "$SLSDIR/path/steam"
    chmod +x "$SLSDIR/path/steam"
    mkdir -p "$HOME/.local/bin"
    cp "$SCRIPT_DIR/launcher.sh" "$HOME/.local/bin/steam"
    chmod +x "$HOME/.local/bin/steam"
    echo "  ✓ 启动器已安装"
fi
printf '#!/bin/sh\nexec /usr/bin/steam "$@"\n' > "$HOME/.local/bin/steam-noinject"
chmod +x "$HOME/.local/bin/steam-noinject"
echo "  ✓ 安全网: ~/.local/bin/steam-noinject"

echo
echo "== 验证 =="
file "$SLSDIR/SLSsteam.so" | sed 's/^/  /'
ldd "$SLSDIR/SLSsteam.so" 2>/dev/null | grep "not found" && echo "  ⚠ 有缺失依赖！" || echo "  ✓ 依赖完整"
nm -D "$SLSDIR/SLSsteam.so" 2>/dev/null | grep -c "la_" | xargs -I{} echo "  ✓ LD_AUDIT 符号: {} 个"

echo
echo "完成！重启 Steam 生效："
echo "  ~/.local/share/SLSsteam/path/steam"
