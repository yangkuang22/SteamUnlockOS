"""rc4 / vdf 两个模块的单元测试。

运行：cd ~/steam-toolkit && python3 -m pytest tests/ -v
（没装 pytest 时用：python3 tests/test_core.py 直接跑）
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from suos import rc4, vdf  # noqa: E402


class TestRC4(unittest.TestCase):
    def test_known_vector(self):
        """RFC 6229 风格的经典测试向量：key="Key", plaintext="Plaintext"。"""
        self.assertEqual(
            rc4.rc4(b"Key", b"Plaintext").hex(),
            "bbf316e8d940af0ad3",
        )

    def test_known_vector_wiki(self):
        """维基百科 RC4 示例：key="Wiki", plaintext="pedia"。"""
        self.assertEqual(rc4.rc4(b"Wiki", b"pedia").hex(), "1021bf0420")

    def test_default_key_shape(self):
        """RC4_KEY 是 20 字节的 bytes 常量（GBK 读出来是科乐美秘技）。"""
        self.assertEqual(len(rc4.RC4_KEY), 20)
        self.assertEqual(rc4.default_key(), rc4.RC4_KEY)
        self.assertEqual(rc4.RC4_KEY.hex(), rc4.RC4_KEY_HEX)
        self.assertEqual(rc4.RC4_KEY.decode("gbk"), "↑↑↓↓←→←→BABA")

    def test_lua_pack_roundtrip(self):
        """原程序写 .o = rc4(lua)；解回来必须一模一样。"""
        lua = 'addappid(730)\naddtoken(730,"abc")\nsetManifestid(731,"123",456)\n'
        blob = rc4.encrypt_lua_pack(lua)
        self.assertNotEqual(blob, lua.encode())
        self.assertEqual(rc4.decrypt_lua_pack(blob), lua)

    def test_lua_pack_is_not_base64_or_wrapped(self):
        """确认 .o 不是 base64、也没有额外包头：长度必须等于原文长度。"""
        lua = "addappid(1)\n"
        self.assertEqual(len(rc4.encrypt_lua_pack(lua)), len(lua.encode("utf-8")))

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            rc4.rc4(b"", b"x")


class TestVDF(unittest.TestCase):
    SAMPLE = '''
// 注释
"Root"
{
\t"Number"\t\t"440"
\t"Nested"
\t{
\t\t"Key"\t\t"141426adc496d4a9070cfa549623bd7f84bf70711e9c213881191eaad8cc90a4"
\t\t"Empty"\t\t""
\t\t"Escaped"\t\t"a\\\\b\\"c"
\t}
}
'''

    def test_parse_nested(self):
        d = vdf.loads(self.SAMPLE)
        self.assertEqual(d["Root"]["Number"], "440")
        self.assertEqual(d["Root"]["Nested"]["Empty"], "")
        self.assertEqual(d["Root"]["Nested"]["Escaped"], 'a\\b"c')

    def test_roundtrip(self):
        d = vdf.loads(self.SAMPLE)
        d2 = vdf.loads(vdf.dumps(d))
        self.assertEqual(d, d2)

    def test_rejects_garbage(self):
        with self.assertRaises(vdf.ParseError):
            vdf.loads('"a" "b" }\n')

    def test_unclosed_object(self):
        with self.assertRaises(vdf.ParseError):
            vdf.loads('"a" { "b" "c"\n')

    def test_real_config_vdf_has_depot_keys(self):
        """用本机真实的 config.vdf 验证解析器（存在才算）。"""
        candidates = [
            Path.home() / ".steam/steam/config/config.vdf",
            Path.home() / ".local/share/Steam/config/config.vdf",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            self.skipTest("本机没有 config.vdf")
        data = vdf.load(path)
        # 深入到 InstallConfigStore/Software/Valve/Steam/depots
        node = data
        for key in ("InstallConfigStore", "Software", "Valve", "Steam", "depots"):
            self.assertIn(key, node, f"config.vdf 里找不到 {key}")
            node = node[key]
        with_key = [k for k, v in node.items() if isinstance(v, dict) and "DecryptionKey" in v]
        self.assertGreater(len(with_key), 50, "解出的带密钥 depot 太少，解析可能有问题")
        for depotid in with_key:
            key = node[depotid]["DecryptionKey"]
            # 实测新版游戏的 depot 密钥可以到 192 个 hex（64 字节 AES key）
            self.assertRegex(key, r"^[0-9a-fA-F]{32,256}$", f"depot {depotid} 的密钥格式不对")


if __name__ == "__main__":
    unittest.main(verbosity=2)
