"""Steam 目录探测与本地数据读取（Linux / SteamOS 版）。

替代原程序的 `steam_helpers.get_steam_path()`（Windows 走注册表
`HKCU\\Software\\Valve\\Steam` → `SteamPath`），这里按 Linux 的实际布局探测。

本机实测（SteamOS 3.8 / ROG Ally Z1E）：
    ~/.steam/steam      -> 软链到 ~/.local/share/Steam
    ~/.steam/root       -> 同上
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import vdf

__all__ = [
    "SteamPaths",
    "find_steam",
    "load_depot_keys",
    "scan_depotcache",
    "installed_appids",
]

#: 候选根目录，按优先级排列（含 Flatpak / Snap 常见位置）
CANDIDATE_ROOTS = (
    "~/.steam/steam",
    "~/.steam/root",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/data/Steam",
    "~/snap/steam/common/.local/share/Steam",
)


class SteamNotFound(RuntimeError):
    """找不到可用的 Steam 安装。"""


@dataclass
class SteamPaths:
    root: Path
    config: Path
    depotcache: Path
    appcache: Path
    steamapps: Path
    extra_libraries: list[Path] = field(default_factory=list)

    @property
    def config_vdf(self) -> Path:
        return self.config / "config.vdf"

    @property
    def appinfo_vdf(self) -> Path:
        return self.appcache / "appinfo.vdf"

    @property
    def stplug_in(self) -> Path:
        return self.config / "stplug-in"

    def describe(self) -> str:
        lines = [f"Steam 根目录 : {self.root}"]
        lines.append(f"  config     : {self.config}")
        lines.append(f"  depotcache : {self.depotcache}")
        lines.append(f"  appcache   : {self.appcache}")
        lines.append(f"  steamapps  : {self.steamapps}")
        for lib in self.extra_libraries:
            lines.append(f"  额外库     : {lib}")
        return "\n".join(lines)


def _looks_like_steam(root: Path) -> bool:
    return (root / "config" / "config.vdf").is_file() or (root / "steamapps").is_dir()


def _extra_libraries(root: Path) -> list[Path]:
    """读 libraryfolders.vdf，拿到其它磁盘上的库（ACF 可能放在那里）。"""
    path = root / "config" / "libraryfolders.vdf"
    if not path.is_file():
        return []
    try:
        data = vdf.load(path)
    except Exception:
        return []
    libs: list[Path] = []
    folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
    for value in folders.values():
        if isinstance(value, dict) and "path" in value:
            libs.append(Path(value["path"]).expanduser())
    return [p for p in libs if p.is_dir()]


def find_steam(explicit: str | os.PathLike | None = None) -> SteamPaths:
    """定位 Steam 安装。显式路径优先，其次环境变量，最后扫候选目录。"""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("STEAM_ROOT"):
        candidates.append(Path(os.environ["STEAM_ROOT"]).expanduser())
    candidates.extend(Path(p).expanduser() for p in CANDIDATE_ROOTS)

    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            resolved = cand
        if _looks_like_steam(resolved):
            return SteamPaths(
                root=resolved,
                config=resolved / "config",
                depotcache=resolved / "depotcache",
                appcache=resolved / "appcache",
                steamapps=resolved / "steamapps",
                extra_libraries=_extra_libraries(resolved),
            )
    raise SteamNotFound(
        "找不到 Steam 安装目录。用 --steam-root 指定，例如 "
        "--steam-root ~/.local/share/Steam"
    )


def load_depot_keys(paths: SteamPaths) -> dict[int, str]:
    """从 config.vdf 读出 {depot_id: DecryptionKey}。

    对应原程序的 `steam_helpers.get_app_keys()`
    （docstring: "Parse Steam config.vdf for depot decryption keys."）。
    注意：这里的密钥是**明文 hex**，不走 RC4。
    """
    data = vdf.load(paths.config_vdf)
    node = data
    for key in ("InstallConfigStore", "Software", "Valve", "Steam", "depots"):
        if not isinstance(node, dict) or key not in node:
            # Valve/valve 大小写在个别版本里有差异，做一次兜底
            if isinstance(node, dict):
                lower = {k.lower(): v for k, v in node.items()}
                if key.lower() in lower:
                    node = lower[key.lower()]
                    continue
            return {}
        node = node[key]
    keys: dict[int, str] = {}
    if not isinstance(node, dict):
        return keys
    for depotid, info in node.items():
        if not str(depotid).isdigit() or not isinstance(info, dict):
            continue
        key = info.get("DecryptionKey")
        # 密钥长度：常见 32/64 hex，新版游戏可到 192 hex（64 字节 AES key）
        if isinstance(key, str) and re.fullmatch(r"[0-9a-fA-F]{32,256}", key):
            keys[int(depotid)] = key
    return keys


def scan_depotcache(paths: "SteamPaths", extra_dirs: "list[Path] | None" = None) -> "dict[int, list[tuple[int, str]]]":
    """扫 depotcache，返回 {depotid: [(manifest_gid, 文件名), ...]}（按 gid 升序）。

    文件名约定：`<depotid>_<manifest_gid>.manifest`。
    同一个 depot 会有多个版本的清单，调用方应取 gid 最大的那个（Steam 用递增 GID 标版本）。
    """
    result: dict[int, list[tuple[int, str]]] = {}
    dirs = [paths.depotcache] + list(extra_dirs or [])
    for d in dirs:
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if entry.suffix != ".manifest":
                continue
            m = re.fullmatch(r"(\d+)_(\d+)\.manifest", entry.name)
            if not m:
                continue
            result.setdefault(int(m.group(1)), []).append((int(m.group(2)), entry.name))
    for depotid in result:
        result[depotid].sort()
    return result


def best_manifests(extra_dirs: "list[Path] | None" = None, paths: "SteamPaths | None" = None):
    """每个 depot 只取 gid 最大的清单，返回 {depotid: (gid, 文件名)}。"""
    if paths is None:
        paths = find_steam()
    index: dict[int, tuple[int, str]] = {}
    for depotid, versions in scan_depotcache(paths, extra_dirs).items():
        gid, name = versions[-1]  # 已按 gid 升序
        index[depotid] = (gid, name)
    return index


def app_of_depot(depotid: int, known_apps: "set[int] | None" = None) -> int:
    """由 depotid 猜它属于哪个 appid。

    Steam 的约定：depot 的 id 通常以 appid 开头（DOOM 379720 的 depot 是 379720xxxx），
    但也有 depotid == appid 的情况（共享 depot / 工具）。
    这是**启发式**，仅用于本地无 ACF 时的兜底展示；正式来源是 appinfo.vdf 的 depots 段
    或服务端下发的 .lua。用户在 CLI 上永远是直接指定 appid。
    """
    s = str(depotid)
    if known_apps:
        # 已知 appid 里最长的前缀匹配优先
        hits = [a for a in known_apps if depotid == a or s.startswith(str(a))]
        if hits:
            return max(hits, key=lambda a: len(str(a)))
    # 没有候选时：depot 通常比 appid 多 3 位（379720 -> 3797205）
    if len(s) > 6:
        cand = int(s[: len(s) - 3])
        if 10 <= cand <= 4_000_000:
            return cand
    return depotid


def installed_appids(paths: SteamPaths) -> set[int]:
    """已安装（有 appmanifest_*.acf）的 appid 集合，含所有库目录。"""
    result: set[int] = set()
    dirs = [paths.steamapps] + [lib / "steamapps" for lib in paths.extra_libraries]
    for d in dirs:
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            m = re.fullmatch(r"appmanifest_(\d+)\.acf", entry.name)
            if m:
                result.add(int(m.group(1)))
    return result


def acf_path(paths: SteamPaths, appid: int) -> Path | None:
    """找一个 appid 的 ACF 路径（已安装才有）。"""
    dirs = [paths.steamapps] + [lib / "steamapps" for lib in paths.extra_libraries]
    for d in dirs:
        p = d / f"appmanifest_{appid}.acf"
        if p.is_file():
            return p
    return None
