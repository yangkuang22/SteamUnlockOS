"""Steam depot 清单解析 + 文件块解密（用于第三方下载路线）。

清单格式（实测 appid 4012810 / depotid 4012811 / gid 4900984998756496132，330,771 字节）：
    <u32 magic=0x71F617D0><u32 body_len>
    ContentManifestPayload {
      repeated FileMapping files = 1 {
        string filename = 1;
        uint64 size = 2;          // 目录项为 0
        uint32 flags = 3;         // 1 = 目录
        bytes  sha_file = 4;      // 20B
        bytes  sha_chunk = 5;     // 20B（内容哈希）
        repeated ChunkData chunks = 6 {   // ★ 块在 field 6，不是 3
          bytes  sha = 1;         // 20B 块哈希（下载 URL 用）
          uint32 offset = 2;      // 在文件内的字节偏移
          uint32 cb_original = 3; // 原始（解密后）长度
          uint32 cb_compressed = 4;// 传输长度
        }
      }
    ★ 实测（4012811）：1 个目录项 + 110 个文件项，块字段号为 6；每条 FileMapping
      的 field4/field5 分别是"文件 sha"和"内容 sha"。
    }
    之后还有 metadata / signature 段，本模块忽略。

depot 解密密钥（本机实测 4012811）：
    96 字节 = 16 字节 IV + 64 字节中段 + 16 字节尾
    实际用于解密的 AES-256 密钥取中段的**前 32 字节**（Steam 用 AES-256-CBC + 该 IV）。
    文件块若 `cb_compressed == cb_original` 则未加密，直接可用。
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Chunk", "FileMapping", "Manifest", "parse_manifest", "load_manifest", "depot_key_parts"]

MANIFEST_MAGIC = 0x71F617D0


class ManifestError(ValueError):
    pass


@dataclass
class Chunk:
    sha: bytes
    offset: int
    cb_original: int
    cb_compressed: int
    checksum: int = 0          # Adler32，清单里带的校验值

    @property
    def sha_hex(self) -> str:
        return self.sha.hex()

    @property
    def encrypted(self) -> bool:
        return self.cb_compressed != 0 and self.cb_original != self.cb_compressed


@dataclass
class FileMapping:
    filename: str
    size: int
    flags: int = 0
    chunks: list[Chunk] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"<File {self.filename!r} {self.size}B {len(self.chunks)}块>"


@dataclass
class Manifest:
    files: list[FileMapping]
    depotid: int | None = None
    gid: int | None = None

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def chunk_count(self) -> int:
        return sum(len(f.chunks) for f in self.files)


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    v = 0
    shift = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        v |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return v, i
    raise ManifestError("varint 越界")


def _fields(buf: bytes):
    """产出 (字段号, wire, 值或 bytes, 下一个位置)。"""
    i = 0
    while i < len(buf):
        tag = buf[i]
        wire = tag & 7
        num = tag >> 3
        i += 1
        if num == 0:
            return
        if wire == 0:
            val, i = _read_varint(buf, i)
            yield num, wire, val
        elif wire == 2:
            ln, i = _read_varint(buf, i)
            if i + ln > len(buf):
                return
            yield num, wire, buf[i : i + ln]
            i += ln
        elif wire == 5:
            if i + 4 > len(buf):
                return
            yield num, wire, struct.unpack_from("<I", buf, i)[0]
            i += 4
        elif wire == 1:
            if i + 8 > len(buf):
                return
            yield num, wire, struct.unpack_from("<Q", buf, i)[0]
            i += 8
        else:
            return


def parse_manifest(data: bytes) -> Manifest:
    if len(data) < 16:
        raise ManifestError("文件太短")
    magic, body_len = struct.unpack_from("<II", data, 0)
    if magic != MANIFEST_MAGIC:
        raise ManifestError(f"魔数不对: {magic:#x}")
    body = data[8 : 8 + body_len]

    files: list[FileMapping] = []
    for num, wire, sub in _fields(body):
        if num != 1 or wire != 2:
            continue  # 只有 field 1 是 FileMapping
        fname = ""
        fsize = 0
        fflags = 0
        chunks: list[Chunk] = []
        for n2, w2, v2 in _fields(sub):
            if n2 == 1 and w2 == 2:
                fname = v2.decode("utf-8", errors="replace")
            elif n2 == 2 and w2 == 0:
                fsize = v2
            elif n2 == 3 and w2 == 0:
                fflags = v2
            elif n2 == 6 and w2 == 2:
                csha = b""
                coff = csize = corig = ccrc = 0
                for n3, w3, v3 in _fields(v2):
                    if n3 == 1 and w3 == 2:
                        csha = v3
                    elif n3 == 2 and w3 == 0:
                        ccrc = v3
                    elif n3 == 3 and w3 == 0:
                        coff = v3
                    elif n3 == 4 and w3 == 0:
                        corig = v3
                    elif n3 == 5 and w3 == 0:
                        csize = v3
                chunks.append(Chunk(sha=csha, offset=coff, cb_original=corig,
                                    cb_compressed=csize, checksum=ccrc))
        files.append(FileMapping(filename=fname, size=fsize, flags=fflags, chunks=chunks))
    return Manifest(files=files)


def load_manifest(path: str | Path) -> Manifest:
    return parse_manifest(Path(path).read_bytes())


def depot_key_parts(key_hex: str) -> dict[str, bytes]:
    """把 192 hex 的 depot 密钥拆成 Steam 用的几个部分。

    实测结构：`<16字节IV><64字节中段><16字节尾>`
    Steam 解密用 AES-256-CBC，密钥取中段前 32 字节，IV 取开头 16 字节。
    """
    raw = bytes.fromhex(key_hex)
    if len(raw) == 32:  # 老式：直接就是 AES-256 密钥，IV 全 0
        return {"aes_key": raw, "iv": b"\x00" * 16, "raw": raw}
    if len(raw) < 48:
        raise ValueError(f"密钥长度异常: {len(raw)} 字节")
    return {"iv": raw[:16], "aes_key": raw[16:48], "tail": raw[-16:], "raw": raw}


def decrypt_chunk(data: bytes, key_hex: str, *, verify: bytes | None = None) -> bytes:
    """解密一个文件块。Steam 用 AES-256-CBC（PKCS#7 填充）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # 可选依赖

    parts = depot_key_parts(key_hex)
    dec = Cipher(algorithms.AES(parts["aes_key"]), modes.CBC(parts["iv"])).decryptor()
    out = dec.update(data) + dec.finalize()
    # 去掉 PKCS#7 填充
    if out:
        pad = out[-1]
        if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
            out = out[:-pad]
    if verify is not None and hashlib.sha1(out).digest() != verify:
        raise ValueError("解密后 SHA-1 不匹配，密钥或分块可能不对")
    return out


# ---------------------------------------------------------------------------
# 内容下载（第三方路线：不经过 Steam 的许可证体系）
# ---------------------------------------------------------------------------

#: Valve 的内容服务器。CDN 只认 (depot_id, 块 sha)，不需要 ticket。
CONTENT_SERVERS = (
    "https://steamcdn-a.akamaihd.net",
    "https://media.st.dl.eccdnx.com",
    "https://media.st.dl.eccdnx.net",
    "https://steamcontent.com",
)


def chunk_urls(depotid: int, sha_hex: str) -> list[str]:
    return [f"{srv}/depot/{depotid}/chunk/{sha_hex}" for srv in CONTENT_SERVERS]


def fetch_chunk(depotid: int, sha_hex: str, *, timeout: int = 60) -> tuple[bytes, str]:
    """下载一个块，返回 (数据, 来源 URL)。"""
    import urllib.error
    import urllib.request

    last = ""
    for url in chunk_urls(depotid, sha_hex):
        req = urllib.request.Request(url, headers={"User-Agent": "Valve/Steam HTTP Client 1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read(), url
                last = f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except Exception as exc:
            last = type(exc).__name__
    raise RuntimeError(f"所有内容服务器都失败: {last}")


def decode_chunk(raw: bytes, key_hex: str, sha: bytes) -> bytes:
    """把下载到的块还原成原始字节。

    **Steam 的真实算法**（来自 SteamKit2 `Steam/CDN/DepotChunk.cs`，已实测复现）：

        1. 取前 16 字节，用 depot 密钥做 **AES-256-ECB**（无填充）解密 → 得到真正的 IV
        2. 剩下部分用 depot 密钥 + 该 IV 做 **AES-256-CBC/PKCS7** 解密
        3. 按解密结果的前 4 字节魔数解压：
             'VSZa'      → Zstd
             'VZa'       → LZMA（Steam 的 VZip 变体）
             'PK\x03\x04' → zip
        4. 用 Adler32 校验（清单里的 chunk.checksum）

    密钥就是 32 字节；96/192-hex 这类长密钥取前 32 字节。
    """
    import lzma

    if hashlib.sha1(raw).digest() == sha:
        return raw

    # 试 AES 解密
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:  # 没有 cryptography 时用 openssl 兜底
        import subprocess
        import tempfile

        parts = depot_key_parts(key_hex)
        with tempfile.NamedTemporaryFile(delete=False) as fin:
            fin.write(raw)
            path = fin.name
        try:
            proc = subprocess.run(
                ["openssl", "enc", "-d", "-aes-256-cbc", "-nopad",
                 "-K", parts["aes_key"].hex(), "-iv", parts["iv"].hex(), "-in", path],
                capture_output=True, timeout=60,
            )
        finally:
            Path(path).unlink(missing_ok=True)
        if proc.returncode == 0:
            out = proc.stdout
            if out:
                pad = out[-1]
                if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
                    out = out[:-pad]
            if hashlib.sha1(out).digest() == sha:
                return out
            if out and hashlib.sha1(out.lstrip(b"\x00")).digest() == sha:
                return out.lstrip(b"\x00")
    else:
        parts = depot_key_parts(key_hex)
        dec = Cipher(algorithms.AES(parts["aes_key"]), modes.CBC(parts["iv"])).decryptor()
        out = dec.update(raw) + dec.finalize()
        if out:
            pad = out[-1]
            if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
                out = out[:-pad]
        if hashlib.sha1(out).digest() == sha:
            return out

    # 试 LZMA
    try:
        out = lzma.decompress(raw)
        if hashlib.sha1(out).digest() == sha:
            return out
    except Exception:
        pass

    raise ValueError(f"块无法还原（sha={sha.hex()[:16]}…, {len(raw)} 字节）")


def decode_chunk_steam(data: bytes, key_hex: str) -> tuple[bytes, str]:
    """按 Steam 的真实算法还原一个块，返回 (数据, 解压方式)。

    **已实测跑通**（用本机拥有的 Project Zomboid 做对照，解出的
    `projectzomboid.sh` 内容与 Adler32 校验全部正确）。算法来自
    SteamKit2 `Steam/CDN/DepotChunk.cs::Process`：

      1. 前 16 字节用 32 字节 depot 密钥做 **AES-256-ECB/无填充** 解密 → 得到 IV
      2. 其余数据用同一密钥 + 该 IV 做 **AES-256-CBC/PKCS7** 解密
      3. 解密结果按前 4 字节魔数解压：
           b"VSZa"      → zstd（头是 `VSZa` + 4 字节长度，zstd 帧从第 8 字节开始；
                          必须把**精确的帧长度**喂给 zstd，多喂尾部字节会报
                          `Src size is incorrect`）
           b"VZa"       → LZMA（Steam 的 VZip 变体）
           b"PK\x03\x04" → zip
      4. 用 `adler32` 与清单里的 chunk.checksum 比对（可选）

    密钥取前 32 字节（192-hex 这类长密钥的其余部分是别的用途）。
    """
    import lzma
    import subprocess
    import tempfile

    key = bytes.fromhex(key_hex)[:32]
    if len(key) != 32:
        raise ValueError(f"depot 密钥应为 32 字节，得到 {len(key)}")
    if len(data) < 32 or len(data) % 16:
        raise ValueError(f"块长度 {len(data)} 不是 16 的倍数，无法按 Steam 格式处理")

    def _openssl(mode: str, payload: bytes, iv_hex: str | None) -> bytes:
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(payload)
            path = tf.name
        try:
            args = ["openssl", "enc", "-d", f"-aes-256-{mode}", "-K", key.hex()]
            if iv_hex is not None:
                args += ["-iv", iv_hex]
            if mode == "ecb":
                args.append("-nopad")
            proc = subprocess.run(args + ["-in", path], capture_output=True, timeout=120)
        finally:
            Path(path).unlink(missing_ok=True)
        if proc.returncode != 0:
            raise ValueError(f"openssl {mode} 失败: {proc.stderr.decode(errors='replace')[:120]}")
        return proc.stdout

    iv = _openssl("ecb", data[:16], None)
    plain = _openssl("cbc", data[16:], iv.hex())

    if plain[:4] == b"VSZa":
        return _zstd(plain), "zstd"
    if plain[:3] == b"VZa":
        return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(plain[8:]), "lzma"
    if plain[:4] == b"PK\x03\x04":
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(plain)) as zf:
            return zf.read(zf.namelist()[0]), "zip"
    raise ValueError(f"未知的解压魔数: {plain[:4]!r} ({plain[:4].hex()})")


def _zstd(plain: bytes) -> bytes:
    """解 Steam 的 `VSZa` zstd 块。

    布局：`VSZa`(4) + u32(4) + zstd 帧。必须按**帧自身的压缩长度**精确切片，
    否则 libzstd 会报 `Src size is incorrect`（实测踩过这个坑）。
    """
    import ctypes

    frame = plain[8:]
    lib = ctypes.CDLL("libzstd.so.1")
    lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
    lib.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
    lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_decompress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
    lib.ZSTD_getErrorName.restype = ctypes.c_char_p

    buf = ctypes.create_string_buffer(frame, len(frame))
    size = lib.ZSTD_getFrameContentSize(buf, len(frame))
    exact = lib.ZSTD_findFrameCompressedSize(buf, len(frame))
    if lib.ZSTD_isError(exact):
        raise ValueError("zstd 帧头损坏: " + lib.ZSTD_getErrorName(exact).decode())
    dst = ctypes.create_string_buffer(size)
    written = lib.ZSTD_decompress(dst, size, buf, exact)  # 只喂精确长度
    if lib.ZSTD_isError(written):
        raise ValueError("zstd 解压失败: " + lib.ZSTD_getErrorName(written).decode())
    return dst.raw[:written]


def adler32(data: bytes) -> int:
    import zlib

    return zlib.adler32(data) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# 完整下载器：清单 + 密钥 → 磁盘上的文件
# ---------------------------------------------------------------------------

@dataclass
class DownloadStats:
    files_done: int = 0
    chunks_done: int = 0
    chunks_failed: int = 0
    bytes_written: int = 0

    def __str__(self) -> str:
        gb = self.bytes_written / 1024**3
        return (f"{self.files_done} 文件 / {self.chunks_done} 块 / {gb:.2f} GB"
                + (f" / {self.chunks_failed} 块失败" if self.chunks_failed else ""))


#: 实测可用的内容服务器（Steam 自己也在用这些）
DEFAULT_HOSTS = (
    "cache1-hkg1.steamcontent.com",
    "cache2-hkg1.steamcontent.com",
    "cache3-hkg1.steamcontent.com",
    "cache4-hkg1.steamcontent.com",
    "cache1-lax1.steamcontent.com",
    "cache2-lax1.steamcontent.com",
    "cache10-lax1.steamcontent.com",
    "steamcdn-a.akamaihd.net",
)


def download_chunk(
    depotid: int,
    chunk: "Chunk",
    key_hex: str,
    *,
    hosts: tuple[str, ...] = DEFAULT_HOSTS,
    cache_dir: Path | None = None,
    timeout: int = 40,
    retries: int = 2,
) -> bytes:
    """下载并还原一个块（带重试 + 可选磁盘缓存）。"""
    import urllib.error
    import urllib.request

    cached = cache_dir / chunk.sha_hex if cache_dir else None
    if cached and cached.is_file():
        raw = cached.read_bytes()
    else:
        raw = b""
        errors: list[str] = []
        for attempt in range(retries):
            for host in hosts:
                url = f"https://{host}/depot/{depotid}/chunk/{chunk.sha_hex}"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Valve/Steam HTTP Client 1.0"}
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        raw = resp.read()
                    break
                except urllib.error.HTTPError as exc:
                    errors.append(f"{host}:HTTP{exc.code}")
                except Exception as exc:
                    errors.append(f"{host}:{type(exc).__name__}")
            if raw:
                break
        if not raw:
            raise RuntimeError(f"下载失败 {chunk.sha_hex[:16]}…: {'; '.join(errors[:4])}")
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(raw)

    body, _how = decode_chunk_steam(raw, key_hex)
    if chunk.checksum and adler32(body) != chunk.checksum:
        raise ValueError(f"Adler32 校验失败 (块 {chunk.sha_hex[:16]}…)")
    return body


def download_depot(
    depotid: int,
    manifest: "Manifest",
    key_hex: str,
    target_dir: str | Path,
    *,
    hosts: tuple[str, ...] = DEFAULT_HOSTS,
    cache_dir: Path | None = None,
    workers: int = 8,
    progress: bool = True,
) -> DownloadStats:
    """把一个 depotid 的全部文件下载到 target_dir（多线程，逐块 Adler32 校验）。"""
    import concurrent.futures
    import threading

    target = Path(target_dir)
    stats = DownloadStats()
    lock = threading.Lock()
    total = len(manifest.files)

    # 先收集所有待下载的块任务，再一次性丢进线程池（不能在池内嵌套 map）
    jobs: list[tuple[FileMapping, int, Chunk]] = []
    for fm in manifest.files:
        if fm.size == 0:
            (target / fm.filename.replace("\\", "/")).mkdir(parents=True, exist_ok=True)
            continue
        out_path = target / fm.filename.replace("\\", "/")
        if out_path.is_file() and out_path.stat().st_size == fm.size:
            with lock:
                stats.files_done += 1
                stats.chunks_done += len(fm.chunks)
                stats.bytes_written += fm.size
            continue
        for ci, ch in enumerate(fm.chunks):
            jobs.append((fm, ci, ch))

    if not jobs:
        return stats

    results: dict[tuple[str, int], bytes] = {}
    failed_chunks = 0

    def work(job: tuple[FileMapping, int, Chunk]) -> tuple[tuple[str, int], bytes | None]:
        fm, ci, ch = job
        try:
            return (fm.filename, ci), download_chunk(
                depotid, ch, key_hex, hosts=hosts, cache_dir=cache_dir
            )
        except Exception as exc:
            print(f"    ✗ 块失败 {fm.filename} #{ci}: {exc}")
            return (fm.filename, ci), None

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for key, body in pool.map(work, jobs):
            done += 1
            if body is None:
                failed_chunks += 1
            else:
                results[key] = body
            if progress and done % 200 == 0:
                gb = sum(len(v) for v in results.values()) / 1024**3
                print(f"    块 {done}/{len(jobs)}  {gb:.2f} GB 已还原", flush=True)

    # 按文件拼装
    by_file: dict[str, dict[int, bytes]] = {}
    for (fname, ci), body in results.items():
        by_file.setdefault(fname, {})[ci] = body

    for fm in manifest.files:
        if fm.size == 0:
            continue
        out_path = target / fm.filename.replace("\\", "/")
        if out_path.is_file() and out_path.stat().st_size == fm.size:
            continue
        parts = by_file.get(fm.filename, {})
        if len(parts) != len(fm.chunks):
            continue  # 有块失败，跳过这个文件
        out_path.parent.mkdir(parents=True, exist_ok=True)
        blob = b"".join(parts[i] for i in range(len(fm.chunks)))
        out_path.write_bytes(blob)
        stats.files_done += 1
        stats.chunks_done += len(fm.chunks)
        stats.bytes_written += len(blob)

    stats.chunks_failed = failed_chunks
    return stats
