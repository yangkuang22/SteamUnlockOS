#!/usr/bin/env bash
# 带 SLSsteam 注入重启 Steam。出错不会影响桌面/系统（只是 Steam 起不来，重跑一次即可）。
set -uo pipefail
SLSDIR="$HOME/.local/share/SLSsteam"
LIB="$SLSDIR/SLSsteam.so"
LOG="$HOME/steam-toolkit/logs/steam-injected.log"
mkdir -p "$(dirname "$LOG")"

[ -f "$LIB" ] || { echo "✗ 找不到 $LIB，先运行 scripts/setup-slssteam.sh"; exit 1; }

echo "→ 关闭当前 Steam 进程"
# 注意：不能用 pkill -f "ubuntu12_32/steam" —— 那会匹配到"正在执行本脚本的 shell"自己（命令行里含该字符串）
# 只杀"二进制路径以 /ubuntu12_32/steam 开头"的进程，绝不匹配到自己（脚本命令行里没有该路径的裸形式）
steam_pids() {
    for d in /proc/[0-9]*; do
        pid="${d#/proc/}"
        [ "$pid" = "$$" ] && continue
        exe="$(readlink -f "$d/exe" 2>/dev/null)" || continue
        case "$exe" in
            */ubuntu12_32/steam|*/ubuntu12_32/steamwebhelper|*/ubuntu12_64/steamwebhelper) echo "$pid" ;;
        esac
    done
}
for pid in $(steam_pids); do kill "$pid" 2>/dev/null || true; done
sleep 4
for pid in $(steam_pids); do kill -9 "$pid" 2>/dev/null || true; done
sleep 2

echo "→ 带注入启动（LD_AUDIT=$LIB）"
setsid env LD_AUDIT="$LIB" /usr/bin/steam >"$LOG" 2>&1 &
disown 2>/dev/null || true

for i in $(seq 1 30); do
    sleep 2
    if pgrep -f "ubuntu12_32/steam -srt-logger-opened" >/dev/null 2>&1; then
        echo "✓ Steam 已启动（等待 ${i}×2 秒）"
        sleep 8
        if pgrep -x steamwebhelper >/dev/null 2>&1; then
            echo "✓ steamwebhelper 也在跑 —— 启动成功"
            exit 0
        fi
        echo "⚠ Steam 主进程在，但 webhelper 还没起来，再等会儿"
    fi
done
echo "✗ 30 秒内没等到 Steam 起来。日志尾部："
tail -30 "$LOG"
echo
echo "恢复方法（去掉注入，正常启动）："
echo "  setsid /usr/bin/steam &"
exit 1
