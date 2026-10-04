"""多数据源统一安装器

数据源（按优先级）:
  ① Sudama 密钥库        api.993499094.xyz/depotkeys.json   239,946 条密钥
  ② 社区 depotkeys.json  SteamAutoCracks/ManifestHub        288,381 条密钥
  ③ ManifestHub3         steamtools-games/ManifestHub3      62,000+ 分支（密钥+清单+Lua）
  ④ ManifestAutoUpdate   多个 fork                          2,591+ 分支（备用）

策略:
  · 密钥: Sudama → 社区库 → ManifestHub3（谁有就用谁）
  · 清单: ManifestHub3 → ManifestAutoUpdate
  · depot 列表 + GID: SteamUnlock API（GetAppinfo）→ ManifestHub3 元数据
"""
from __future__ import annotations

import re
from pathlib import Path

from . import sudama, depotkeys, manifesthub3


def _log(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg)


def resolve(appid: int, verbose: bool = True) -> dict | None:
    """汇总所有数据源，返回统一结构。

    返回:
      {
        "appid": int,
        "name": str | None,
        "keys": {depot: 64hex},
        "manifests": [(depot, gid, bytes)],
        "lua": str | None,
        "sources": {"keys": [...], "manifests": [...], "name": [...]},
      }
    """
    out = {
        "appid": appid,
        "name": None,
        "keys": {},
        "manifests": [],
        "lua": None,
        "sources": {"keys": [], "manifests": [], "name": []},
        # ★ Valve/服务端认为这个 app 需要哪些 depot（含没有密钥的）
        #   install() 用它来找"无密钥 depot"并写占位密钥。
        #   不在 meta 里的 depot（如 787480）也可能出现在这里。
        "depots": [],
    }

    # ── ① ManifestHub3（提供 depotid 列表、gid、清单文件、Lua） ──
    mh3 = None
    try:
        mh3 = manifesthub3.fetch_all(appid)
    except Exception as exc:  # noqa: BLE001
        _log(f"  ManifestHub3 失败: {str(exc)[:60]}", verbose)

    mh3_depots: list[int] = []
    if mh3:
        for dep, gid, data in mh3.get("manifests") or []:
            if dep not in mh3_depots:
                mh3_depots.append(dep)
        for dep in (mh3.get("keys") or {}):
            if dep not in mh3_depots:
                mh3_depots.append(dep)
        # Lua 里出现的 depot（含 addappid 和 setManifestid）
        for m in re.finditer(r'addappid\(\s*(\d+)', mh3.get("lua") or ""):
            d = int(m.group(1))
            if d != appid and d not in mh3_depots:
                mh3_depots.append(d)
        for _d in mh3_depots:
            if _d not in out["depots"]:
                out["depots"].append(_d)
        if mh3_depots:
            _log(f"  ManifestHub3: {len(mh3_depots)} 个 depot, "
                 f"{len(mh3.get('manifests') or [])} 个清单", verbose)

    # ── ② SteamUnlock API（拿 depot 列表 + gid，用于社区库没有的新游戏） ──
    api_config = None
    try:
        from . import server_api
        plan = server_api.install_plan(appid, cache_dir=Path(__file__).parent.parent / "cache")
        if plan and plan.depots:
            api_config = plan
            # ★ 记录所有 depot（含 key=None 的无密钥 depot）
            for _d in plan.depots:
                try:
                    _id = int(getattr(_d, "depotid", 0) or 0)
                    if _id and _id not in out["depots"]:
                        out["depots"].append(_id)
                except (TypeError, ValueError):
                    pass
            # raw_keys 里也可能有无密钥的 depot（键存在但值为 48 字节格式）
            for _rk in (getattr(plan, "raw_keys", None) or {}):
                try:
                    _id = int(_rk)
                    if _id != appid and _id not in out["depots"]:
                        out["depots"].append(_id)
                except (TypeError, ValueError):
                    pass
            _log(f"  SteamUnlock API: {len(plan.depots)} 个 depot", verbose)
    except Exception as exc:  # noqa: BLE001
        _log(f"  SteamUnlock API 不可用: {str(exc)[:60]}", verbose)

    # ── 组装 depot 列表 ──
    depots = list(mh3_depots)
    if api_config:
        for d in api_config.depots:
            if d.depotid and d.depotid not in depots:
                depots.append(d.depotid)

    # ── ③ 密钥: Sudama → 社区库 → ManifestHub3 ──
    try:
        sud = sudama.load()
    except Exception:  # noqa: BLE001
        sud = {}
    try:
        comm = depotkeys.load_community_keys()
    except Exception:  # noqa: BLE001
        comm = {}

    for dep in depots:
        k = sud.get(str(dep))
        if k and len(k) == 64:
            out["keys"][dep] = k.lower()
            if "sudama" not in out["sources"]["keys"]:
                out["sources"]["keys"].append("sudama")
            continue
        k = (comm or {}).get(str(dep))
        if k and len(k) == 64:
            out["keys"][dep] = k.lower()
            if "community" not in out["sources"]["keys"]:
                out["sources"]["keys"].append("community")
            continue
        k = (mh3.get("keys") or {}).get(dep) if mh3 else None
        if k and len(k) == 64:
            out["keys"][dep] = k.lower()
            if "manifesthub3" not in out["sources"]["keys"]:
                out["sources"]["keys"].append("manifesthub3")

    # ── 清单文件 ──
    if mh3 and mh3.get("manifests"):
        out["manifests"] = list(mh3["manifests"])
        out["sources"]["manifests"].append("manifesthub3")
    if mh3 and mh3.get("lua"):
        out["lua"] = mh3["lua"]
    # 名字
    if mh3 and mh3.get("meta"):
        meta = mh3["meta"]
        # ★ 暴露完整的 depot 清单给调用方 ——
        #   install() 需要它来找出"有清单但没密钥"的 depot，
        #   给它们写占位密钥（否则 Steam 报 Missing decryption key
        #   并取消整个下载任务）
        out["meta"] = meta
        for key in ("name", "common_name", "appname"):
            if isinstance(meta.get(key), str):
                out["name"] = meta[key]
                out["sources"]["name"].append("manifesthub3")
                break
    if not out["name"] and api_config is not None:
        nm = getattr(api_config, "name", None)
        if nm:
            out["name"] = nm
            out["sources"]["name"].append("steamunlock_api")

    # ManifestHub3 没清单时，用 API 的 gid 生成 Lua（清单靠 Steam 自己拿）
    if not out["lua"] and api_config:
        lines = [f"addappid({appid})"]
        for d in api_config.depots:
            if not d.depotid:
                continue
            k = out["keys"].get(d.depotid)
            if k:
                lines.append(f'addappid({d.depotid},0,"{k}")')
            else:
                lines.append(f"addappid({d.depotid})")
            if d.gid:
                lines.append(f'setManifestid({d.depotid},"{d.gid}")')
        out["lua"] = "\n".join(lines) + "\n"
        out["sources"]["manifests"].append("steamunlock_api_gids")

    _log(f"  → 最终: {len(out['keys'])} 个密钥, {len(out['manifests'])} 个清单", verbose)
    return out if (out["keys"] or out["manifests"] or out["lua"]) else None
