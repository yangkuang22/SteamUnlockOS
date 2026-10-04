"""服务端客户端 —— 复刻原程序的数据管道（`GET {API}GetAppinfo/<appid>`）。

逆向证据（见 su_analysis/RECON_RC4.md §C）与**活体验证**：

    GET http://auth1.caigamer.cn/GetAppinfo/<appid>
      -> 原始字节
      -> rc4(raw, RC4_KEY)            # 只有一层 RC4，固定密钥无 IV
      -> .decode("utf-8")
      -> ast.literal_eval(...)        # 注意：是 **Python 字典字面量**，不是 JSON
      -> {'Key': <VDF 文本>, 'appinfo': <VDF 文本>, 'config': <JSON 文本>}

    其中：
      Key      -> vdf.loads  -> {"depots": {"<depotid>": {"DecryptionKey": "<hex>"}}}
      appinfo  -> vdf.loads  -> 标准 appinfo 结构，含 common/name、depots/<id>/manifests/public/{gid,size}
      config   -> json.loads -> {"appId":…, "depots":[…], "dlcs":[…], "app_token":…}

实测 appid 379720（DOOM）返回 34,293 字节，解出 12 个 depot + 5 个 DLC + 全部密钥。
"""

from __future__ import annotations

import ast
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import rc4, vdf

__all__ = ["API_BASE", "AUTH_BASE", "ServerPayload", "fetch", "parse_payload", "install_plan"]

API_BASE = "http://auth1.caigamer.cn/"
AUTH_BASE = "http://auth.caigamer.cn/"
TIMEOUT = 30


@dataclass
class DepotInfo:
    depotid: int
    gid: int | None
    size: int
    key: str | None
    oslist: str = ""


@dataclass
class ServerPayload:
    """一个 appid 的全部入库数据。"""

    appid: int
    name: str
    depots: list[DepotInfo] = field(default_factory=list)
    dlcs: list[int] = field(default_factory=list)
    app_token: str | None = None
    raw_keys: dict[int, str] = field(default_factory=dict)

    @property
    def total_size(self) -> int:
        return sum(d.size for d in self.depots)

    def describe(self) -> str:
        gb = self.total_size / (1024**3)
        lines = [
            f"appid      : {self.appid}",
            f"名称       : {self.name}",
            f"depot 数量 : {len(self.depots)}（合计 {gb:.2f} GB）",
            f"DLC        : {self.dlcs if self.dlcs else '无'}",
            f"app_token  : {self.app_token or '无'}",
            f"密钥       : {sum(1 for d in self.depots if d.key)}/{len(self.depots)} 个 depot 有密钥",
        ]
        return "\n".join(lines)


def fetch(appid: int, *, base: str = API_BASE, timeout: int = TIMEOUT) -> bytes:
    """从服务端拉取密文原始字节（纯 stdlib，不依赖 requests）。"""
    url = f"{base}GetAppinfo/{appid}"
    req = urllib.request.Request(url, headers={"User-Agent": "SteamUnlockOS/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise urllib.error.HTTPError(url, resp.status, "非 200", resp.headers, None)
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"服务端返回 {exc.code}（appid {appid} 可能不存在）") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"连不上服务端 {url}: {exc.reason}") from exc


def parse_payload(raw: bytes) -> ServerPayload:
    """解密并解析服务端响应。"""
    text = rc4.rc4(rc4.RC4_KEY, raw).decode("utf-8")
    try:
        data = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(
            f"服务端数据解密后不是 Python 字面量（可能服务端改了协议或需要激活态）: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"服务端返回的结构不对: {type(data).__name__}")

    keys_vdf = vdf.loads(data.get("Key", "")) if data.get("Key") else {}
    info = vdf.loads(data.get("appinfo", "")) if data.get("appinfo") else {}
    cfg = json.loads(data.get("config", "{}")) if data.get("config") else {}

    appid = int(cfg.get("appId") or info.get("appid") or 0)
    common = info.get("common", {}) if isinstance(info.get("common"), dict) else {}
    name = common.get("name", "") or f"appid {appid}"

    raw_keys: dict[int, str] = {}
    depots_node = keys_vdf.get("depots", {}) if isinstance(keys_vdf, dict) else {}
    if isinstance(depots_node, dict):
        for depotid_str, info_node in depots_node.items():
            if str(depotid_str).isdigit() and isinstance(info_node, dict):
                key = info_node.get("DecryptionKey")
                if isinstance(key, str):
                    raw_keys[int(depotid_str)] = key

    depots: list[DepotInfo] = []
    info_depots = info.get("depots", {}) if isinstance(info.get("depots"), dict) else {}
    listed = cfg.get("depots") or []
    ordered_ids: list[int] = []
    for item in listed:
        try:
            ordered_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    # 服务端没列全时，补上 appinfo 里有清单的 depot
    for depotid_str, node in info_depots.items():
        if not str(depotid_str).isdigit() or not isinstance(node, dict):
            continue
        if node.get("manifests", {}).get("public"):
            did = int(depotid_str)
            if did not in ordered_ids:
                ordered_ids.append(did)

    for depotid in ordered_ids:
        node = info_depots.get(str(depotid), {}) if isinstance(info_depots, dict) else {}
        manifests = node.get("manifests", {}) if isinstance(node, dict) else {}
        public = manifests.get("public", {}) if isinstance(manifests, dict) else {}
        gid = public.get("gid")
        size = public.get("size", 0)
        oslist = ""
        config_node = node.get("config") if isinstance(node, dict) else None
        if isinstance(config_node, dict):
            oslist = config_node.get("oslist", "")
        depots.append(
            DepotInfo(
                depotid=depotid,
                gid=int(gid) if gid else None,
                size=int(size) if str(size).isdigit() else 0,
                key=raw_keys.get(depotid),
                oslist=oslist,
            )
        )

    dlcs: list[int] = []
    for item in cfg.get("dlcs") or []:
        try:
            dlcs.append(int(item))
        except (TypeError, ValueError):
            continue

    token = cfg.get("app_token")
    return ServerPayload(
        appid=appid,
        name=name,
        depots=depots,
        dlcs=dlcs,
        app_token=str(token) if token else None,
        raw_keys=raw_keys,
    )


def install_plan(appid: int, *, cache_dir: Path | None = None) -> ServerPayload:
    """拉取并解析一个 appid 的入库数据；cache_dir 给定时同时缓存原始响应。"""
    raw = fetch(appid)
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"GetAppinfo_{appid}.bin").write_bytes(raw)
    return parse_payload(raw)
