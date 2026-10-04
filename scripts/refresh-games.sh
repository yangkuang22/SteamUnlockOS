#!/bin/bash
# ============================================================
# 检查已入库游戏的版本更新
#
# 用法: bash scripts/refresh-games.sh [--apply]
#   不加参数 = 只检查（不改动）
#   --apply  = 发现有更新就更新 Lua
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

python3 - "$APPLY" <<'PYEOF'
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
APPLY = sys.argv[1] == "1"

LUA_DIR = Path.home() / ".config/SLSsteam/lua"
LUA_STEAM = Path.home() / ".local/share/Steam/config/lua"
BACKUP = Path.cwd() / "backup/lua-refresh"   # 脚本已 cd 到项目根目录

print("=" * 60)
print(" 已入库游戏的版本检查")
print("=" * 60)

from suos import manifesthub3, sudama

def current_gid(appid):
    """从数据源拿最新的 manifest gid"""
    try:
        r = manifesthub3.fetch_all(appid)
        if r and r.get("manifests"):
            return {dep: gid for dep, gid, _ in r["manifests"]}
    except Exception:
        pass
    return {}

total = updated = 0
for f in sorted(LUA_DIR.glob("*.lua")):
    total += 1
    appid = int(f.stem)
    text = f.read_text()
    pins = {int(d): g for d, g in re.findall(r'setManifestid\((\d+),\s*"(\d+)"\)', text)}
    if not pins:
        print(f"\n  {appid}: 没有 setManifestid（动态版本）")
        continue

    latest = current_gid(appid)
    if not latest:
        print(f"\n  {appid}: 数据源查不到（跳过）")
        continue

    diffs = []
    for dep, cur in pins.items():
        new = latest.get(dep)
        if new and str(new) != str(cur):
            diffs.append((dep, cur, new))

    if not diffs:
        print(f"\n  {appid}: ✓ 已是最新（{len(pins)} 个 depot）")
        continue

    print(f"\n  {appid}: ★ 有 {len(diffs)} 个 depot 版本更新")
    for dep, cur, new in diffs:
        print(f"      depot {dep}: {cur} → {new}")

    if APPLY:
        BACKUP.mkdir(parents=True, exist_ok=True)
        (BACKUP / f"{appid}.lua.bak").write_text(text)
        nt = text
        for dep, cur, new in diffs:
            nt = re.sub(rf'(setManifestid\({dep},\s*"){cur}(")', rf"\g<1>{new}\g<2>", nt)
        f.write_text(nt)
        (LUA_STEAM / f"{appid}.lua").write_text(nt)
        print(f"      ✓ 已更新（备份: backup/lua-refresh/{appid}.lua.bak）")
        updated += 1

print()
print("=" * 60)
if APPLY:
    print(f" 检查 {total} 个游戏，更新 {updated} 个")
    if updated:
        print(" → 重启 Steam 生效（新版本会在库里显示更新）")
else:
    print(f" 检查 {total} 个游戏")
    print(" → 加 --apply 参数才会实际更新")
PYEOF
