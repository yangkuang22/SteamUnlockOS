#!/bin/bash
# ============================================================
# 日志归档 —— 把散落在根目录的日志收进项目里
#
# 为什么需要:
#   SLSsteam 的日志固定在 ~/.SLSsteam.log
#   调试时如果直接备份到根目录，会堆积一堆 .SLSsteam.log.before-*
#
# 用法: bash scripts/archive-logs.sh
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

DEST="logs/history"
KEEP=10          # 只保留最近 10 个历史日志
mkdir -p "$DEST"

n=0
for f in "$HOME"/.SLSsteam.log.before-* "$HOME"/.SLSsteam.log.prev \
         "$HOME"/.SLSsteam.log.crash-session \
         "$HOME"/.Steam Toolkit-launcher.log* \
         "$HOME"/SteamUnlockOS/logs/launcher.log.*; do
    [ -f "$f" ] || continue
    mv "$f" "$DEST/" && n=$((n + 1))
done
# 轮转当前 launcher.log（超过 1MB 就归档）
_ll="$HOME/steam-toolkit/logs/launcher.log"
if [ -f "$_ll" ] && [ "$(stat -c%s "$_ll" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    mv "$_ll" "$DEST/launcher.log.$(date +%Y%m%d-%H%M%S)" && n=$((n + 1))
    echo "  launcher.log 超过 1MB，已轮转"
fi

echo "已归档 $n 个日志 → $DEST"

# 只保留最近 N 个
ls -t "$DEST"/*.log* 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old" && echo "  清理旧日志: $(basename "$old")"
done

echo "当前归档: $(ls "$DEST" 2>/dev/null | wc -l) 个文件，$(du -sh "$DEST" 2>/dev/null | cut -f1)"
