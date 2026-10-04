"""
depot 密钥获取：多源聚合（SteamUnlock 服务端 + 社区密钥库）
"""
import json, urllib.request, re
from pathlib import Path
from typing import Dict, Optional

MANIFESTHUB_URLS = [
    "https://cdn.jsdelivr.net/gh/SteamAutoCracks/ManifestHub@HEAD/depotkeys.json",
    "https://ghproxy.net/https://raw.githubusercontent.com/SteamAutoCracks/ManifestHub/HEAD/depotkeys.json",
]
CACHE = Path.home() / ".cache/suos/depotkeys.json"


def load_community_keys(force: bool = False) -> Dict[str, str]:
    """加载社区密钥库（ManifestHub，17 万个 depot）"""
    if CACHE.is_file() and not force:
        try:
            return json.loads(CACHE.read_text())
        except Exception:
            pass
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    for url in MANIFESTHUB_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=180).read()
            if len(data) > 100000:
                CACHE.write_bytes(data)
                return json.loads(data)
        except Exception:
            continue
    return {}


def key_for(depotid: int, community: Optional[Dict[str, str]] = None) -> Optional[str]:
    """查单个 depot 的 32 字节密钥（64 hex）。返回 None 表示没有。"""
    if community is None:
        community = load_community_keys()
    k = community.get(str(depotid))
    if k and len(k) == 64:
        return k
    return None


def keys_for_app(depots, community: Optional[Dict[str, str]] = None):
    """
    depots: [(depotid, gid, size), ...] 或 DepotInfo 列表
    返回 (keys, missing) —— keys: {depotid: hexkey}, missing: [depotid, ...]
    """
    if community is None:
        community = load_community_keys()
    keys, missing = {}, []
    for d in depots:
        depid = getattr(d, "depotid", None) or d[0]
        k = key_for(depid, community)
        if k:
            keys[depid] = k
        elif depid:  # 空密钥 depot（如 40 字节的小 depot）不需要
            missing.append(depid)
    return keys, missing
