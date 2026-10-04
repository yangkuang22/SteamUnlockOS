"""
ManifestHub3 数据源：一个 appid 一个 Git 分支，含 lua + key.vdf + 所有清单文件
仓库: steamtools-games/ManifestHub3 (62,000+ 分支)
"""
import base64, json, re, urllib.request, urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = "steamtools-games/ManifestHub3"
API = f"https://api.github.com/repos/{REPO}"
TIMEOUT = 30


import os

def _api_get(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.github+json",
    }
    # 用 token 可把限速从 60/小时 提到 5000/小时
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        for cand in (Path.home()/".config/SteamUnlockOS/github_token",
                     Path.home()/".github_token"):
            if cand.is_file():
                tok = cand.read_text().strip()
                break
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def branch_exists(appid: int) -> bool:
    """检查该 appid 的分支是否存在"""
    try:
        with _api_get(f"{API}/branches/{appid}") as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return False


def list_files(appid: int) -> List[dict]:
    """列出分支里的所有文件"""
    try:
        with _api_get(f"{API}/contents/?ref={appid}") as r:
            d = json.load(r)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def fetch_file(appid: int, name: str) -> Optional[bytes]:
    """下载分支里的单个文件"""
    try:
        with _api_get(f"{API}/contents/{name}?ref={appid}") as r:
            d = json.load(r)
            if "content" in d:
                return base64.b64decode(d["content"])
    except Exception:
        pass
    return None


def fetch_all(appid: int):
    """
    抓取整个分支。返回 dict:
      lua: str           官方 Lua 配置
      key_vdf: str       key.vdf 内容（Steam 格式）
      keys: {depot: key} 从 key.vdf 解析
      manifests: [(depot, gid, bytes)]  清单文件
      meta: dict         元数据（名称等）
      files: [文件名]
    """
    files = list_files(appid)
    if not files:
        return None
    names = [f["name"] for f in files]
    out = {"lua": None, "key_vdf": None, "keys": {}, "manifests": [], "meta": None, "files": names}

    # lua
    if f"{appid}.lua" in names:
        b = fetch_file(appid, f"{appid}.lua")
        if b: out["lua"] = b.decode("utf-8", "replace")
    # key.vdf
    if "key.vdf" in names:
        b = fetch_file(appid, "key.vdf")
        if b:
            out["key_vdf"] = b.decode("utf-8", "replace")
            for m in re.finditer(r'"(\d+)"\s*\{\s*"DecryptionKey"\s*"([0-9a-fA-F]+)"', out["key_vdf"]):
                out["keys"][int(m.group(1))] = m.group(2)
    # 元数据
    if f"{appid}.json" in names:
        b = fetch_file(appid, f"{appid}.json")
        if b:
            try: out["meta"] = json.loads(b)
            except Exception: pass
    # 清单文件：<depot>_<gid>.manifest
    for n in names:
        m = re.match(r"^(\d+)_(\d+)\.manifest$", n)
        if not m: continue
        b = fetch_file(appid, n)
        if b and len(b) > 100:
            out["manifests"].append((int(m.group(1)), int(m.group(2)), b))
    return out


def public_gids(lua: str) -> Dict[int, int]:
    """从官方 lua 里解析 depot → gid"""
    out = {}
    for m in re.finditer(r'setManifestid\((\d+),\s*"(\d+)"\)', lua or "", re.I):
        out[int(m.group(1))] = int(m.group(2))
    return out
