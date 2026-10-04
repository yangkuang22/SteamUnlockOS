#!/bin/bash
# ============================================================
# Steam 升级后的体检 + 自动修复
#
# 用法: bash scripts/check-after-steam-update.sh [--fix]
# ============================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 项目根目录：从脚本位置推导，不写死目录名（新旧安装都适用）
SLSDIR="$HOME/.local/share/SLSsteam"
LOG="$HOME/.SLSsteam.log"
FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

echo "=================================================="
echo " Steam 升级后体检"
echo "=================================================="
echo

# Steam 版本指纹
SC="$HOME/.local/share/Steam/ubuntu12_32/steamclient.so"
if [ -f "$SC" ]; then
    echo "steamclient.so:"
    echo "  大小: $(stat -c%s "$SC") 字节"
    echo "  修改: $(stat -c %y "$SC" | cut -d. -f1)"
    echo "  SHA256: $(sha256sum "$SC" | cut -c1-32)…"
else
    echo "✗ 找不到 steamclient.so"
fi
echo

# 特征码状态
if [ -f "$LOG" ]; then
    LAST=$(grep -E "pattern summary" "$LOG" 2>/dev/null | tail -1)
    if [ -n "$LAST" ]; then
        echo "最近的特征码匹配:"
        echo "  $LAST"
        MISS=$(echo "$LAST" | grep -oE "missing=[0-9]+" | cut -d= -f2)
        FOUND=$(echo "$LAST" | grep -oE "found=[0-9]+" | cut -d= -f2)
        if [ "${MISS:-0}" != "0" ]; then
            echo
            echo "  ⚠ 有 $MISS 条特征码失配！Steam 可能升级了，需要重新编译"
            NEED_FIX=1
        else
            echo "  ✓ 全部匹配（$FOUND 条），不需要处理"
            NEED_FIX=0
        fi
    else
        echo "⚠ 日志里没有特征码记录（SLSsteam 可能没加载）"
        NEED_FIX=1
    fi
    if grep -q "Failed to find all patterns" "$LOG" 2>/dev/null; then
        echo "  ⚠ 日志里有 'Failed to find all patterns' → 需要重新编译"
        NEED_FIX=1
    fi
else
    echo "⚠ 没有 SLSsteam 日志（从没成功加载过）"
    NEED_FIX=1
fi
echo

# 编译环境还在吗
if [ -d "$HOME/slsplus-build" ] && [ -f "$ROOT/buildenv.sh" ] && [ -d "$ROOT/buildtools/wrappers" ]; then
    echo "✓ 编译环境在（$HOME/slsplus-build）"
    echo "  当前编译产物: $(stat -c%s "$HOME/slsplus-build/bin/SLSsteam.so" 2>/dev/null || echo '无') 字节"
else
    echo "✗ 编译环境不在（无法重新编译）"
fi
echo

if [ "${NEED_FIX:-0}" = "1" ]; then
    echo "=================================================="
    echo " 需要修复：重新编译 SLSsteam-Plus"
    echo "=================================================="
    if [ "$FIX" = "1" ]; then
        echo "  开始重新编译（约 1-5 分钟，取决于改动量）…"
        # ★ 工具链没加载上就绝不编译：否则会用系统 gcc（无 32 位支持）编译失败，
        #   并被误报成"上游还没适配"，把排查方向带偏
        if ! . "$ROOT/buildenv.sh" || [ ! -d "${SLSU_TOOLS:-}/wrappers" ]; then
            echo "  ✗ 32 位工具链不可用（${SLSU_TOOLS:-未设置}）"
            echo "     先重建工具链: bash $ROOT/scripts/build-slsteam-plus.sh"
            exit 1
        fi
        cd "$HOME/slsplus-build" || exit 1
        if make -j"$(nproc)" bin/SLSsteam.so bin/library-inject.so 2>&1 | tail -5; then
            cp bin/SLSsteam.so bin/library-inject.so "$SLSDIR/" && echo "  ✓ 已安装新编译的库"
            echo "  → 重启 Steam 生效"
        else
            echo "  ✗ 编译失败！可能上游还没适配新版本 Steam"
            echo "     尝试: cd ~/slsplus-build && git pull && 重新打补丁"
        fi
    else
        echo "  跑这个自动修: bash $0 --fix"
        echo "  或者手动: source $ROOT/buildenv.sh && cd ~/slsplus-build && make -j\$(nproc) && cp bin/*.so ~/.local/share/SLSsteam/"
    fi
else
    echo "✓ 一切正常，不需要处理"
fi
