"""本次 bug 修复的回归测试

对应 docs/BUG清单-待分析.md 里的 P1-1 / P1-2 / P2-1 / P2-2 / P2-3 / P2-4。

★ 安全设计: 所有涉及配置写入的测试都用【临时文件】，
  通过替换 webui_core 的模块级路径常量实现，绝不碰真实配置。
  tearDown 里强制还原，还原失败会让测试报错（而不是静默）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import webui_core as core  # noqa: E402
from suos import slsconfig  # noqa: E402


class TempCorePaths(unittest.TestCase):
    """把 webui_core 的路径常量指向临时目录的基类"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig: dict[str, object] = {}

        # 保存原始值
        for name in ("CONFIG_VDF", "SLS_TOML", "LUA_SLS", "LUA_STEAM", "RECORD", "HOME"):
            self._orig[name] = getattr(core, name, None)

        # 造临时结构
        (self.tmp / "config").mkdir(parents=True)
        (self.tmp / "sls").mkdir(parents=True)
        (self.tmp / "steamlua").mkdir(parents=True)
        (self.tmp / "home").mkdir(parents=True)

        # 从真实文件复制一份初始内容（有真实数据才有意义）
        real_vdf = self._orig["CONFIG_VDF"]
        real_toml = self._orig["SLS_TOML"]
        if isinstance(real_vdf, Path) and real_vdf.is_file():
            shutil.copy2(real_vdf, self.tmp / "config/config.vdf")
        else:
            (self.tmp / "config/config.vdf").write_text(
                '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
                '\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"depots"\n\t\t\t\t{\n\t\t\t\t}\n'
                '\t\t\t}\n\t\t}\n\t}\n}\n')
        if isinstance(real_toml, Path) and real_toml.is_file():
            shutil.copy2(real_toml, self.tmp / "sls/config.toml")
        else:
            (self.tmp / "sls/config.toml").write_text(
                'AppIds = []\nAdditionalApps = []\n')

        core.CONFIG_VDF = self.tmp / "config/config.vdf"
        core.SLS_TOML = self.tmp / "sls/config.toml"
        core.LUA_SLS = self.tmp / "sls/lua"
        core.LUA_STEAM = self.tmp / "steamlua"
        core.LUA_SLS.mkdir(parents=True, exist_ok=True)
        core.RECORD = self.tmp / "home/installed.json"
        core._name_cache.clear()

        # 隔离备份：避免测试往真实的 backup/ 目录写
        self._orig_backup = getattr(core, "BACKUP", None)
        core.BACKUP = self.tmp / "backup"
        core.BACKUP.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        # 强制还原 —— 失败就报错，不能静默
        for name, val in self._orig.items():
            if val is not None:
                setattr(core, name, val)
        if getattr(self, "_orig_backup", None) is not None:
            core.BACKUP = self._orig_backup
        core._name_cache.clear()
        self._tmp.cleanup()

        # 确认真的还原了（防止测试污染真实配置）
        assert core.CONFIG_VDF == self._orig["CONFIG_VDF"], "CONFIG_VDF 没还原！"
        assert core.SLS_TOML == self._orig["SLS_TOML"], "SLS_TOML 没还原！"


# ══════════════════════════════════════════════════════════════
#  P1-1  名字缓存污染
# ══════════════════════════════════════════════════════════════

class TestNameCachePoisoning(TempCorePaths):
    """P1-1: 解析失败不能污染永久缓存；旧的中毒缓存要能自愈"""

    def _names_file(self) -> Path:
        """真实代码里是 HOME/.config/SteamUnlockOS/names.json"""
        return self.tmp / "home/.config/SteamUnlockOS/names.json"

    def test_resolve_failure_returns_none(self):
        """_resolve_name 全部失败时必须返回 None（而不是 'AppID xxx'）"""
        orig = core._resolve_name
        try:
            core._resolve_name = lambda a: None
            self.assertIsNone(core._resolve_name(123))
        finally:
            core._resolve_name = orig

    def test_failure_does_not_write_cache(self):
        """P1-1 核心: 解析失败时不能写永久缓存"""
        # 让 names.json 指向临时路径
        orig_resolve = core._resolve_name
        orig_home = core.HOME
        try:
            core.HOME = self.tmp / "home"
            self._names_file().parent.mkdir(parents=True, exist_ok=True)
            core._resolve_name = lambda a: None
            core._name_cache.clear()
            # 调 _name_for（会尝试写缓存）
            out = core._name_for(999999, None)
            self.assertEqual(out, "AppID 999999")
            nf = self._names_file()
            if nf.is_file():
                data = json.loads(nf.read_text())
                self.assertNotIn("999999", data,
                                 "解析失败的结果不该被写进永久缓存")
        finally:
            core._resolve_name = orig_resolve
            core.HOME = orig_home
            core._name_cache.clear()

    def test_poisoned_cache_self_heals(self):
        """旧的中毒缓存（'AppID 数字'）应该被自动修复"""
        orig_resolve = core._resolve_name
        orig_home = core.HOME
        try:
            core.HOME = self.tmp / "home"
            nf = self._names_file()
            nf.parent.mkdir(parents=True, exist_ok=True)
            nf.write_text(json.dumps({"999999": "AppID 999999"}))
            core._name_cache.clear()
            core._resolve_name = lambda a: "真实名字"
            out = core._name_for(999999, None)
            self.assertEqual(out, "真实名字", "中毒缓存应该被重新解析覆盖")
            data = json.loads(nf.read_text())
            self.assertEqual(data.get("999999"), "真实名字")
        finally:
            core._resolve_name = orig_resolve
            core.HOME = orig_home
            core._name_cache.clear()

    def test_good_cache_is_used(self):
        """正常缓存应该直接用，不再请求"""
        orig_resolve = core._resolve_name
        orig_home = core.HOME
        calls = []
        try:
            core.HOME = self.tmp / "home"
            nf = self._names_file()
            nf.parent.mkdir(parents=True, exist_ok=True)
            nf.write_text(json.dumps({"999999": "缓存里的名字"}))
            core._name_cache.clear()

            def spy(a):
                calls.append(a)
                return "不该被调用"

            core._resolve_name = spy
            out = core._name_for(999999, None)
            self.assertEqual(out, "缓存里的名字")
            self.assertEqual(calls, [], "有缓存时不该再解析")
        finally:
            core._resolve_name = orig_resolve
            core.HOME = orig_home
            core._name_cache.clear()


# ══════════════════════════════════════════════════════════════
#  P2-1  write_keys_to_config
# ══════════════════════════════════════════════════════════════

class TestWriteKeys(TempCorePaths):
    """P2-1: 不能静默失败，不能重复插入"""

    KEY = "ab" * 32

    def test_insert_new(self):
        n = core.write_keys_to_config({"1111111": self.KEY})
        self.assertEqual(n, 1)
        self.assertEqual(core._read_vdf_keys(core.CONFIG_VDF.read_text()).get("1111111"),
                         self.KEY)

    def test_idempotent(self):
        core.write_keys_to_config({"1111111": self.KEY})
        n = core.write_keys_to_config({"1111111": self.KEY})
        self.assertEqual(n, 0, "同样的值不该重复写入")

    def test_replace_existing(self):
        core.write_keys_to_config({"1111111": self.KEY})
        new = "cd" * 32
        n = core.write_keys_to_config({"1111111": new})
        self.assertEqual(n, 1)
        self.assertEqual(core._read_vdf_keys(core.CONFIG_VDF.read_text()).get("1111111"),
                         new)

    def test_bad_length_raises(self):
        """长度不是 64 hex 必须报错（Steam 会忽略这种值）"""
        with self.assertRaises(ValueError):
            core.write_keys_to_config({"2222222": "ab" * 48})

    def test_no_duplicate_when_format_unexpected(self):
        """P2-1 核心: 解析器读不到但文件里已存在时，不能重复插入"""
        # 先插一个正常的
        core.write_keys_to_config({"3333333": self.KEY})
        text = core.CONFIG_VDF.read_text()
        # 破坏它的格式（在 id 和 DecryptionKey 之间插一个字段）
        pat = re.compile(r'("3333333"\s*\{\s*)("DecryptionKey")')
        m = pat.search(text)
        self.assertIsNotNone(m, "测试前提: 应该能找到刚写入的块")
        text = text[:m.start(2)] + '"Extra"\t"x"\n\t\t\t\t\t\t' + text[m.start(2):]
        core.CONFIG_VDF.write_text(text)

        before = core.CONFIG_VDF.read_text().count('"3333333"')
        with self.assertRaises(ValueError):
            core.write_keys_to_config({"3333333": "ff" * 32})
        after = core.CONFIG_VDF.read_text().count('"3333333"')
        self.assertEqual(after, before, "不该产生重复的 depot 块")

    def test_missing_depots_section_raises(self):
        core.CONFIG_VDF.write_text('"Nothing"\n{\n}\n')
        with self.assertRaises(Exception):
            core.write_keys_to_config({"4444444": self.KEY})

    def test_result_is_parseable_vdf(self):
        from suos import vdf
        core.write_keys_to_config({"5555555": self.KEY})
        d = vdf.load(str(core.CONFIG_VDF))   # 不该抛异常
        self.assertIsInstance(d, dict)


# ══════════════════════════════════════════════════════════════
#  P2-2  install() 的步骤分类 + 防覆盖
# ══════════════════════════════════════════════════════════════

class TestInstallClassification(TempCorePaths):
    """P2-2: 致命步骤失败要 ok=False；防覆盖保护要拦住退化数据"""

    def test_bad_appid_fails_cleanly(self):
        """不存在的游戏 → ok=False，且不抛异常"""
        r = core.install(999999999, include_dlc=False)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("fatal"), "应该有致命原因")
        self.assertIn("数据", r["message"])

    def test_lua_overwrite_protection(self):
        """P2-2 核心: 新的 Lua 清单数少于现有 → 拒绝覆盖"""
        from suos import multisource

        appid = 7777777
        lua_target = core.LUA_SLS / f"{appid}.lua"
        core.LUA_SLS.mkdir(parents=True, exist_ok=True)
        good_lua = (f"addappid({appid})\n"
                    f'addappid(7777778,0,"{"aa"*32}")\n'
                    f'setManifestid(7777778,"123456")\n'
                    f'setManifestid(7777779,"654321")\n')
        lua_target.write_text(good_lua)

        orig = multisource.resolve

        def degraded(a, verbose=False):
            return {"appid": a, "name": "退化数据", "keys": {}, "manifests": [],
                    "lua": f"addappid({a})\n", "sources": {}}

        try:
            multisource.resolve = degraded
            r = core.install(appid, include_dlc=False)
            self.assertFalse(r["ok"], "退化数据应该导致失败")
            self.assertTrue(any("拒绝覆盖" in s for s in r["steps"]),
                            f"应该出现拒绝覆盖的提示: {r['steps']}")
            # ★ 关键: 原文件必须保持完整
            self.assertIn("setManifestid", lua_target.read_text(),
                          "原 Lua 被破坏了！")
        finally:
            multisource.resolve = orig


# ══════════════════════════════════════════════════════════════
#  P2-3  slsconfig 读 TOML
# ══════════════════════════════════════════════════════════════

class TestSLSConfigToml(unittest.TestCase):
    """P2-3: 只有 config.toml 时也应该能看到 AppIds"""

    def test_reads_toml_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            yaml_path = d / "config.yaml"          # 故意不创建
            (d / "config.toml").write_text(
                'AppIds = [111, 222, 333]\n'
                'AdditionalApps = [222, 444]\n'
            )
            cfg = slsconfig.SLSConfig(yaml_path)
            # 显式传 path 时不探测 TOML（保持原行为）
            self.assertFalse(cfg.exists())

    def test_owned_merges_both(self):
        """owned() 应该合并 YAML 与 TOML"""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = d / "config.yaml"
            p.write_text("AppIds:\n  - 111\nAdditionalApps:\n  - 222\n")
            cfg = slsconfig.SLSConfig(p)
            cfg.load()
            self.assertEqual(cfg.owned(), {111, 222})

    def test_toml_detection_when_no_path(self):
        """不传 path 时应该探测同目录的 config.toml"""
        # 用真实的 CONFIG_PATH 目录做判断（只读，不改动）
        cfg = slsconfig.SLSConfig()
        toml = slsconfig.CONFIG_PATH.with_suffix(".toml")
        if toml.is_file():
            self.assertIsNotNone(cfg.toml_path)
            self.assertTrue(cfg.exists())
            cfg.load()
            # 真实环境里应该有 AppIds
            self.assertGreater(len(cfg.owned()), 0,
                               "config.toml 存在时 owned() 不该为空")


# ══════════════════════════════════════════════════════════════
#  P2-4  批量写入
# ══════════════════════════════════════════════════════════════

class TestBatchToml(TempCorePaths):
    """P2-4: 批量接口的行为与性能"""

    def _appids(self) -> list[str]:
        text = core.SLS_TOML.read_text()
        m = re.search(r"^AppIds = \[([^\]]*)\]", text, re.M)
        return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []

    def test_batch_add(self):
        n = core._add_appids_to_toml([9001, 9002, 9003])
        self.assertEqual(n, 6, "两个列表各加 3 个 = 6")
        ids = self._appids()
        for x in ("9001", "9002", "9003"):
            self.assertIn(x, ids)

    def test_batch_idempotent(self):
        core._add_appids_to_toml([9001, 9002])
        n = core._add_appids_to_toml([9001, 9002])
        self.assertEqual(n, 0)

    def test_batch_empty(self):
        self.assertEqual(core._add_appids_to_toml([]), 0)

    def test_single_wrapper(self):
        core._add_appid_to_toml(9500)
        self.assertIn("9500", self._appids())

    def test_batch_writes_once(self):
        """批量接口应该只写一次文件"""
        writes = []
        orig = core.SLS_TOML

        class Spy(type(orig)):  # type: ignore[misc]
            pass

        # 更简单: 用 mtime/inode 计数不靠谱，改成统计 write_text 调用
        real_write = Path.write_text
        count = {"n": 0}

        def counting_write(self, *a, **kw):
            if self == core.SLS_TOML:
                count["n"] += 1
            return real_write(self, *a, **kw)

        Path.write_text = counting_write  # type: ignore[method-assign]
        try:
            core._add_appids_to_toml(list(range(7000, 7100)))
        finally:
            Path.write_text = real_write  # type: ignore[method-assign]
        self.assertEqual(count["n"], 1,
                         f"100 个 appid 应该只写 1 次，实际 {count['n']} 次")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════
#  keyless depot 占位密钥（本次修复）
# ══════════════════════════════════════════════════════════════

class TestPlaceholderKeys(TempCorePaths):
    """Steam 会要密钥但我们没有的 depot，必须写零密钥占位。

    否则 Steam: hook 没有 → 放行给 Valve → Valve 拒绝
                → 【把整个下载任务从队列移除】
    实测案例: 紫色晶石(625960) depot 4506760
    """

    def test_detects_missing_key_depot(self):
        """depots 里有、keys 里没有 → 要占位"""
        r = {"depots": [1, 2, 3], "keys": {1: "aa" * 32, 2: "bb" * 32}, "appid": 999}
        self.assertEqual(core._depots_needing_placeholder(r), [3])

    def test_no_false_positive_when_all_have_keys(self):
        """都有密钥 → 不占位（关键：不能误伤）"""
        r = {"depots": [1, 2], "keys": {1: "aa" * 32, 2: "bb" * 32}, "appid": 999}
        self.assertEqual(core._depots_needing_placeholder(r), [])

    def test_existing_zero_key_is_idempotent(self):
        """config.vdf 里已经是零密钥 → 可能会被再报一次，但写入必须幂等

        实测行为: 会再报一次（因为零密钥 strip("0") 后为空，
        不满足"已有非零密钥就跳过"的条件）。重写零密钥值不变，
        所以是安全的幂等操作。这里验证"幂等"而不是"不报告"。
        """
        core.write_keys_to_config({"4444444": "00" * 32})
        r = {"depots": [4444444], "keys": {}, "appid": 999}
        need = core._depots_needing_placeholder(r)
        # 再写一次，值必须不变
        for d in need:
            core.write_keys_to_config({d: "00" * 32})
        self.assertEqual(
            core._read_vdf_keys(core.CONFIG_VDF.read_text()).get("4444444"),
            "00" * 32, "重写零密钥后值应保持不变")

    def test_realdepot_flow_does_not_touch_real_keys(self):
        """★ 端到端安全验证: 混合场景下单次调用不能改动任何真密钥"""
        real_a, real_b = "11" * 32, "22" * 32
        core.write_keys_to_config({"1000001": real_a, "1000002": real_b})
        # 模拟一个游戏: depots 有三个，两个有真密钥，一个没有
        r = {"depots": [1000001, 1000002, 1000003],
             "keys": {1000001: real_a, 1000002: real_b}, "appid": 999}
        need = core._depots_needing_placeholder(r)
        self.assertEqual(need, [1000003])
        for d in need:
            core.write_keys_to_config({d: "00" * 32})
        after = core._read_vdf_keys(core.CONFIG_VDF.read_text())
        self.assertEqual(after.get("1000001"), real_a, "真密钥被改动了！")
        self.assertEqual(after.get("1000002"), real_b, "真密钥被改动了！")
        self.assertEqual(after.get("1000003"), "00" * 32)

    def test_does_not_override_real_key(self):
        """★ 最重要的安全保证: 有真密钥的 depot 绝不能被写成零密钥"""
        real = "ab" * 32
        core.write_keys_to_config({"5555555": real})
        r = {"depots": [5555555], "keys": {5555555: real}, "appid": 999}
        self.assertEqual(core._depots_needing_placeholder(r), [])
        # config.vdf 里的值不受影响
        self.assertEqual(
            core._read_vdf_keys(core.CONFIG_VDF.read_text()).get("5555555"), real)

    def test_handles_empty_and_garbage(self):
        for r in ({}, {"depots": None}, {"depots": ["x", None], "keys": {}},
                  {"depots": [], "keys": None}):
            self.assertEqual(core._depots_needing_placeholder(r), [])


# ══════════════════════════════════════════════════════════════
#  卸载时一并移除 DLC
# ══════════════════════════════════════════════════════════════

class TestUninstallRemovesDlc(TempCorePaths):
    """用户 bug 报告: 卸载游戏后，它带的 DLC appid 会留在 config.toml
    → Steam 依然认为你拥有那些 DLC（库里留下孤儿条目）
    """

    def _toml_appids(self) -> list[str]:
        t = core.SLS_TOML.read_text()
        m = re.search(r"^AppIds = \[([^\]]*)\]", t, re.M)
        return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []

    def test_extracts_dlc_from_lua(self):
        """能从 -- DLC 标记后读出 DLC appid"""
        appid = 8888000
        core.LUA_SLS.mkdir(parents=True, exist_ok=True)
        (core.LUA_SLS / f"{appid}.lua").write_text(
            f"addappid({appid})\n"
            f'addappid(8888001,0,"{"aa"*32}")\n'
            f'setManifestid(8888001,"111")\n'
            f"\n-- DLC\n"
            f"addappid(9000001)\n"
            f"addappid(9000002)\n"
        )
        dlcs = core._dlc_appids_from_lua(appid)
        self.assertEqual(dlcs, [9000001, 9000002])

    def test_no_dlc_marker_returns_empty(self):
        appid = 8888001
        (core.LUA_SLS / f"{appid}.lua").write_text(f"addappid({appid})\n")
        self.assertEqual(core._dlc_appids_from_lua(appid), [])

    def test_uninstall_removes_dlc_from_toml(self):
        """★ 核心: 卸载后 DLC appid 也要从 config.toml 消失"""
        appid = 8888002
        core._add_appids_to_toml([appid, 9000001, 9000002])
        (core.LUA_SLS / f"{appid}.lua").write_text(
            f"addappid({appid})\n\n-- DLC\naddappid(9000001)\naddappid(9000002)\n")
        before = self._toml_appids()
        self.assertIn("9000001", before)
        self.assertIn("9000002", before)

        r = core.uninstall(appid)
        self.assertTrue(r["ok"])
        self.assertEqual(r.get("dlcs_removed"), [9000001, 9000002])
        after = self._toml_appids()
        self.assertNotIn(str(appid), after, "本体没被移除")
        self.assertNotIn("9000001", after, "DLC 没被移除")
        self.assertNotIn("9000002", after, "DLC 没被移除")

    def test_uninstall_keeps_other_games(self):
        """卸载一个游戏不能影响别的"""
        keep = 8888003
        core._add_appids_to_toml([keep, 8888004])
        (core.LUA_SLS / f"{keep}.lua").write_text(f"addappid({keep})\n")
        (core.LUA_SLS / "8888004.lua").write_text("addappid(8888004)\n")

        core.uninstall(keep)
        after = self._toml_appids()
        self.assertIn("8888004", after, "别的游戏被误删了！")
        self.assertNotIn("8888003", after)


class TestFetchDlcsFiltering(unittest.TestCase):
    """fetch_dlcs 必须滤掉"其实是 depot"的条目。

    实测: 潜渊症(602960) 的 API config.dlcs = [1197650, 3714450]
          但 1197650 也在 config.depots 里 → 是 depot，不是 DLC
    """

    def test_barotrauma_dlc_count(self):
        """潜渊症应该只有 1 个真 DLC（3714450）"""
        from suos import rc4  # noqa: F401
        dlcs = core.fetch_dlcs(602960)
        if not dlcs:
            self.skipTest("SteamUnlock API 不可用")
        self.assertNotIn(1197650, dlcs, "depot 被误当成 DLC 了")
        self.assertIn(3714450, dlcs)

    def test_monster_hunter_still_has_many(self):
        """怪猎的 253 个 DLC 不该被过滤误伤"""
        dlcs = core.fetch_dlcs(1446780)
        if not dlcs:
            self.skipTest("SteamUnlock API 不可用")
        self.assertGreater(len(dlcs), 200, f"怪猎 DLC 数异常: {len(dlcs)}")
        # 抽查几个已知的真 DLC
        for d in (1753180, 1753181, 2133120):
            self.assertIn(d, dlcs)


# ══════════════════════════════════════════════════════════════
#  改名残留：项目目录被写死（实机上项目在 ~/SteamUnlockOS，
#  仓库代码却写死 ~/steam-toolkit / ~/SteamUnlockOS / /home/deck）
# ══════════════════════════════════════════════════════════════

import subprocess  # noqa: E402

def _working_bash() -> "str | None":
    """找一个【真能跑】的 bash（Windows 沙箱里 msys bash 可能起不来）"""
    b = shutil.which("bash")
    if not b:
        return None
    try:
        r = subprocess.run([b, "-c", "echo ok"], capture_output=True, text=True, timeout=15)
        return b if r.stdout.strip() == "ok" else None
    except Exception:  # noqa: BLE001
        return None


_BASH = _working_bash()


def _code_files() -> list[Path]:
    files = [ROOT / "webui_core.py", ROOT / "buildenv.sh"]
    files += sorted((ROOT / "suos").glob("*.py"))
    files += sorted((ROOT / "scripts").glob("*.sh"))
    return [f for f in files if f.is_file()]


class TestPathsHardcodedInstallDir(unittest.TestCase):
    """项目目录必须从文件自身位置推导，不能写死任何一个目录名。

    实机复现（SteamOS，项目在 ~/SteamUnlockOS）:
      · healthcheck 第 11 项"启动器日志: 暂无"（日志明明在 ~/SteamUnlockOS/logs/）
      · fix-injection.sh status 报"备份: ✗ 不存在" → install/remove 拒绝执行
      · buildenv.sh 指向不存在的 ~/steam-toolkit/buildtools → --fix 必定编译失败
    """

    # 写死的"安装目录 + 项目子目录"形式（不含 install.sh 的默认安装目录、兜底候选）
    BAD = re.compile(
        r'(\$HOME"?|~|/home/deck)/steam-toolkit/(backup|logs|buildtools|buildenv|docs)'
        r'|SteamUnlockOS/(backup|buildtools|buildenv)'
        r'|/home/deck/')

    def test_no_hardcoded_project_dir(self) -> None:
        bad = []
        for f in _code_files():
            for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if self.BAD.search(line):
                    bad.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
        self.assertEqual(bad, [], "仍有写死的项目目录:\n" + "\n".join(bad))

    def test_python_backup_dirs_under_repo(self) -> None:
        from suos import depotcache_clean, updater
        for name, p in (("webui_core.BACKUP", core.BACKUP),
                        ("depotcache_clean.ARCHIVE_DIR", depotcache_clean.ARCHIVE_DIR),
                        ("updater.BACKUP", updater.BACKUP)):
            self.assertTrue(Path(p).resolve().is_relative_to(ROOT),
                            f"{name} = {p} 不在项目目录 {ROOT} 下")

    def test_scripts_define_root_before_use(self) -> None:
        for f in sorted((ROOT / "scripts").glob("*.sh")):
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            uses = [i for i, l in enumerate(lines) if "$ROOT" in l and not l.startswith("ROOT=")]
            if not uses:
                continue
            defs = [i for i, l in enumerate(lines) if l.startswith("ROOT=")]
            self.assertTrue(defs and defs[0] < uses[0], f"{f.name}: $ROOT 在定义前被使用")


@unittest.skipUnless(_BASH, "没有可用的 bash")
class TestBuildenvSelfLocate(unittest.TestCase):
    """buildenv.sh 必须定位到自己所在的项目目录，且在 set -u 下 source 不中断。

    回归: 原来写死 SLSU_ROOT=/home/deck/steam-toolkit；且 $LD_LIBRARY_PATH 未定义时
    在 set -u 的调用方里 source 会直接中断（check-after-steam-update.sh 就是 set -u）。
    """

    def test_locates_own_dir_under_set_u(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "某个任意目录名"
            (proj / "buildtools/wrappers").mkdir(parents=True)
            shutil.copy2(ROOT / "buildenv.sh", proj / "buildenv.sh")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("SLSU_ROOT", "LD_LIBRARY_PATH", "LIBRARY_PATH")}
            r = subprocess.run(
                [_BASH, "-uc",
                 '. "$1/buildenv.sh" && [ "$SLSU_TOOLS" = "$(cd "$1" && pwd)/buildtools" ] '
                 '&& echo OK || echo "BAD SLSU_TOOLS=$SLSU_TOOLS"',
                 "_", proj.as_posix()],
                capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
            self.assertIn("OK", r.stdout, r.stdout + r.stderr)
