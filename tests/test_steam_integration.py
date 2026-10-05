"""针对真实 Steam 数据的集成测试（有 Steam 就全跑，没有就 skip）。

运行：cd ~/steam-toolkit && python3 tests/test_steam_integration.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from suos import appinfo, rc4, slsconfig, steam, vdf  # noqa: E402


def _have_steam() -> bool:
    try:
        steam.find_steam()
        return True
    except steam.SteamNotFound:
        return False


@unittest.skipUnless(_have_steam(), "本机没有 Steam")
class TestSteamDetection(unittest.TestCase):
    def test_paths_resolved(self):
        p = steam.find_steam()
        self.assertTrue(p.config.is_dir(), "config 目录应存在")
        self.assertTrue(p.config_vdf.is_file(), "config.vdf 应存在")

    def test_depot_keys(self):
        p = steam.find_steam()
        keys = steam.load_depot_keys(p)
        self.assertGreater(len(keys), 20, "应该能读出几十个 depot 密钥")
        for depotid, key in list(keys.items())[:5]:
            self.assertIsInstance(depotid, int)
            self.assertRegex(key, r"^[0-9a-fA-F]{32,64}$")

    def test_installed_apps(self):
        p = steam.find_steam()
        self.assertGreater(len(steam.installed_appids(p)), 0)

    def test_depotcache_scan_picks_max_gid(self):
        """同一 depotid 有多版本清单时，必须取 gid 最大的那个。"""
        p = steam.find_steam()
        raw = steam.scan_depotcache(p)
        self.assertGreater(len(raw), 0)
        multi = {d: v for d, v in raw.items() if len(v) > 1}
        if not multi:
            self.skipTest("本机没有多版本清单的 depot")
        best = steam.best_manifests(paths=p)
        for depotid, versions in multi.items():
            max_gid = max(g for g, _ in versions)
            self.assertEqual(best[depotid][0], max_gid, f"depot {depotid} 没取到最大 gid")

    def test_acf_parse(self):
        """能解析已安装游戏的 ACF 并读出 depot。"""
        p = steam.find_steam()
        installed = sorted(steam.installed_appids(p))
        if not installed:
            self.skipTest("没有已安装游戏")
        checked = 0
        for appid in installed:
            acf = steam.acf_path(p, appid)
            if acf is None:
                continue
            data = vdf.load(acf)
            self.assertIn("AppState", data, f"{acf.name} 缺 AppState")
            deps = data["AppState"].get("InstalledDepots")
            if isinstance(deps, dict) and deps:
                checked += 1
                self.assertTrue(all(str(k).isdigit() for k in deps))
        self.assertGreater(checked, 0, "没有解析出任何 InstalledDepots")


class TestSLSConfigReadonly(unittest.TestCase):
    """SLSConfig 现在是只读视图（入库写入由 webui_core 负责，直接写 config.toml）。
    这里验证它能正确读出 config.toml 里的 AppIds。"""

    def test_reads_owned_from_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            toml = Path(tmp) / "config.toml"
            toml.write_text(
                "AppIds = [440, 379720]\nAdditionalApps = [730]\n",
                encoding="utf-8",
            )
            cfg = slsconfig.SLSConfig(toml).load()
            self.assertTrue(cfg.exists())
            self.assertEqual(cfg.owned(), {440, 379720, 730})

    def test_missing_config_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = slsconfig.SLSConfig(Path(tmp) / "config.toml").load()
            self.assertFalse(cfg.exists())
            self.assertEqual(cfg.owned(), set())


class TestAppOfDepot(unittest.TestCase):
    def test_known_prefix_match(self):
        # depotid == appid 的情况（共享 depot / 工具）
        self.assertEqual(steam.app_of_depot(379720), 379720)
        self.assertEqual(steam.app_of_depot(228990), 228990)

    def test_unknown_long_depot_drops_three_digits(self):
        # 无候选时：depot 比 appid 多 3 位
        self.assertEqual(steam.app_of_depot(3797205), 3797)

    def test_with_candidates_prefers_longest(self):
        cands = {3797, 379720, 3797205}
        self.assertEqual(steam.app_of_depot(3797205, cands), 3797205)


@unittest.skipUnless(_have_steam(), "本机没有 Steam")
class TestAppInfoParser(unittest.TestCase):
    def test_parses_real_file_without_crashing(self):
        """解析器至少要能跑完真实 appinfo.vdf 并拿到条目（哪怕标题提取还在路上）。"""
        p = steam.find_steam()
        if not p.appinfo_vdf.is_file():
            self.skipTest("没有 appinfo.vdf")
        ai = appinfo.AppInfoFile.load(p.appinfo_vdf)
        self.assertIsInstance(ai.apps, dict)
        self.assertGreater(len(ai.keys), 100, "字符串表应该能读出来（实测 6910 项）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
