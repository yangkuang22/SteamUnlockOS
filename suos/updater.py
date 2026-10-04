"""游戏版本更新 —— 检查 + 应用

验证过的完整链路（2026-10-03 实测 Barotrauma）:
  ① api.steamcmd.net 拿最新 gid + buildid
  ② manifest.luastools.xyz 下新清单（不需要密钥/请求码）
  ③ 写进 Steam/depotcache/
  ④ 更新 Lua 的 setManifestid
  ⑤ 重启 Steam → Steam 自动检测到"config changed" → 开始下载

实测输出:
  [22:03:12] AppID 602960 config changed : updated depots 602962
  [22:03:22] update prefetch finished : 24258432 bytes to download
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

STEAM = Path.home() / ".local/share/Steam"
DEPOTCACHE = STEAM / "depotcache"
LUA_SLS = Path.home() / ".config/SLSsteam/lua"
LUA_STEAM = STEAM / "config/lua"
BACKUP = Path.home() / "SteamUnlockOS/backup/updates"
UA = {"User-Agent": "Mozilla/5.0"}


def latest_manifests(appid: int, timeout: int = 25) -> dict[int, dict]:
    """从 api.steamcmd.net 拿所有 depot 的最新 gid。

    返回 {depot: {"gid": int, "size": int}}
    """
    try:
        url = f"https://api.steamcmd.net/v1/info/{appid}"
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=timeout).read())
        info = d["data"][str(appid)]
    except Exception:
        return {}
    out: dict[int, dict] = {}
    for k, v in (info.get("depots") or {}).items():
        if not isinstance(v, dict):
            continue
        pub = (v.get("manifests") or {}).get("public")
        if not pub:
            continue
        try:
            size = int(pub.get("size") or 0)
            gid = int(pub["gid"])
        except Exception:
            continue
        if size > 0:
            out[int(k)] = {"gid": gid, "size": size}
    return out


def latest_buildid(appid: int, timeout: int = 25) -> str | None:
    try:
        url = f"https://api.steamcmd.net/v1/info/{appid}"
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=timeout).read())
        br = ((d["data"][str(appid)].get("depots") or {}).get("branches") or {})
        pub = br.get("public") or {}
        v = pub.get("buildid")
        return str(v) if v else None
    except Exception:
        return None


def local_pins(appid: int) -> dict[int, int]:
    """读本地 Lua 里 pin 的 gid"""
    f = LUA_SLS / f"{appid}.lua"
    if not f.is_file():
        return {}
    t = f.read_text(errors="replace")
    return {int(d): int(g) for d, g in re.findall(r'setManifestid\((\d+),\s*"(\d+)"\)', t)}


def local_buildid(appid: int) -> str | None:
    acf = STEAM / f"steamapps/appmanifest_{appid}.acf"
    if not acf.is_file():
        return None
    m = re.search(r'"buildid"\s+"(\d+)"', acf.read_text(errors="replace"))
    return m.group(1) if m else None


def check(appid: int, verbose: bool = False) -> dict:
    """检查一个游戏有没有更新。不修改任何东西。"""
    out = {"appid": appid, "has_update": False, "need": {}, "local_build": None,
           "latest_build": None, "error": None}
    pins = local_pins(appid)
    if not pins:
        out["error"] = "没有 Lua 配置（不是通过本工具入库的，或没有 setManifestid）"
        return out
    latest = latest_manifests(appid)
    if not latest:
        out["error"] = "api.steamcmd.net 查询失败"
        return out
    out["local_build"] = local_buildid(appid)
    out["latest_build"] = latest_buildid(appid)
    for dep, old in pins.items():
        new = latest.get(dep)
        if new and new["gid"] != old:
            out["need"][dep] = {"old": old, "new": new["gid"], "size": new["size"]}
    out["has_update"] = bool(out["need"])
    if verbose:
        print(f"  {appid}: build {out['local_build']} → {out['latest_build']}")
        for dep, v in out["need"].items():
            print(f"    depot {dep}: {v['old']} → {v['new']} ({v['size']:,} 字节)")
        if not out["need"]:
            print("    ✓ 已是最新")
    return out


def apply(appid: int, verbose: bool = False) -> dict:
    """应用更新：下新清单 + 改 Lua gid。"""
    from . import manifests

    res = {"ok": False, "appid": appid, "downloaded": 0, "failed": [], "steps": []}
    info = check(appid, verbose=verbose)
    if info.get("error"):
        res["steps"].append(f"✗ {info['error']}")
        return res
    if not info["has_update"]:
        res["ok"] = True
        res["steps"].append("✓ 已是最新，无需更新")
        return res

    need = info["need"]
    BACKUP.mkdir(parents=True, exist_ok=True)
    for d in (LUA_SLS, LUA_STEAM):
        f = d / f"{appid}.lua"
        if f.is_file():
            (BACKUP / f"{appid}.lua.{d.parent.name}.bak").write_text(f.read_text())

    for dep, v in need.items():
        r = manifests.fetch_manifest(appid, dep, v["new"])
        if r:
            manifests.install_manifest(DEPOTCACHE, dep, v["new"], r.data)
            res["downloaded"] += 1
            res["steps"].append(f"✓ depot {dep}: 下到新清单 {v['new']} ({len(r.data):,} 字节, {r.provider})")
        else:
            res["failed"].append(dep)
            res["steps"].append(f"✗ depot {dep}: 清单下载失败")

    if res["downloaded"]:
        for d in (LUA_SLS, LUA_STEAM):
            f = d / f"{appid}.lua"
            if not f.is_file():
                continue
            t = f.read_text()
            for dep, v in need.items():
                t = re.sub(rf'(setManifestid\({dep},\s*")[0-9]+(")', rf'\g<1>{v["new"]}\g<2>', t)
            f.write_text(t)
        res["steps"].append(f"✓ 更新了 Lua 的 gid（备份在 backup/updates/）")
        res["ok"] = True
        res["message"] = f"{res['downloaded']} 个 depot 有更新 —— 重启 Steam 后自动下载"
    else:
        res["message"] = "所有清单下载失败"
    return res


def check_all(verbose: bool = False) -> list[dict]:
    """检查所有已入库游戏"""
    out = []
    for f in sorted(LUA_SLS.glob("*.lua")):
        if not f.stem.isdigit():
            continue
        out.append(check(int(f.stem), verbose=verbose))
    return out

def latest_gids(appid: int, timeout: int = 25) -> dict[int, int]:
    """从 Steam 拿所有 depot 的最新 gid（只有 size > 0 的）。

    为什么需要: ManifestHub3 是【快照】，可能几个月没更新。
    入库时如果用它给的 gid，会写进过时的版本 →
    WebUI 的更新检查永远报"有更新"，而且用户更新后
    重新入库又会被退回旧版。

    另见 latest_manifests()（带 size 信息）。
    """
    out: dict[int, int] = {}
    for dep, info in latest_manifests(appid, timeout=timeout).items():
        try:
            out[int(dep)] = int(info["gid"])
        except (KeyError, TypeError, ValueError):
            continue
    return out
