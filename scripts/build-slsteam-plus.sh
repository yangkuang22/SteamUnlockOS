#!/bin/bash
# ============================================================
# 从源码编译 SLSsteam-Plus（SteamOS 上原本编译不了，本脚本自动搞定）
#
# 它做的事:
#   1. 从 Arch 仓库提取 32 位开发环境（SteamOS 缺这个，不需要 sudo）
#   2. 克隆 SLSsteam-Plus 源码
#   3. 打上必要的补丁（4 条失效特征码 + GCC 15 兼容）
#   4. 编译并安装
# ============================================================
set -e
BUILD_DIR="${BUILD_DIR:-$HOME/slsplus-build}"
TOOLS_DIR="$HOME/steam-toolkit/buildtools"
ARCH_MIRROR="${ARCH_MIRROR:-https://geo.mirror.pkgbuild.com}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================="
echo " 编译 SLSsteam-Plus (SteamOS)"
echo "=============================================="
echo

echo "[1/5] 检查构建环境..."
need_tools=0
[ -x "$TOOLS_DIR/wrappers/cmake" ] || need_tools=1
[ -f "$TOOLS_DIR/usr/include/gnu/stubs-32.h" ] || need_tools=1

pick() {
    python3 - "$1" <<'PYEOF'
import tarfile, re, sys
want = sys.argv[1]
for repo in ("core", "extra"):
    try:
        t = tarfile.open(repo + ".db", "r:*")
    except Exception:
        continue
    for m in t.getmembers():
        if not m.name.endswith("/desc"):
            continue
        base = m.name.split("/")[0]
        if re.match(r'^' + re.escape(want) + r'-[0-9]', base):
            d = t.extractfile(m).read().decode('utf-8', 'replace')
            fn = re.search(r'%FILENAME%\n(\S+)', d)
            if fn:
                print(repo + "\t" + fn.group(1))
                t.close()
                sys.exit(0)
    t.close()
PYEOF
}

if [ "$need_tools" = "1" ]; then
    echo "  从 Arch 仓库提取 32 位工具链（装到 $TOOLS_DIR，不需要 sudo）"
    mkdir -p "$TOOLS_DIR"
    WORK=$(mktemp -d)
    cd "$WORK"
    echo "  获取包数据库..."
    curl -fsSL "$ARCH_MIRROR/core/os/x86_64/core.db" -o core.db
    curl -fsSL "$ARCH_MIRROR/extra/os/x86_64/extra.db" -o extra.db

    for pkg in cmake pkgconf jsoncpp rhash libuv cppdap lib32-glibc openssl curl; do
        [ -f "$TOOLS_DIR/.done-$pkg" ] && { echo "    ✓ $pkg"; continue; }
        spec=$(pick "$pkg")
        if [ -z "$spec" ]; then echo "    ⚠ 找不到 $pkg"; continue; fi
        repo="${spec%%	*}"
        fname="${spec##*	}"
        echo "    下载 $pkg ($repo)..."
        if curl -fsSL "$ARCH_MIRROR/$repo/os/x86_64/$fname" -o "$fname"; then
            tar --zstd -xf "$fname" -C "$TOOLS_DIR" 2>/dev/null || tar -xf "$fname" -C "$TOOLS_DIR" 2>/dev/null || true
            touch "$TOOLS_DIR/.done-$pkg"
        fi
    done
    cd "$HOME"
    rm -rf "$WORK"

    mkdir -p "$TOOLS_DIR/wrappers"
    for t in cmake pkg-config; do
        printf '#!/bin/sh\nexport LD_LIBRARY_PATH=%s/usr/lib:$LD_LIBRARY_PATH\nexport PKG_CONFIG_PATH=%s/usr/lib/pkgconfig:$PKG_CONFIG_PATH\nexec %s/usr/bin/%s "$@"\n' \
            "$TOOLS_DIR" "$TOOLS_DIR" "$TOOLS_DIR" "$t" > "$TOOLS_DIR/wrappers/$t"
        chmod +x "$TOOLS_DIR/wrappers/$t"
    done
    echo "  ✓ 工具链就绪"
else
    echo "  ✓ 工具链已存在"
fi

printf '#!/bin/sh\nexport PATH=%s/wrappers:$PATH\nexport LD_LIBRARY_PATH=%s/usr/lib:$LD_LIBRARY_PATH\nexport C_INCLUDE_PATH=%s/usr/include\nexport CPLUS_INCLUDE_PATH=%s/usr/include\nexport PKG_CONFIG_PATH=%s/usr/lib/pkgconfig\n' \
    "$TOOLS_DIR" "$TOOLS_DIR" "$TOOLS_DIR" "$TOOLS_DIR" "$TOOLS_DIR" > "$HOME/steam-toolkit/buildenv.sh"
chmod +x "$HOME/steam-toolkit/buildenv.sh"

. "$HOME/steam-toolkit/buildenv.sh"
if ! (echo 'int main(){return 0;}' > /tmp/_t32.c && gcc -m32 /tmp/_t32.c -o /tmp/_t32 2>/dev/null); then
    echo "  ✗ 32 位编译测试失败"
    exit 1
fi
echo "  ✓ 32 位编译可用"

echo
echo "[2/5] 获取源码..."
if [ -d "$BUILD_DIR/.git" ]; then
    echo "  ✓ 已存在: $BUILD_DIR"
else
    git clone --depth 1 https://github.com/Hintay/SLSsteam-Plus.git "$BUILD_DIR"
    echo "  ✓ 已克隆"
fi
cd "$BUILD_DIR"

echo
echo "[3/5] 打补丁..."
if [ -f "$SCRIPT_DIR/slsplus.patch" ]; then
    if git apply --check "$SCRIPT_DIR/slsplus.patch" 2>/dev/null; then
        git apply "$SCRIPT_DIR/slsplus.patch" && echo "  ✓ 补丁已应用"
    else
        echo "  ⚠ 补丁无法应用（可能已应用或上游已变）"
    fi
else
    echo "  ⚠ 没找到 slsplus.patch"
fi

echo
echo "[4/5] 编译（首次约 20-40 分钟，含 LLVM）..."
. "$HOME/steam-toolkit/buildenv.sh"
make -j"$(nproc)" bin/SLSsteam.so bin/library-inject.so

echo
echo "[5/5] 安装..."
[ -f bin/SLSsteam.so ] || { echo "  ✗ 编译失败"; exit 1; }
bash "$SCRIPT_DIR/install-slsteam-plus.sh" bin/SLSsteam.so bin/library-inject.so

echo
echo "=============================================="
echo " 完成！"
echo "=============================================="
