#!/bin/bash
# ============================================================
# Steam Toolkit 启动器（加固版）
#   1. 自动检查注入库是否存在且可加载
#   2. 任何异常都回退到"不带注入"启动，保证 Steam 一定能开
#   3. 设置 SLS_NOINJECT=1 可强制不注入
# ============================================================
SLSDIR="$HOME/.local/share/SLSsteam"
LIB1="$SLSDIR/library-inject.so"
LIB2="$SLSDIR/SLSsteam.so"
STEAMBIN="/usr/bin/steam"
LOG="$HOME/.Steam Toolkit-launcher.log"

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# 手动跳过注入
if [ "${SLS_NOINJECT:-0}" = "1" ]; then
    log "SLS_NOINJECT=1 → 不带注入启动"
    exec "$STEAMBIN" "$@"
fi

# 检查文件存在且非空
if [ ! -s "$LIB1" ] || [ ! -s "$LIB2" ]; then
    log "注入库缺失或为空 → 回退到普通启动（Steam 仍可正常使用）"
    exec "$STEAMBIN" "$@"
fi

# 快速验证动态链接（缺依赖就不注入，避免刷屏报错）
if command -v ldd >/dev/null 2>&1; then
    if ldd "$LIB2" 2>/dev/null | grep -q "not found"; then
        log "SLSsteam.so 依赖缺失 → 回退到普通启动"
        exec "$STEAMBIN" "$@"
    fi
fi

log "带 SLSsteam-Plus 注入启动"
export LD_AUDIT="$LIB1:$LIB2"
exec "$STEAMBIN" "$@"
