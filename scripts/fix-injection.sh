#!/bin/bash
# ============================================================
# SLSsteam 注入管理
#
# 用法:
#   bash scripts/fix-injection.sh status    # 看当前状态
#   bash scripts/fix-injection.sh install   # 给 steam.sh 打注入补丁
#   bash scripts/fix-injection.sh remove    # 移除注入补丁（还原）
#   bash scripts/fix-injection.sh test      # 测试注入是否生效
# ============================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 项目根目录：从脚本位置推导，不写死目录名（新旧安装都适用）
STEAM_SH="$HOME/.local/share/Steam/steam.sh"
BAK="$ROOT/backup/steam.sh.orig"
SLSDIR="$HOME/.local/share/SLSsteam"
MARK="SLSsteam-Plus"

case "${1:-status}" in
  status)
    echo "=== steam.sh 状态 ==="
    if [ ! -f "$STEAM_SH" ]; then echo "  ✗ 找不到 $STEAM_SH"; exit 1; fi
    if grep -q "$MARK" "$STEAM_SH"; then
        echo "  ✓ 已打注入补丁"
    else
        echo "  ✗ 未打补丁（游戏模式/系统启动时不会注入）"
    fi
    echo "  备份: $([ -f "$BAK" ] && echo "✓ $BAK" || echo '✗ 不存在')"
    echo
    echo "=== 当前 Steam 进程注入情况 ==="
    found=0
    for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
        exe=$(readlink /proc/$pid/exe 2>/dev/null)
        case "$exe" in
          */ubuntu12_32/steam)
            found=1
            echo "  Steam PID $pid"
            if tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -q "^LD_AUDIT="; then
                echo "    ✓ 已注入"
            else
                echo "    ✗ 未注入"
            fi
            ;;
        esac
    done
    [ "$found" = 0 ] && echo "  （Steam 未运行）"
    ;;

  install)
    [ -f "$BAK" ] || { echo "✗ 备份不存在，拒绝操作（先手动确认）"; exit 1; }
    if grep -q "$MARK" "$STEAM_SH"; then echo "✓ 已经打过补丁"; exit 0; fi
    python3 - "$STEAM_SH" <<'PYEOF'
import sys
from pathlib import Path
p = Path(sys.argv[1])
t = p.read_text()
BLOCK = '''
# ── SLSsteam-Plus 注入（Steam Toolkit 添加）──────────────────────
# 在这里导出 LD_AUDIT，保证【所有】启动方式都注入：
#   systemd autostart / 游戏模式 / 桌面图标 / Steam 客户端自身重启
# 出问题时: 设环境变量 SLS_NOINJECT=1，或者删除本注释块
if [ "${SLS_NOINJECT:-0}" != "1" ]; then
    _sls_dir="${HOME}/.local/share/SLSsteam"
    if [ -s "${_sls_dir}/library-inject.so" ] && [ -s "${_sls_dir}/SLSsteam.so" ]; then
        export LD_AUDIT="${_sls_dir}/library-inject.so:${_sls_dir}/SLSsteam.so"
        echo "steam.sh[$$]: SLSsteam-Plus injection enabled" >&2 || :
    fi
    unset _sls_dir
fi
# ────────────────────────────────────────────────────────────────
'''
anchor = "set -u\n"
i = t.find(anchor)
if i < 0:
    print("✗ 找不到插入锚点"); sys.exit(1)
j = i + len(anchor)
p.write_text(t[:j] + BLOCK + t[j:])
print("✓ 注入补丁已应用")
PYEOF
    bash -n "$STEAM_SH" && echo "✓ 语法校验通过" || { echo "✗ 语法错误，正在还原"; cp "$BAK" "$STEAM_SH"; exit 1; }
    ;;

  remove)
    [ -f "$BAK" ] || { echo "✗ 备份不存在"; exit 1; }
    cp "$BAK" "$STEAM_SH"
    echo "✓ 已还原成原始 steam.sh"
    ;;

  test)
    echo "=== 测试：用 systemd 的方式启动 Steam ==="
    echo "  （会关闭当前 Steam）"
    for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
        exe=$(readlink /proc/$pid/exe 2>/dev/null)
        case "$exe" in */ubuntu12_32/steam|*/steamwebhelper) kill -TERM "$pid" 2>/dev/null;; esac
    done
    sleep 15
    rm -f "$HOME/.SLSsteam.log"
    setsid nohup /usr/bin/steam -silent >/tmp/steam-inj-test.log 2>&1 </dev/null &
    sleep 45
    for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
        exe=$(readlink /proc/$pid/exe 2>/dev/null)
        case "$exe" in
          */ubuntu12_32/steam)
            echo "  Steam PID $pid"
            if tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -q "^LD_AUDIT="; then
                echo "    ✓ 注入成功"
            else
                echo "    ✗ 注入失败"
            fi
            ;;
        esac
    done
    grep -E "Loaded successfully" "$HOME/.SLSsteam.log" 2>/dev/null | tail -1 | sed 's/^/    /'
    ;;

  *) echo "用法: $0 status|install|remove|test"; exit 1;;
esac
