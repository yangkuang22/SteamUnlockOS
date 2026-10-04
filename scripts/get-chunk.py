#!/usr/bin/env python3
"""从 Valve 内容服务器取一个块（多主机重试 + 缓存）。"""
import sys, urllib.request, urllib.error, time
from pathlib import Path

HOSTS = ["cache1-hkg1.steamcontent.com","cache2-hkg1.steamcontent.com","cache3-hkg1.steamcontent.com",
         "cache4-hkg1.steamcontent.com","cache1-lax1.steamcontent.com","cache2-lax1.steamcontent.com",
         "cache10-lax1.steamcontent.com","steamcdn-a.akamaihd.net"]

def fetch(depotid: int, sha: str, cache_dir="cache/chunks", timeout=25, rounds=3) -> bytes:
    c = Path(cache_dir) / sha
    if c.is_file():
        return c.read_bytes()
    last = ""
    for r in range(rounds):
        for h in HOSTS:
            url = f"https://{h}/depot/{depotid}/chunk/{sha}"
            try:
                data = urllib.request.urlopen(urllib.request.Request(
                    url, headers={"User-Agent": "Valve/Steam HTTP Client 1.0"}), timeout=timeout).read()
                c.parent.mkdir(parents=True, exist_ok=True)
                c.write_bytes(data)
                print(f"  ✓ {h} → {len(data)}B")
                return data
            except urllib.error.HTTPError as e:
                last = f"{h}:HTTP{e.code}"
            except Exception as e:
                last = f"{h}:{type(e).__name__}"
        time.sleep(1.5)
    raise RuntimeError(f"取块失败 sha={sha[:16]}… 最后错误: {last}")

if __name__ == "__main__":
    d = fetch(int(sys.argv[1]), sys.argv[2])
    print(f"{len(d)} 字节")
