#!/usr/bin/env bash
# ============================================================================
# Steam Toolkit —— SLSsteam 安装/更新脚本（SteamOS / ROG Ally 等 holo 系）
#
# 干什么：
#   1. 从 GitHub 拉最新 SLSsteam release
#   2. 解压到 ~/.local/share/SLSsteam        （用户目录，随时可删）
#   3. 生成 ~/.config/SLSsteam/config.yaml   （并强制打开 SafeMode）
#   4. 备份旧的 config.yaml（如果存在）
#
# 不干什么：**不碰任何系统文件**（不改 /usr/bin/steam、不改只读根）。
#
# 用法：bash ~/steam-toolkit/scripts/setup-slssteam.sh
# ============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 项目根目录：从脚本位置推导，不写死目录名（新旧安装都适用）

SLS_HOME="$HOME/.local/share/SLSsteam"
SLS_CFG_DIR="$HOME/.config/SLSsteam"
SLS_CFG="$SLS_CFG_DIR/config.yaml"
BACKUP_DIR="$ROOT/backup"
API="https://api.github.com/repos/AceSLS/SLSsteam/releases/latest"

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || die "需要 curl"
command -v 7z >/dev/null || command -v 7za >/dev/null || die "需要 7z 或 7za（SteamOS 自带 7z）"

say "── 1/4 查询最新版本 ──"
META=$(timeout 60 curl -fsSL "$API") || die "无法访问 GitHub API（网络问题）"
URL=$(printf '%s' "$META" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('版本:', d['tag_name'])
for a in d['assets']:
    if a['name'].endswith('Any-release.7z'):
        print(a['browser_download_url'])
" | tail -1)
TAG=$(printf '%s' "$META" | python3 -c "import json,sys;print(json.load(sys.stdin)['tag_name'])")
say "最新版本: $TAG"
say "下载地址: $URL"

say "── 2/4 下载并解压 ──"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
timeout 600 curl -fL --progress-bar "$URL" -o "$TMP/sls.7z" || die "下载失败"
( cd "$TMP" && 7z x -y sls.7z >/dev/null ) || die "解压失败"

mkdir -p "$SLS_HOME"
LIB=$(find "$TMP" -name 'SLSsteam.so' -print -quit)
INJ=$(find "$TMP" -name 'library-inject.so' -print -quit)
[ -n "$LIB" ] || die "包里没找到 SLSsteam.so"
[ -n "$INJ" ] || die "包里没找到 library-inject.so"
cp -f "$LIB" "$SLS_HOME/SLSsteam.so"
cp -f "$INJ" "$SLS_HOME/library-inject.so"
# 其余文件（yaml 模板、tools 等）一并放过去，SLSsteam 可能需要
for extra in config.yaml updates.yaml tools; do
    found=$(find "$TMP" -maxdepth 3 -name "$extra" -print -quit)
    [ -n "$found" ] && cp -rf "$found" "$SLS_HOME/" 2>/dev/null || true
done
say "✓ 已安装到 $SLS_HOME"
ls -l "$SLS_HOME" | sed 's/^/   /'

say "── 3/4 备份并准备配置 ──"
mkdir -p "$SLS_CFG_DIR" "$BACKUP_DIR"
if [ -f "$SLS_CFG" ]; then
    cp "$SLS_CFG" "$BACKUP_DIR/config.yaml.$(date +%Y%m%d-%H%M%S).bak"
    say "✓ 已备份原配置到 $BACKUP_DIR"
fi

python3 - "$SLS_CFG" "$SLS_HOME/config.yaml" <<'PY'
import sys, pathlib
target = pathlib.Path(sys.argv[1])
template = pathlib.Path(sys.argv[2])

text = ""
if target.exists():
    text = target.read_text(encoding="utf-8", errors="replace")
elif template.exists():
    text = template.read_text(encoding="utf-8", errors="replace")

def force(text: str, key: str, value: str) -> str:
    """把 key 的值强制设为 value（不存在则追加）。"""
    out, done, lines = [], False, text.splitlines()
    import re
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for line in lines:
        if pat.match(line):
            out.append(f"{key}: {value}")
            done = True
        else:
            out.append(line)
    if not done:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}: {value}")
    return "\n".join(out) + "\n"

if not text.strip():
    text = "AppIds:\nAdditionalApps:\nManifestIds:\nCDKeys:\nAppTokens:\n"

# SafeMode 是 SteamOS 上官方强烈建议打开的：steamclient.so 哈希不匹配时自动停用自己
text = force(text, "SafeMode", "yes")
text = force(text, "NotifyInit", "yes")
target.write_text(text, encoding="utf-8")
print(f"✓ 配置就绪: {target}（SafeMode: yes）")
PY

say "── 4/4 完成 ──"
cat <<EOF

下一步（两条路，选一条）：

  A. 桌面模式下让 Steam 自己启动时带上注入（官方做法，要改系统文件）
     - 先确认 Steam 能正常启动，再执行：
       sudo steamos-readonly disable
       sudo nano /usr/bin/steam      # 在最后一行 exec 之前加：
       export LD_AUDIT="$SLS_HOME/library-inject.so:$SLS_HOME/SLSsteam.so"
     - 改完立刻完全退出 Steam 再启动一次，确认没崩。（崩了就把那行删掉）

  B. 用我们的启动器（推荐，不碰系统文件）
       python3 -m suos.cli launch
     它用同样的 LD_AUDIT 参数启动 Steam，且失败不会影响开机。

装完自检：
       python3 -m suos.cli status
EOF
