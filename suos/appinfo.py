"""Steam appinfo.vdf 解析器（旧版二进制 KeyValues 格式）。

格式（本机实测 appinfo.vdf 头部）：

    offset 0  u32  magic = 0x07564429
    offset 4  u32  version = 1
    offset 8  u32  字符串表偏移
    offset 12 字符串表：u32 长度 + null 结尾的键名序列
    之后是条目序列，直到字符串表偏移为止：
        u32 appid
        u32 entry_size
        u32 infostate
        u64 last_updated
        u64 access_token
        u8[20] sha1
        entry_size 字节的二进制 KV 数据
    二进制 KV 的类型字节：
        0x00 嵌套对象开始（后跟 key 字符串，然后是其子项，直到 0x08）
        0x01 字符串（null 结尾）
        0x02 u32
        0x03 f32
        0x04 u32（指针）
        0x05 宽字符串（少见）
        0x06 u32
        0x07 u64
        0x08 对象结束
        0x0A i64
        0x0B 对象结束（另一种）

新格式（version 29+）是 protobuf 且条目 delta 编码，本模块不处理；
原程序的做法也一样（它只解析到足够取 name/depots 的程度）。
"""

from __future__ import annotations

import struct
from pathlib import Path

__all__ = ["AppInfoFile", "AppEntry", "parse"]

MAGIC = 0x07564429


class AppInfoError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes, pos: int, end: int):
        self.data = data
        self.pos = pos
        self.end = end

    def u8(self) -> int:
        if self.pos >= self.end:
            raise AppInfoError("读取越界")
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u32(self) -> int:
        if self.pos + 4 > self.end:
            raise AppInfoError("读取越界")
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self) -> int:
        if self.pos + 8 > self.end:
            raise AppInfoError("读取越界")
        v = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def cstr(self) -> str:
        start = self.pos
        while self.pos < self.end and self.data[self.pos] != 0:
            self.pos += 1
        if self.pos >= self.end:
            raise AppInfoError("字符串没有结束符")
        text = self.data[start : self.pos].decode("utf-8", errors="replace")
        self.pos += 1
        return text


def _read_object(reader: _Reader, depth: int = 0) -> dict:
    """读一个二进制 KV 对象，返回 dict。读取位置在 reader 上推进。

    实测本机 appinfo.vdf（version 1）的编码：
      - 顶层用一个 **u32** 当键（type 0x02 + 4 字节 = appid），值也常是 u32 → {appid: value}
      - 之后是 type 0x00 + "键名\\0" + 子对象 的常规嵌套
      - 结束时 0x08
    """
    if depth > 32:
        raise AppInfoError("嵌套过深")
    obj: dict = {}
    while True:
        t = reader.u8()
        if t == 0x08 or t == 0x0B:
            return obj
        if t == 0x02:  # u32 键值对（appinfo 顶层就是这一种）
            key = reader.u32()
            nxt = reader.u8()
            if nxt == 0x08:
                obj[key] = None
                return obj
            if nxt == 0x00:
                obj[key] = _read_object(reader, depth + 1)
            elif nxt == 0x01:
                obj[key] = reader.cstr()
            elif nxt in (0x02, 0x04, 0x06):
                obj[key] = reader.u32()
            elif nxt == 0x07:
                obj[key] = reader.u64()
            elif nxt == 0x03:
                obj[key] = struct.unpack_from("<f", reader.data, reader.pos)[0]
                reader.pos += 4
            elif nxt == 0x0A:
                obj[key] = struct.unpack_from("<q", reader.data, reader.pos)[0]
                reader.pos += 8
            else:
                raise AppInfoError(f"u32 键 {key} 后的类型字节未知: {nxt:#x}")
        elif t == 0x00:
            key = reader.cstr()
            obj[key] = _read_object(reader, depth + 1)
        elif t == 0x01:
            obj[reader.cstr()] = reader.cstr()
        elif t in (0x04, 0x06):
            obj[reader.cstr()] = reader.u32()
        elif t == 0x03:
            key = reader.cstr()
            obj[key] = struct.unpack_from("<f", reader.data, reader.pos)[0]
            reader.pos += 4
        elif t == 0x07:
            obj[reader.cstr()] = reader.u64()
        elif t == 0x0A:
            key = reader.cstr()
            obj[key] = struct.unpack_from("<q", reader.data, reader.pos)[0]
            reader.pos += 8
        elif t == 0x05:  # 宽字符串：键名 + u32 字节长度 + UTF-16 数据
            key = reader.cstr()
            length = reader.u32()
            raw = reader.data[reader.pos : reader.pos + length]
            reader.pos += length
            obj[key] = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        else:
            raise AppInfoError(f"未知的 KV 类型字节 {t:#x}（位置 {reader.pos - 1:#x}）")


class AppEntry:
    __slots__ = ("appid", "infostate", "last_updated", "access_token", "sha1", "data")

    def __init__(self, appid, infostate, last_updated, access_token, sha1, data):
        self.appid = appid
        self.infostate = infostate
        self.last_updated = last_updated
        self.access_token = access_token
        self.sha1 = sha1
        self.data: dict = data

    @property
    def name(self) -> str:
        return self.data.get("common", {}).get("name", "")

    @property
    def type(self) -> str:
        return self.data.get("common", {}).get("type", "")

    @property
    def oslist(self) -> str:
        return self.data.get("common", {}).get("oslist", "")

    @property
    def depots(self) -> dict:
        return self.data.get("depots", {})

    def __repr__(self) -> str:
        return f"<AppEntry {self.appid} {self.name!r}>"


class AppInfoFile:
    """解析后的 appinfo.vdf。`apps` 是 {appid: AppEntry}。"""

    def __init__(self, entries: dict[int, AppEntry], keys: list[str]):
        self.apps = entries
        self.keys = keys

    def get(self, appid: int) -> AppEntry | None:
        return self.apps.get(appid)

    def name_of(self, appid: int) -> str:
        entry = self.apps.get(appid)
        return entry.name if entry else ""

    @classmethod
    def load(cls, path: str | Path) -> "AppInfoFile":
        return parse(Path(path).read_bytes())


def parse(data: bytes) -> AppInfoFile:
    if len(data) < 16:
        raise AppInfoError("文件太短")
    # 实测头部：magic(4) version(4) 字符串表偏移(4) 0(4)，条目从 16 开始
    magic, version, str_off, _pad = struct.unpack_from("<IIII", data, 0)
    if magic != MAGIC:
        raise AppInfoError(f"magic 不匹配: {magic:#x}（期望 {MAGIC:#x}），可能是新版 protobuf 格式")

    # 字符串表占据文件剩余部分：u32 条目数 + 键名序列 + 0x00 结尾
    keys: list[str] = []
    table_start = str_off
    if table_start < len(data):
        r = _Reader(data, table_start, len(data))
        try:
            r.u32()  # 条目数，不依赖它，循环读到结尾自然停
        except AppInfoError:
            pass
        while r.pos < len(data):
            try:
                keys.append(r.cstr())
            except AppInfoError:
                break
        while keys and keys[-1] == "":
            keys.pop()

    entries: dict[int, AppEntry] = {}
    # 条目 KV 以 u32 键值对开头：0x02 + u32 appid。用它当同步标记（实测文件里出现 1156 次），
    # 不必推算记录头长度与对齐填充。
    limit = min(str_off, len(data))
    pos = 16
    while pos < limit - 8:
        found = data.find(b"\x02", pos, limit)
        if found < 0:
            break
        appid = struct.unpack_from("<I", data, found + 1)[0]
        if appid < 1 or appid > 0x7FFFFFFF or data[found + 5] != 0x00:
            pos = found + 1
            continue
        try:
            reader = _Reader(data, found, limit)
            kv = _read_object(reader)
        except AppInfoError:
            pos = found + 1
            continue
        head = found - 56
        sha1 = data[head + 36 : head + 56] if head >= 0 else b""
        last_updated = struct.unpack_from("<Q", data, head + 16)[0] if head >= 0 else 0
        access_token = struct.unpack_from("<Q", data, head + 24)[0] if head >= 0 else 0
        entries[appid] = AppEntry(appid, 0, last_updated, access_token, sha1, kv)
        pos = max(reader.pos, found + 5)

    return AppInfoFile(entries, keys)
