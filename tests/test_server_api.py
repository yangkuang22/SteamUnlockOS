"""服务端协议测试（需要网络；无网络时用缓存跳过）。

运行：cd ~/steam-toolkit && python3 tests/test_server_api.py
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from suos import rc4, server_api, vdf  # noqa: E402

CACHE = Path(__file__).resolve().parent.parent / "cache"


class TestRC4KeyCorrectness(unittest.TestCase):
    """RC4_KEY 必须能解开服务端真实数据——这是密钥正确性的唯一硬证据。"""

    def test_key_value(self):
        self.assertEqual(len(rc4.RC4_KEY), 20)
        self.assertEqual(rc4.RC4_KEY.hex(), rc4.RC4_KEY_HEX)
        self.assertEqual(rc4.RC4_KEY.decode("gbk"), "↑↑↓↓←→←→BABA")

    def test_rc4_known_vectors(self):
        self.assertEqual(rc4.rc4(b"Key", b"Plaintext").hex(), "bbf316e8d940af0ad3")
        self.assertEqual(rc4.rc4(b"Wiki", b"pedia").hex(), "1021bf0420")

    def test_decrypts_cached_server_response(self):
        sample = CACHE / "GetAppinfo_379720.bin"
        if not sample.is_file():
            self.skipTest("没有缓存样本（先跑一次 cli fetch）")
        text = rc4.rc4(rc4.RC4_KEY, sample.read_bytes()).decode("utf-8")
        data = ast.literal_eval(text)  # 不是 JSON，是 Python 字面量
        self.assertEqual(set(data.keys()), {"Key", "appinfo", "config"})
        self.assertIn('"DecryptionKey"', data["Key"])
        self.assertEqual(data["appinfo"].count('"appid"'), 1)


class TestPayloadParsing(unittest.TestCase):
    def _payload(self, appid: int):
        sample = CACHE / f"GetAppinfo_{appid}.bin"
        if not sample.is_file():
            self.skipTest(f"没有 appid {appid} 的缓存样本")
        return server_api.parse_payload(sample.read_bytes())

    def test_doom_payload(self):
        p = self._payload(379720)
        self.assertEqual(p.appid, 379720)
        self.assertEqual(p.name, "DOOM")
        self.assertEqual(len(p.depots), 12)
        self.assertEqual(len(p.dlcs), 5)
        # 每个 depot 都要有 GID 和密钥，否则下载不了
        for d in p.depots:
            self.assertIsNotNone(d.gid, f"depot {d.depotid} 缺 GID")
            self.assertTrue(d.key, f"depot {d.depotid} 缺解密密钥")
            self.assertRegex(d.key, r"^[0-9a-fA-F]{32,192}$")

    def test_keys_vdf_shape(self):
        sample = CACHE / "GetAppinfo_379720.bin"
        if not sample.is_file():
            self.skipTest("没有缓存样本")
        data = ast.literal_eval(rc4.rc4(rc4.RC4_KEY, sample.read_bytes()).decode("utf-8"))
        keys = vdf.loads(data["Key"])
        self.assertIn("depots", keys)
        self.assertIsInstance(keys["depots"], dict)

    def test_bad_payload_rejected(self):
        with self.assertRaises(ValueError):
            server_api.parse_payload(b"\x00" * 100)


@unittest.skipIf(
    not Path("/sys/class/net").is_dir(),
    "没有网络设备",
)
class TestLiveServer(unittest.TestCase):
    """活体测试：确认服务端还活着（失败可能只是网络问题，不一定是代码错）。"""

    def test_fetch_tf2(self):
        try:
            payload = server_api.install_plan(440)
        except Exception as exc:
            self.skipTest(f"服务端不可达: {exc}")
        self.assertEqual(payload.appid, 440)
        self.assertGreater(len(payload.depots), 3)
        self.assertTrue(payload.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
