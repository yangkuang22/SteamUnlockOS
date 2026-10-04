#!/bin/bash
# ============================================================
# 用 GitHub REST API 推送（本机 git 协议不稳定时使用）
#
# 为什么需要这个:
#   这台机器上 git push 经常失败（TLS unexpected eof）
#   但 api.github.com 一直可用（HTTP 200）
#   → 所以用 API 创建 blob/tree/commit 再更新 ref
#
# 用法: bash scripts/push-github.sh ["提交信息"]
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
git config core.quotepath false 2>/dev/null

MSG="${1:-更新: $(date '+%Y-%m-%d %H:%M')}"
TOKFILE="$HOME/.config/SteamUnlockOS/github_token"
if [ ! -f "$TOKFILE" ]; then
    echo "✗ 找不到 token: $TOKFILE"; exit 1
fi

python3 - "$MSG" <<'PYEOF'
import base64, json, os, subprocess, sys, urllib.request, urllib.error

MSG = sys.argv[1]
TOK = open(os.path.expanduser('~/.config/SteamUnlockOS/github_token')).read().strip()
OWNER, REPO = "yangkuang22", "steam-toolkit"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"

def gh(path, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"{API}{path}", data=body, method=method, headers={
        "Authorization": f"Bearer {TOK}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Steam Toolkit",
        "Content-Type": "application/json",
    })
    try:
        return json.loads(urllib.request.urlopen(req, timeout=90).read())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "__body__": e.read().decode()[:300]}

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()

# 远程当前状态
ref = gh("/git/ref/heads/main")
if "__error__" in ref:
    print("✗ 拿远程 ref 失败:", ref); sys.exit(1)
parent = ref["object"]["sha"]
ptree = gh(f"/git/commits/{parent}")["tree"]["sha"]
remote_tree = gh(f"/git/trees/{ptree}?recursive=1")
remote_files = {t["path"]: t["sha"] for t in remote_tree.get("tree", []) if t["type"] == "blob"}

# 本地所有文件
local_files = git("ls-files").split("\n")
local_files = [f for f in local_files if f]

print(f"  远程提交: {parent[:12]}")
print(f"  远程文件: {len(remote_files)}   本地: {len(local_files)}")

# 计算需要上传的（对比 git 的 blob hash 和远程 sha 不可直接比，
# 所以用文件内容 hash 比对：简单起见上传所有变化的文件）
entries = []
skipped = 0
for path in local_files:
    full = os.path.join(os.getcwd(), path)
    if not os.path.isfile(full):
        continue
    data = open(full, "rb").read()
    # 用 git hash-object 算本地 blob hash
    local_sha = git("hash-object", path)
    remote_sha = remote_files.get(path)
    if local_sha == remote_sha:
        skipped += 1
        continue
    r = gh("/git/blobs", "POST", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
    if "sha" not in r:
        print(f"  ✗ {path}: {str(r)[:120]}")
        continue
    mode = "100755" if os.access(full, os.X_OK) else "100644"
    entries.append({"path": path, "mode": mode, "type": "blob", "sha": r["sha"]})
    print(f"  ↑ {path}")

# 删除远程多余的文件
for path in remote_files:
    if path not in local_files:
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        print(f"  ✗ {path}（删除）")

print(f"  未变: {skipped}   变更: {len(entries)}")
if not entries:
    print("  ✓ 已是最新，无需推送")
    sys.exit(0)

tree = gh("/git/trees", "POST", {"base_tree": ptree, "tree": entries})
if "sha" not in tree:
    print("  ✗ 创建 tree 失败:", str(tree)[:200]); sys.exit(1)

commit = gh("/git/commits", "POST", {
    "message": MSG, "tree": tree["sha"], "parents": [parent],
    "author": {"name": git("config", "user.name") or "dev",
               "email": git("config", "user.email") or "dev@local"},
})
if "sha" not in commit:
    print("  ✗ 创建提交失败:", str(commit)[:200]); sys.exit(1)

upd = gh("/git/refs/heads/main", "PATCH", {"sha": commit["sha"]})
if "__error__" in upd:
    print("  ✗ 更新 ref 失败:", str(upd)[:200]); sys.exit(1)
print(f"  ✓ 已推送到 GitHub: {commit['sha'][:12]}")
PYEOF
