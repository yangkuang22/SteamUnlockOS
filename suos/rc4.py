"""RC4 —— 从 SteamUnlock 的 `utils.rc4` 逆向出来的等价实现。

来源与自证（见 su_analysis/RECON_RC4.md）：
  - Main.dll offset 0x04B90896：Nuitka tag `0x63`（= bytes 常量），值 20 字节，名字 `RC4_KEY` 紧随其后
  - **RC4_KEY = a1fca1fca1fda1fda1fba1faa1fba1fa42414241**，GBK 解码 = "↑↑↓↓←→←→BABA"（科乐美秘技）
  - 自证：该 20 字节在 92MB 里**恰好出现 1 次**；用它 + 标准 RC4 解密
    http://auth1.caigamer.cn/GetAppinfo/730 的真实响应，得到可读的 Python 字典字面量 →
    `{'Key': <VDF>, 'appinfo': <VDF>, 'config': <JSON>}`，`ast.literal_eval` 通过。

用途（原程序里 RC4 只用在两处）：
  1. 写 `<Steam>/config/stplug-in/<appid>.o`：`.o` = rc4(lua_text.encode("utf-8"))，**裸密文无头部**
  2. 解密服务端下发的 GetAppinfo 响应
注意：`config.vdf` 里的 depot 密钥是明文 hex，**不走 RC4**。
"""

from __future__ import annotations

#: 原程序 config.py 里的 RC4_KEY（20 字节，Nuitka bytes 常量）。
RC4_KEY_HEX = "a1fca1fca1fda1fda1fba1faa1fba1fa42414241"
RC4_KEY = bytes.fromhex(RC4_KEY_HEX)
#: 同一串字节按 GBK 读出来的样子（作者的小彩蛋）
RC4_KEY_EASTER_EGG = "↑↑↓↓←→←→BABA"


def rc4(key: bytes, data: bytes) -> bytes:
    """标准 RC4。密钥调度 + 伪随机生成，逐字节异或。"""
    if not key:
        raise ValueError("RC4 key 不能为空")
    s = list(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + s[i] + key[i % klen]) & 0xFF
        s[i], s[j] = s[j], s[i]

    out = bytearray(len(data))
    i = j = 0
    for n, byte in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out[n] = byte ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


def default_key() -> bytes:
    """RC4_KEY 的字节形式（20 字节，直接就是常量值）。"""
    return RC4_KEY


def encrypt_lua_pack(lua_text: str, key: bytes | None = None) -> bytes:
    """把 Lua 文本打成 `.o` 文件的内容。"""
    return rc4(key or default_key(), lua_text.encode("utf-8"))


def decrypt_lua_pack(raw: bytes, key: bytes | None = None) -> str:
    """把 `.o` 文件的内容解回 Lua 文本（解密失败会抛 UnicodeDecodeError）。"""
    return rc4(key or default_key(), raw).decode("utf-8")
