#!/bin/bash
# ============================================================
# 自动检查游戏更新（由 systemd timer 调用，每 12 小时一次）
#
# 做的事:
#   ① 检查所有已入库游戏有没有更新
#   ② 有更新 → 自动应用（下新清单 + 改 gid）→ 桌面通知
#   ③ 顺便清理 depotcache 的无用旧清单（无更新时也做）
#
# 注意: 只更新【清单和 gid】，不动密钥（密钥不会变，见 docs/游戏更新机制.md）
# ============================================================
cd "$(dirname "$0")/.." || exit 1

python3 - <<'PYEOF'
import sys, subprocess
sys.path.insert(0, '.')
from suos import updater

# ── ① 检查更新 ──
results = updater.check_all()
need = [r for r in results if r.get("has_update")]
print(f"检查了 {len(results)} 个游戏，{len(need)} 个有更新")

# ── ② 应用更新（如果有）──
names = []
for r in need:
    res = updater.apply(r["appid"])
    n = res.get("downloaded", 0)
    if res.get("ok") and n:
        names.append(f"AppID {r['appid']} ({n} 个 depot)")
    print(f"  AppID {r['appid']}: {res.get('message')}")

# ── ③ 清理 depotcache（无论有没有更新都做）──
try:
    r = subprocess.run([sys.executable, "-m", "suos.depotcache_clean", "--apply"],
                       capture_output=True, text=True, timeout=1800)
    for line in (r.stdout or "").splitlines():
        s = line.strip()
        if "清理后" in s or "节省" in s:
            print(f"  depotcache: {s}")
except Exception as exc:  # noqa: BLE001
    print(f"  depotcache 清理跳过: {type(exc).__name__}")

# ── ④ 通知用户 ──
if names:
    msg = "\n".join(names)
    try:
        subprocess.run([
            "notify-send", "-t", "0", "-u", "normal",
            "Steam Toolkit: 游戏有更新",
            f"{len(names)} 个游戏有新版本已准备好:\n{msg}\n\n重启 Steam 后自动下载"
        ], timeout=10)
    except Exception:
        pass
    print(f"已通知用户: {len(names)} 个游戏需要重启 Steam")
else:
    print("没有更新，未打扰用户")
PYEOF
