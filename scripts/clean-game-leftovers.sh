#!/bin/bash
# ============================================================
# 清理指定游戏的 Steam 残留
#
# 背景: 用本工具移除游戏后，Steam 不会自动清理这些:
#   · 封面图缓存        appcache/librarycache/<appid>/
#   · 成就列表          userdata/<uid>/config/librarycache/<appid>.json
#   · 成就定义/统计     appcache/stats/*<appid>*
#   · temp 目录         steamapps/temp/<appid>/
#   · 游戏目录（空）    steamapps/common/<installdir>/
#   · 桌面图标          ~/Desktop/<游戏名>.desktop
#
# 用法:
#   bash scripts/clean-game-leftovers.sh <appid>          # 只报告
#   bash scripts/clean-game-leftovers.sh <appid> --apply  # 实际清理
# ============================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 项目根目录：从脚本位置推导，不写死目录名（新旧安装都适用）
APPID="${1:-}"
APPLY="${2:-}"
[ -n "$APPID" ] || { echo "用法: $0 <appid> [--apply]"; exit 1; }
echo "$APPID" | grep -qE '^[0-9]+$' || { echo "appid 必须是数字"; exit 1; }

STEAM="$HOME/.local/share/Steam"
BAK="$ROOT/backup/leftover-$APPID"
FOUND=0

find_and_handle() {
    local desc="$1"; shift
    for p in "$@"; do
        [ -e "$p" ] || continue
        FOUND=$((FOUND + 1))
        local sz; sz=$(du -sh "$p" 2>/dev/null | cut -f1)
        echo "  找到: $desc  $p  ($sz)"
        if [ "$APPLY" = "--apply" ]; then
            mkdir -p "$BAK"
            cp -r "$p" "$BAK/" 2>/dev/null
            rm -rf "$p" && echo "    ✓ 已删（备份在 $BAK）"
        fi
    done
}

echo "== 清理 $APPID 的残留 =="
echo
# Steam 自己的缓存
find_and_handle "封面图缓存"   "$STEAM/appcache/librarycache/$APPID"
find_and_handle "成就定义/统计" "$STEAM"/appcache/stats/*"$APPID"*
find_and_handle "temp 目录"     "$STEAM/steamapps/temp/$APPID"
find_and_handle "下载目录"      "$STEAM/steamapps/downloading/$APPID"
find_and_handle "着色器缓存"    "$STEAM/shadercache/$APPID"
find_and_handle "ACF 文件"      "$STEAM/steamapps/appmanifest_$APPID.acf"
# 每个用户的成就列表缓存
for u in "$STEAM"/userdata/*/; do
    find_and_handle "成就列表" "${u}config/librarycache/$APPID.json"
done
# 空游戏目录（找 installdir）
if [ -f "$STEAM/steamapps/appmanifest_$APPID.acf" ]; then
    idle=$(grep -oP '"installdir"\s+"\K[^"]+' "$STEAM/steamapps/appmanifest_$APPID.acf" 2>/dev/null)
    [ -n "$idle" ] && find_and_handle "游戏目录" "$STEAM/steamapps/common/$idle"
fi
# 桌面图标（按内容匹配 appid）
for f in "$HOME/Desktop"/*.desktop; do
    [ -f "$f" ] || continue
    grep -q "rungameid/$APPID\b" "$f" 2>/dev/null && find_and_handle "桌面图标" "$f"
done

echo
if [ "$FOUND" -eq 0 ]; then
    echo "  ✓ 没有找到残留"
elif [ "$APPLY" != "--apply" ]; then
    echo "  共 $FOUND 处。加 --apply 实际清理（会先备份）"
else
    echo "  共处理 $FOUND 处。建议重启 Steam 让库刷新"
fi
