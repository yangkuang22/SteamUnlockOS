"""
解析 SteamUnlock 服务端返回的 appinfo（完整 Steam appinfo VDF）
提取：depot 列表、各分支/版本的 manifest gid、大小
"""
import re
from typing import Dict, List, Optional


def _find_block(text: str, key: str, start: int = 0) -> Optional[tuple]:
    """返回 (内容起止位置, 内容) —— 简单的 VDF 块提取（支持嵌套）"""
    m = re.compile(r'"' + re.escape(key) + r'"\s*\{').search(text, start)
    if not m:
        return None
    i = text.index("{", m.start())
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return (m.start(), j + 1, text[i + 1:j])
        j += 1
    return None


def parse_depots(appinfo: str) -> Dict[int, dict]:
    """从 appinfo 提取所有 depot 及其 manifest 信息"""
    out = {}
    blk = _find_block(appinfo, "depots")
    if not blk:
        return out
    body = blk[2]
    # 逐个 depot 块
    for m in re.finditer(r'"(\d+)"\s*\{', body):
        depid = int(m.group(1))
        sub = _find_block(body, str(depid), m.start())
        if not sub:
            continue
        content = sub[2]
        info = {"depotid": depid, "oslist": None, "manifests": {}}
        os_m = re.search(r'"oslist"\s*"([^"]*)"', content)
        if os_m:
            info["oslist"] = os_m.group(1)
        mblk = _find_block(content, "manifests")
        if mblk:
            mb = mblk[2]
            for bm in re.finditer(r'"([^"]+)"\s*\{', mb):
                branch = bm.group(1)
                bsub = _find_block(mb, branch, bm.start())
                if not bsub:
                    continue
                bc = bsub[2]
                gid_m = re.search(r'"gid"\s*"(\d+)"', bc)
                size_m = re.search(r'"size"\s*"(\d+)"', bc)
                dl_m = re.search(r'"download"\s*"(\d+)"', bc)
                if gid_m:
                    info["manifests"][branch] = {
                        "gid": int(gid_m.group(1)),
                        "size": int(size_m.group(1)) if size_m else 0,
                        "download": int(dl_m.group(1)) if dl_m else 0,
                    }
        out[depid] = info
    return out


def public_manifest(depot_info: dict) -> Optional[dict]:
    """取 public 分支（默认下载用）"""
    return depot_info.get("manifests", {}).get("public")


def branches(depot_info: dict) -> List[str]:
    return list(depot_info.get("manifests", {}).keys())
