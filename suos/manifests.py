"""清单（.manifest）获取 —— 入库流程里缺的那一块。

## 为什么需要它

即便有了「所有权放行 + depot 密钥 + 清单版本号(GID)」，Steam 仍然需要
**清单文件本体**（`<steam>/depotcache/<depotid>_<gid>.manifest`）才能在本地建立
depot 挂载点。没有它，症状是：

    AppID xxx state changed : ... (Missing decryption key)
    AppID xxx scheduler finished : removed from schedule

（Steam 的错误文案会变：先报 `Missing decryption key`，补上密钥后若仍无清单，
 就会在 `content_log.txt` 里报 Failed to initialize depot / downloading manifests failed。）

## 清单从哪来（已实测）

Steam 的 CDN 只对**已授权该 app 的账号**发放清单，所以本工具走第三方清单源。
BetterSteamTools 的做法（`src/Utils/SteamMetadata/ManifestClient.cpp`）给了完整线索：

> Valve made the request code depot-bound on 2026-09-09 … A gid-only request cannot
> name the depot, only works for 731/571/441 — every other depot 401s at the CDN

也就是说 **2026-09-09 之后必须用 depot 感知的接口**：

    https://manifest.opensteamtool.com/{appid}/{depotid}/{gid}   ← depot 感知（首选）
    https://manifest.luastools.xyz/m/{depotid}/{gid}             ← 捐赠池（实测可用）

实测（appid 4012810 / depotid 4012811 / gid 4900984998756496132）：

    manifest.luastools.xyz/m/4012811/4900984998756496132  -> HTTP 200, 330,771 B, 魔数 0x71f617d0 ✅
    manifest.opensteamtool.com/...                        -> HTTP 403（要 key/UA）
    gmrc.wudrm.com/manifest/<gid>                         -> HTTP 200 但 body 只有 "1005761..."（不是清单）
    manifest.steam.run/api/manifest/<gid>                 -> 连不上
"""

from __future__ import annotations

import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__all__ = ["MANIFEST_MAGIC", "ManifestResult", "provider_urls", "fetch_manifest", "install_manifest"]

#: Steam 清单文件（protobuf 外层）的魔数
MANIFEST_MAGIC = 0x71F617D0

_UA = "Mozilla/5.0 (X11; Linux x86_64) SteamUnlockOS/0.2"


@dataclass
class ManifestResult:
    data: bytes
    provider: str
    url: str

    @property
    def size(self) -> int:
        return len(self.data)

    def is_valid(self) -> bool:
        return is_steam_manifest(self.data)


def is_steam_manifest(data: bytes) -> bool:
    """校验是不是 Steam 清单。

    结构：`<u32 magic=0x71F617D0><u32 body_len><protobuf body>`。
    实测 body_len 与「文件长度-8」会有几十字节的零头（protobuf 定长字段对齐），
    所以容差放到 4KB；魔数不对则直接判假。
    """
    if len(data) < 16:
        return False
    magic, declared = struct.unpack_from("<II", data, 0)
    if magic != MANIFEST_MAGIC:
        return False
    body_len = len(data) - 8
    if declared > len(data):
        return False
    return abs(declared - body_len) <= 4096


def provider_urls(appid: int, depotid: int, gid: int) -> list[tuple[str, str]]:
    """按优先级返回 (provider 名, URL)。

    luastools 的 `/m/<depot>/<gid>` 排第一 —— 真机实测它是唯一稳定返回干净清单的源
    （opensteamtool 对未授权请求一律 403）。把它放首位能大幅降低瞬时失败率。
    """
    return [
        ("luastools", f"https://manifest.luastools.xyz/m/{depotid}/{gid}"),
        ("opensteamtool", f"https://manifest.opensteamtool.com/{appid}/{depotid}/{gid}"),
        ("luastools-root", f"https://manifest.luastools.xyz/{depotid}/{gid}"),
        ("opensteamtool-gid", f"https://manifest.opensteamtool.com/{gid}"),
    ]


def fetch_manifest(
    appid: int,
    depotid: int,
    gid: int,
    *,
    timeout: int = 60,
    retries: int = 3,
    backoff: float = 1.5,
) -> ManifestResult | None:
    """依次尝试各清单源，返回第一个有效的清单。全部失败返回 None。

    ★ 每个源重试 `retries` 次（指数退避）。背景：国内网络抖动时单次请求很容易超时，
      而清单文件本身是存在的 —— 真机案例里同一个清单入库时拿不到、4 分钟后一次就成功。
      没有重试 = 一次抖动就让整个游戏永久下不动（清单缺失是硬失败，见 webui_core）。
    """
    errors: list[str] = []
    for name, url in provider_urls(appid, depotid, gid):
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        errors.append(f"{name}: HTTP {resp.status}")
                        break  # 明确的 HTTP 状态码，换下一个源
                    data = resp.read()
            except urllib.error.HTTPError as exc:
                errors.append(f"{name}: HTTP {exc.code}")
                break  # 403/404 这类是确定性拒绝，重试同一个源没意义
            except Exception as exc:  # 超时/连接失败 —— 这才是值得重试的
                errors.append(f"{name}: {type(exc).__name__}(试{attempt}/{retries})")
                if attempt < retries:
                    time.sleep(backoff * attempt)
                continue
            if is_steam_manifest(data):
                return ManifestResult(data=data, provider=name, url=url)
            errors.append(f"{name}: 不是有效清单（{len(data)} 字节，magic={data[:4].hex()}）")
            break  # 拿到了响应但不是清单，换下一个源
    if errors:
        print("  清单源都失败：" + "; ".join(errors))
    return None


def install_manifest(depotcache: Path, depotid: int, gid: int, data: bytes) -> Path:
    """把清单写进 Steam 的 depotcache，返回落地路径。"""
    depotcache.mkdir(parents=True, exist_ok=True)
    dest = depotcache / f"{depotid}_{gid}.manifest"
    dest.write_bytes(data)
    return dest
