"""Valve KeyValues (VDF) 解析器 —— 纯 stdlib，不依赖第三方 `vdf` 包。

Steam 的 config.vdf / appmanifest_*.acf / libraryfolders.vdf 都是这个格式：
  - `"key"` `"value"` 成对出现，制表符/空格/换行分隔
  - `"key"` `{ ... }` 表示嵌套
  - 支持 // 行注释、\\ 与 \" 转义
  - 裸词（不带引号的值）在少数文件里出现，容忍之

原程序用的是 `vdf.loads()`（见 RECON_SPEC.md §2.3），本模块是替代品，
接口刻意做成 `loads()/dumps()/load()` 以便将来整模块替换。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["loads", "dumps", "load", "ParseError"]

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "r": "\r"}


class ParseError(ValueError):
    """VDF 结构不合法时抛出。"""


def _unescape(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(_ESCAPES.get(text[i + 1], text[i + 1]))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _tokenize(text: str):
    """产出 ('str', 内容) / ('brace', '{'|'}')。引号只作分隔，不进内容。"""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":  # 行注释
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch in "{}":
            yield ("brace", ch)
            i += 1
            continue
        if ch == '"':
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i : i + 2])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            else:
                raise ParseError("字符串没有闭合的引号")
            yield ("str", _unescape("".join(buf)))
            continue
        # 裸词
        start = i
        while i < n and text[i] not in ' \t\r\n"{}':
            i += 1
        yield ("str", text[start:i])


def loads(text: str) -> dict:
    """把 VDF 文本解析成嵌套 dict。"""
    tokens = list(_tokenize(text))
    pos = 0

    def parse_object(depth: int) -> dict:
        nonlocal pos
        if depth > 64:
            raise ParseError("嵌套层数过深，疑似文件损坏")
        obj: dict = {}
        while pos < len(tokens):
            kind, value = tokens[pos]
            if kind == "brace":
                if value == "}":
                    pos += 1
                    return obj
                raise ParseError(f"位置 {pos} 出现意外的 '{{'")
            key = value
            pos += 1
            if pos >= len(tokens):
                raise ParseError(f"键 {key!r} 后面缺少值")
            kind2, value2 = tokens[pos]
            if kind2 == "brace":
                if value2 != "{":
                    raise ParseError(f"键 {key!r} 的值是孤立的 '}}'")
                pos += 1
                obj[key] = parse_object(depth + 1)
            else:
                obj[key] = value2
                pos += 1
        raise ParseError(f"对象没有闭合（在键 {key!r} 之后遇到文件结尾）")

    root: dict = {}
    while pos < len(tokens):
        kind, value = tokens[pos]
        if kind == "brace":
            raise ParseError(f"顶层出现意外的 {value!r}")
        key = value
        pos += 1
        if pos >= len(tokens):
            raise ParseError(f"顶层键 {key!r} 缺少值")
        kind2, value2 = tokens[pos]
        if kind2 == "brace":
            if value2 != "{":
                raise ParseError(f"顶层键 {key!r} 的值是孤立的 '}}'")
            pos += 1
            root[key] = parse_object(1)
        else:
            root[key] = value2
            pos += 1
    return root


def dumps(obj: dict, indent: int = 0) -> str:
    """回写 VDF（Steam 风格：制表符缩进）。"""
    pad = "\t" * indent
    lines = []
    for key, value in obj.items():
        if isinstance(value, dict):
            lines.append(f'{pad}"{_escape(str(key))}"')
            lines.append(f"{pad}{{")
            body = dumps(value, indent + 1)
            if body:
                lines.append(body)
            lines.append(f"{pad}}}")
        else:
            lines.append(f'{pad}"{_escape(str(key))}"\t\t"{_escape(str(value))}"')
    return "\n".join(lines)


def load(path: str | Path) -> dict:
    """读取并解析一个 VDF 文件。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return loads(text)
