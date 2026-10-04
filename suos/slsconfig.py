"""SLSsteam 配置读写（`~/.config/SLSsteam/config.yaml`）。

为什么需要这一层：SLSsteam 的"拥有权"完全由配置驱动——源码
`Apps::checkAppOwnership()` 里就一句 `if (!g_config.isAddedAppId(appId)) return false;`，
`isAddedAppId` 读的是 `AppIds` + `AdditionalApps` 两个列表。
所以把 appid 写进配置 = 入库（等价于原程序注入 Console.dll 后调 `AddAppid`）。

字段对照（原 SteamTools Lua → SLSsteam config.yaml）：

    addappid(<appid>)                  -> AppIds / AdditionalApps
    addappid(<depotid>,1,"<key>")      -> CDKeys[depotid]
    addtoken(<appid>,"<token>")        -> AppTokens[appid]
    setManifestid(<depot>,"<gid>",<sz>) -> ManifestIds[depot]（SteamTools 另有 .manifest 落盘）

设计取舍：**只改指定段落，其余原样保留**。写之前先备份，避免"调一次工具毁掉用户配置"。
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

__all__ = ["SLSConfig", "SLS_DIR", "CONFIG_PATH", "find_slssteam"]

SLS_DIR = Path.home() / ".config" / "SLSsteam"
CONFIG_PATH = SLS_DIR / "config.yaml"
PLUGIN_DIR = SLS_DIR / "plugins"

#: 各段的默认值（首次生成配置时用）
_DEFAULTS: dict[str, object] = {
    "DisableFamilyShareLock": "yes",
    "UseWhitelist": "no",
    "AppIds": [],
    "AdditionalApps": [],
    "ManifestIds": {},
    "CDKeys": {},
    "AppTokens": {},
    "DepotBlacklist": [],
    "SafeMode": "yes",  # SteamOS 上官方强烈建议开启
    "NotifyInit": "yes",
    "Plugins": "no",
    "DisableCloud": "yes",
    "LogLevels": "0xff",
}


def find_slssteam() -> dict[str, object]:
    """探测 SLSsteam 是否已安装（两个 .so 是否存在）。"""
    candidates = [
        Path.home() / ".local/share/SLSsteam",
        Path.home() / ".steam/steam",
        Path.home() / ".local/share/Steam",
    ]
    found: dict[str, object] = {"installed": False, "dirs": [], "lib": None, "inject": None}
    for d in candidates:
        lib = d / "SLSsteam.so"
        inj = d / "library-inject.so"
        if lib.is_file() or inj.is_file():
            found["installed"] = True
            found["lib"] = str(lib) if lib.is_file() else found["lib"]
            found["inject"] = str(inj) if inj.is_file() else found["inject"]
            found["dirs"].append(str(d))  # type: ignore[union-attr]
    return found


class SLSConfig:
    """SLSsteam 的 config.yaml 读写。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else CONFIG_PATH
        self.data: dict = {}
        self.raw: str = ""
        # ★ SLSsteam 从某个版本起改用 config.toml（YAML 被弃用）。
        #   owned() 等只读接口需要能看到 TOML 里的 AppIds，
        #   否则会误报"已声明拥有 0 个"。
        self.toml_path: Path | None = None
        if path is None:
            cand = CONFIG_PATH.with_suffix(".toml")
            if cand.is_file():
                self.toml_path = cand

    # ---------------------------------------------------------------- 读
    def load(self) -> "SLSConfig":
        if self.path.is_file():
            self.raw = self.path.read_text(encoding="utf-8", errors="replace")
            loaded = yaml.safe_load(self.raw)
            self.data = loaded if isinstance(loaded, dict) else {}
        else:
            self.raw = ""
            self.data = {}
        return self

    def exists(self) -> bool:
        """配置存在吗（YAML 或 TOML 任一存在即为真）"""
        if self.path.is_file():
            return True
        return bool(self.toml_path and self.toml_path.is_file())

    # ---------------------------------------------------------------- 写
    def backup(self, backup_dir: Path) -> Path | None:
        """把现有配置备份到指定目录，返回备份路径（无配置则返回 None）。"""
        if not self.path.is_file():
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = backup_dir / f"config.yaml.{stamp}.bak"
        shutil.copy2(self.path, dest)
        return dest

    def _seed_defaults(self) -> None:
        for key, value in _DEFAULTS.items():
            self.data.setdefault(key, value)

    def add_app(self, appid: int, *, additional: bool = False) -> None:
        """把 appid 加入配置列表。additional=True 时进 AdditionalApps。"""
        self._seed_defaults()
        key = "AdditionalApps" if additional else "AppIds"
        current = self.data.get(key) or []
        if not isinstance(current, list):
            current = []
        if appid not in current:
            current.append(appid)
        self.data[key] = sorted({int(x) for x in current})

    def set_manifest(self, depotid: int, gid: int) -> None:
        self._seed_defaults()
        manifests = self.data.get("ManifestIds") or {}
        if not isinstance(manifests, dict):
            manifests = {}
        manifests[int(depotid)] = int(gid)
        self.data["ManifestIds"] = dict(sorted(manifests.items()))

    def set_cdkey(self, depotid: int, key: str) -> None:
        self._seed_defaults()
        keys = self.data.get("CDKeys") or {}
        if not isinstance(keys, dict):
            keys = {}
        keys[int(depotid)] = key
        self.data["CDKeys"] = dict(sorted(keys.items()))

    def set_token(self, appid: int, token: str) -> None:
        self._seed_defaults()
        tokens = self.data.get("AppTokens") or {}
        if not isinstance(tokens, dict):
            tokens = {}
        tokens[int(appid)] = token
        self.data["AppTokens"] = dict(sorted(tokens.items()))

    def save(self) -> Path:
        """写出配置（保持人类可读、带注释头）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# 由 Steam Toolkit 生成/更新 —— 数据来自 SteamUnlock (Windows 版) 的数据管道\n"
            "# 本文件是 SLSsteam 的配置：AppIds 即“拥有权声明”\n"
            f"# 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        body = yaml.safe_dump(
            self.data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
        self.path.write_text(header + body, encoding="utf-8")
        return self.path

    # ---------------------------------------------------------------- 查询
    def owned(self) -> set[int]:
        """已声明拥有的 appid（合并 YAML 与 TOML 两处来源）。"""
        out: set[int] = set()
        for key in ("AppIds", "AdditionalApps"):
            value = self.data.get(key) or []
            if isinstance(value, list):
                out.update(int(x) for x in value if str(x).isdigit())
        # TOML（新版 SLSsteam 用的格式）
        if self.toml_path and self.toml_path.is_file():
            try:
                txt = self.toml_path.read_text(encoding="utf-8", errors="replace")
                for key in ("AppIds", "AdditionalApps"):
                    m = re.search(rf"^{key}\s*=\s*\[([^\]]*)\]", txt, re.M)
                    if not m:
                        continue
                    for x in m.group(1).split(","):
                        x = x.strip()
                        if x.isdigit():
                            out.add(int(x))
            except Exception:
                pass
        return out
