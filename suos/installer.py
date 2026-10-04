"""
一键准备：SteamUnlock 服务端（depot 列表/gid）+ 社区密钥库 → 写入 Steam 配置
经验证的可用流程（紫色晶石 625960 实测成功，853MB 完整下载）
"""
import re, shutil
from pathlib import Path
from typing import List, Tuple

from . import server_api, steam, vdf, depotkeys, manifests, slsconfig, appinfo_parse

LUA_DIRS = [
    Path.home() / ".config/SLSsteam/lua",
    Path.home() / ".local/share/Steam/config/lua",
]


def _write_depot_key_to_config(cfg_path: Path, depotid: int, key_hex: str) -> bool:
    """把 32 字节密钥写进 config.vdf（Steam 从这里读取）"""
    t = cfg_path.read_text(encoding="utf-8", errors="replace")
    # 已存在则替换
    if re.search(rf'"{depotid}"\s*\{{', t):
        t = re.sub(rf'("{depotid}"\s*\{{)\s*"DecryptionKey"\s*"[0-9a-fA-F]*"',
                   rf'\1\n\t\t\t\t\t\t"DecryptionKey"\t\t"{key_hex}"', t, count=1)
    else:
        i = t.find('"depots"')
        if i < 0:
            return False
        j = t.find("{", i)
        block = (f'\n\t\t\t\t\t"{depotid}"\n\t\t\t\t\t{{\n'
                 f'\t\t\t\t\t\t"DecryptionKey"\t\t"{key_hex}"\n\t\t\t\t\t}}')
        t = t[:j + 1] + block + t[j + 1:]
    cfg_path.write_text(t, encoding="utf-8")
    return True


def prepare(appid: int, branch: str = "public", verbose: bool = True) -> dict:
    """
    为 appid 准备好下载所需的一切：
      1. 从 SteamUnlock 服务端拿 depot 列表 + gid
      2. 从社区密钥库拿 32 字节密钥
      3. 密钥写进 config.vdf（Steam 从这里读）
      4. 写 Lua 配置（清单 gid 覆盖；无密钥的 depot 跳过）
    """
    log = print if verbose else (lambda *a, **k: None)
    paths = steam.find_steam()
    cfg_path = paths.config_vdf

    plan = server_api.install_plan(appid, cache_dir=Path("cache"))
    log(f"  SteamUnlock 服务端: {len(plan.depots)} 个 depot")

    # ★ 从服务端 appinfo 解析全部版本信息（能选历史版本）
    branch_gids = {}
    try:
        from . import rc4 as _rc4
        raw = Path("cache/GetAppinfo_%d.bin" % appid)
        if raw.is_file():
            import ast as _ast
            _j = _ast.literal_eval(_rc4.rc4(_rc4.RC4_KEY, raw.read_bytes()).decode("utf-8", "replace"))
            _dep = appinfo_parse.parse_depots(_j.get("appinfo", ""))
            for depid, info in _dep.items():
                mb = info.get("manifests", {})
                pick = mb.get(branch) or mb.get("public")
                if pick:
                    branch_gids[depid] = pick["gid"]
            avail = sorted({b for i in _dep.values() for b in i.get("manifests", {})})
            log(f"  版本分支: {len(avail)} 个可选（当前用 '{branch}'）")
    except Exception as e:
        log(f"  （版本解析跳过: {str(e)[:40]}）")

    ck = depotkeys.load_community_keys()
    keys, missing = depotkeys.keys_for_app(plan.depots, ck)
    log(f"  社区密钥: {len(keys)} 个有密钥, {len(missing)} 个无密钥 {missing}")

    # 备份 config.vdf
    bak = Path(__file__).resolve().parent.parent / "backup/config.vdf.autobak"
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(cfg_path, bak)

    # 写密钥
    for depid, k in keys.items():
        _write_depot_key_to_config(cfg_path, depid, k)
    log(f"  ✓ 已写入 {len(keys)} 个密钥到 config.vdf")

    # ★ 下载清单文件到 depotcache（关键：Steam 从这里读清单）
    dl_ok, dl_fail = 0, []
    for d in plan.depots:
        gid = branch_gids.get(d.depotid) or d.gid
        if d.depotid not in keys or not gid:
            continue
        mf = paths.depotcache / f"{d.depotid}_{gid}.manifest"
        if mf.is_file() and mf.stat().st_size > 100:
            dl_ok += 1
            continue
        try:
            r = manifests.fetch_manifest(appid, d.depotid, gid)
            if r:
                manifests.install_manifest(paths.depotcache, d.depotid, gid, r.data)
                dl_ok += 1
        except Exception:
            pass
        else:
            if not (mf.is_file() and mf.stat().st_size > 100):
                dl_fail.append(d.depotid)
    log(f"  ✓ 清单文件: {dl_ok} 个就绪" + (f", {len(dl_fail)} 个拿不到 {dl_fail}" if dl_fail else ""))

    # 清单（只给有密钥的 depot 设 gid —— 无密钥的跳过，避免阻塞）
    lines = [f"-- {appid} 自动生成（Steam Toolkit）",
             f"-- 密钥: 社区库 | depot 列表: SteamUnlock 服务端",
             f"addappid({appid})"]
    for d in plan.depots:
        if d.depotid in keys:
            lines.append(f'addappid({d.depotid}, 1, "{keys[d.depotid]}")')
        else:
            lines.append(f"addappid({d.depotid})")
    lines.append("")
    for d in plan.depots:
        gid = branch_gids.get(d.depotid) or d.gid
        if d.depotid in keys and gid:
            lines.append(f'setmanifestid({d.depotid}, "{gid}")')
    lua = "\n".join(lines) + "\n"

    for ld in LUA_DIRS:
        ld.mkdir(parents=True, exist_ok=True)
        (ld / f"{appid}.lua").write_text(lua)

    log(f"  ✓ Lua 配置已写入 {len(LUA_DIRS)} 个目录")
    return {"appid": appid, "keys": keys, "missing": missing, "manifest_fail": dl_fail,
            "depots": [(d.depotid, d.gid, d.size) for d in plan.depots],
            "lua": lua}
