"""Sudama 密钥库 —— 239,946 条 depot 解密密钥

来源发现: 读开源项目 cai-install (zhouchentao666/Fluent-Install) 的
backend/cai_backend.py 第 1838 行找到的端点。

它的优势（实测）:
  · 239,946 条，其中 26,921 条是社区库（288,381 条）没有的
  · 包含 SteamUnlock 有、而 ManifestHub3/ManifestAutoUpdate 都没有的新游戏
    （例: 命运石之门 RE:BOOT 4012811 / 杀戮尖塔2 2868841）

缓存策略: 24 小时（和 cai-install 一致）
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

URL = "https://api.993499094.xyz/depotkeys.json"
TIMEOUT = 120
CACHE_TTL = 7 * 24 * 3600  # 7 天（网络不稳，延长缓存）

_CACHE_DIR = Path(os.environ.get("SUOS_CACHE", str(Path.home() / ".cache/suos")))
_CACHE = _CACHE_DIR / "sudama_depotkeys.json"
_mem: dict | None = None


def _load_cache() -> dict | None:
    if not _CACHE.is_file():
        return None
    try:
        raw = json.loads(_CACHE.read_text())
    except Exception:
        return None
    ts = raw.get("timestamp", 0)
    if time.time() - ts > CACHE_TTL:
        return None
    data = raw.get("data")
    return data if isinstance(data, dict) else None


def _save_cache(data: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"timestamp": time.time(), "data": data}))
    tmp.replace(_CACHE)


def load(force: bool = False, verbose: bool = False) -> dict:
    """返回 {depot_id_str: 64hex_key}。带 24h 缓存 + 过期兜底。"""
    global _mem
    if _mem is not None and not force:
        return _mem
    if not force:
        cached = _load_cache()
        if cached:
            if verbose:
                print(f"  Sudama: 用缓存（{len(cached):,} 条）")
            _mem = cached
            return cached
    if verbose:
        print(f"  Sudama: 从 {URL} 下载…")
    last_err = None
    try:
        from . import fetch as _fetch
        data = _fetch.fetch_json(URL, _CACHE, verbose=verbose, timeout=25)
        if isinstance(data, dict) and data:
            _save_cache(data)
            _mem = data
            return data
    except Exception as exc:  # noqa: BLE001
        last_err = exc
    # 兜底：老的逐次重试
    for attempt in range(2):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("返回不是 JSON 对象")
            _save_cache(data)
            if verbose:
                print(f"  Sudama: 下载完成（{len(data):,} 条）")
            _mem = data
            return data
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2)
    # 兜底：用过期缓存
    if _CACHE.is_file():
        try:
            raw = json.loads(_CACHE.read_text())
            if isinstance(raw.get("data"), dict):
                if verbose:
                    print("  Sudama: 下载失败，用过期缓存兜底")
                _mem = raw["data"]
                return raw["data"]
        except Exception:
            pass
    if verbose:
        print(f"  Sudama: 全部失败 ({last_err})")
    _mem = {}
    return {}


def key_for(depot_id: int) -> str | None:
    d = load()
    return d.get(str(depot_id))


def keys_for_app(appid: int) -> dict:
    """key.vdf 兼容的 {depot: key}；这里只能给出该 appid 自身的条目。"""
    d = load()
    out = {}
    if str(appid) in d:
        out[appid] = d[str(appid)]
    return out
