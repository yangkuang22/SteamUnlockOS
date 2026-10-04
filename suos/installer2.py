"""
一键安装 —— 用 ManifestHub3 作为数据源（一个 appid 一个分支，含全部数据）

流程：
  1. 从 ManifestHub3 分支拿 lua + key.vdf + 所有清单
  2. 密钥写进 config.vdf（Steam 从这里读）
  3. 清单放进 depotcache/
  4. lua 放进 SLSsteam 的 lua 目录
  5. 重启 Steam → 点安装 → 自动下载
"""
import shutil
import re
from pathlib import Path
from typing import Optional

from . import steam, manifesthub3 as m3

LUA_DIRS = [
    Path.home() / ".config/SLSsteam/lua",
    Path.home() / ".local/share/Steam/config/lua",
]


def _write_keys_to_config(cfg_path: Path, keys: dict) -> int:
    """把密钥写进 config.vdf"""
    t = cfg_path.read_text(encoding="utf-8", errors="replace")
    written = 0
    for depid, key in keys.items():
        ds = str(depid)
        if re.search(rf'"{ds}"\s*\{{', t):
            # 替换已有的 DecryptionKey
            t2 = re.sub(rf'("{ds}"\s*\{{)[^}}]*("DecryptionKey"\s*"[0-9a-fA-F]*")?',
                        rf'\1\n\t\t\t\t\t\t"DecryptionKey"\t\t"{key}"\n\t\t\t\t\t', t, count=1)
            if t2 != t:
                t = t2; written += 1
        else:
            i = t.find('"depots"')
            if i < 0:
                continue
            j = t.find("{", i)
            block = (f'\n\t\t\t\t\t"{ds}"\n\t\t\t\t\t{{\n'
                     f'\t\t\t\t\t\t"DecryptionKey"\t\t"{key}"\n\t\t\t\t\t}}')
            t = t[:j + 1] + block + t[j + 1:]
            written += 1
    cfg_path.write_text(t, encoding="utf-8")
    return written


def install(appid: int, dry_run: bool = False, verbose: bool = True) -> dict:
    """
    从 ManifestHub3 一键准备某个游戏
    """
    log = print if verbose else (lambda *a, **k: None)
    paths = steam.find_steam()

    log(f"== 从 ManifestHub3 获取 {appid} ==")
    if not m3.branch_exists(appid):
        log(f"  ✗ ManifestHub3 没有 {appid} 的分支（太新或未收录）")
        return {"ok": False, "reason": "no_branch"}

    data = m3.fetch_all(appid)
    if not data:
        log("  ✗ 获取失败")
        return {"ok": False, "reason": "fetch_failed"}

    meta = data.get("meta") or {}
    name = meta.get("schinese_name") or meta.get("name") or "?"
    log(f"  游戏: {name}")
    log(f"  密钥: {len(data['keys'])} 个")
    log(f"  清单: {len(data['manifests'])} 个")

    if dry_run:
        log("  (dry-run，未写入)")
        return {"ok": True, "dry_run": True, **data}

    # 1. 备份 config.vdf
    bak = Path.home() / "SteamUnlockOS/backup/config.vdf.autobak"
    if not bak.is_file() and paths.config_vdf.is_file():
        bak.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(paths.config_vdf, bak)

    # 2. 密钥 → config.vdf
    n = _write_keys_to_config(paths.config_vdf, data["keys"])
    log(f"  ✓ 密钥写入 config.vdf: {n} 个")

    # 2.5 ★ 给"无密钥 depot"写占位密钥
    #   背景：Valve 的 appinfo 会强制要求某些 depot（常见是几十字节的小 depot），
    #        但我们没有它们的密钥。Steam 一遇到就报 "Missing decryption key"
    #        并【取消整个更新】——即使其他 depot 的密钥都齐全。
    #   实测：紫色晶石(625960) 的 depot 4506760 就是这个情况，写占位后立刻能下载。
    placeholders = 0
    for depid in _depots_without_keys(appid, data, paths):
        if _write_keys_to_config(paths.config_vdf, {depid: "00" * 32}):
            placeholders += 1
    if placeholders:
        log(f"  ✓ 占位密钥（无密钥 depot，防止阻塞）: {placeholders} 个")

    # 3. 清单 → depotcache
    paths.depotcache.mkdir(parents=True, exist_ok=True)
    for depid, gid, blob in data["manifests"]:
        (paths.depotcache / f"{depid}_{gid}.manifest").write_bytes(blob)
    log(f"  ✓ 清单写入 depotcache: {len(data['manifests'])} 个")

    # 4. lua → SLSsteam 目录（用官方 lua，格式完全正确）
    lua = data.get("lua") or ""
    if lua:
        for ld in LUA_DIRS:
            ld.mkdir(parents=True, exist_ok=True)
            (ld / f"{appid}.lua").write_text(lua, encoding="utf-8")
        log(f"  ✓ Lua 配置写入 {len(LUA_DIRS)} 个目录")

    return {"ok": True, "name": name, "keys": data["keys"],
            "manifests": [(d, g) for d, g, _ in data["manifests"]],
            "lua": lua, "meta": meta}


def _depots_without_keys(appid: int, data: dict, paths) -> list:
    """找出 Valve appinfo 里有、但我们没密钥的 depot（通常是几十字节的小 depot）。
    这些必须给占位密钥，否则 Steam 会因 'Missing decryption key' 取消整个更新。"""
    import json as _json
    import re as _re
    out = []
    # 从 Steam 的 appinfo.vdf 拿不到（加密），改用 SteamUnlock 服务端或社区元数据
    try:
        meta = data.get("meta") or {}
        depots = (meta.get("depot") or {})
        for did, dinfo in depots.items():
            try:
                depid = int(did)
            except Exception:
                continue
            if depid in data["keys"]:
                continue
            # 只要它在 manifest 列表里（说明 Valve 要求它），就加占位
            if isinstance(dinfo, dict) and (dinfo.get("manifests") or {}):
                out.append(depid)
    except Exception:
        pass
    return out
