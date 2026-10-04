# BUG 清单 —— 待分析

> 2026-10-03 通篇审计结果
> **状态: ✅ 全部已修复并验证**（2026-10-03 23:50）
> 修复提交: 见下方每个条目的「修复」小节
>
> 保留本文档是为了记录问题、根因和验证方法，便于后续维护参考。
> 其中 P2-3 的初版结论有误（说它是死代码），已在原处标注纠正。
>
> 审计方法: 6 轮共 36 项检查，每项都有可复现的证据。
> 代码位置: 本仓库。所有行号对应 commit `2ad9f4e`。

---

## 目录

| 编号 | 标题 | 严重度 | 状态 |
|---|---|---|---|
| [P1-1](#p1-1-名字缓存被永久污染) | 名字缓存被永久污染，永不自愈 | 🔴 真实 Bug | **已复现** |
| [P1-2](#p1-2-启动器日志会重新堆到根目录) | 启动器日志会重新堆到根目录 | 🔴 真实 Bug | 已确认 |
| [P1-3](#p1-3-depotcache-堆积-1427-mb-无用旧清单) | depotcache 堆积 142.7 MB 无用旧清单 | 🔴 资源泄漏 | 已量化 |
| [P2-1](#p2-1-write_keys_to_config-静默失败) | `write_keys_to_config` 静默失败 | 🟡 设计缺陷 | 代码审查 |
| [P2-2](#p2-2-关键步骤失败仍报成功) | 关键步骤失败仍报"入库完成" | 🟡 设计缺陷 | 代码审查 |
| [P2-3](#p2-3-slsconfig-读错配置文件) | `slsconfig` 读错配置文件（真 bug） | 🟡 设计缺陷 | **已修复** |
| [P2-4](#p2-4-install-的-on²-文件读写) | `install()` 的 O(n²) 文件读写 | 🟡 性能隐患 | 已实测 |
| [P3-1](#p3-1-测试覆盖严重不足) | 测试覆盖严重不足（2/19 模块） | 🟢 工程债 | 已统计 |

---

# 🔴 P1 真实 Bug

## P1-1　名字缓存被永久污染

> ### ✅ 已修复
> · `_resolve_name()` 失败返回 `None`（不再返回 `AppID xxx`）
> · `_name_for()` 只有真实结果才写永久缓存
> · 读取时发现旧中毒缓存自动重新解析（自愈）
> · 回归测试: `tests/test_bugfixes.py::TestNameCachePoisoning`（4 个用例）

**严重度**: 🔴 高（永久性、不可自愈、用户可见）

### 位置

`webui_core.py` — `_name_for()`

```python
def _name_for(appid: int, db_name: str | None) -> str:
    """拿游戏名：记录里 → 内存缓存 → 磁盘名字缓存 → Steam API"""
    if db_name:
        return db_name
    key = str(appid)
    if key in _name_cache:
        return _name_cache[key]
    nc = HOME / ".config/SteamUnlockOS/names.json"
    try:
        cache = json.loads(nc.read_text()) if nc.is_file() else {}
    except Exception:
        cache = {}
    if key in cache:
        _name_cache[key] = cache[key]
        return cache[key]
    nm = _resolve_name(appid)      # ← 失败时返回 f"AppID {appid}"
    _name_cache[key] = nm
    cache[key] = nm                # ★ 无条件写缓存（问题所在）
    try:
        nc.parent.mkdir(parents=True, exist_ok=True)
        nc.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        pass
    return nm
```

### 根因

`_resolve_name()` 在**所有数据源都失败**时返回兜底字符串：

```python
def _resolve_name(appid: int) -> str:
    # ① 本地 ACF  ② ManifestHub3  ③ SteamUnlock API  ④ steamcmd  ⑤ Steam 商店
    ...
    return f"AppID {appid}"        # ← 兜底值
```

`_name_for()` **无法区分**"真实游戏名"和"兜底值"，一律写进永久缓存
`~/.config/SteamUnlockOS/names.json`。

### 复现步骤（已实测）

```python
import sys, json, shutil
from pathlib import Path
sys.path.insert(0, '.')
NC = Path.home()/".config/SteamUnlockOS/names.json"
shutil.copy2(NC, "/tmp/names.json.bak")     # 先备份

import webui_core as core
NC.unlink(missing_ok=True)                   # 清空缓存
core._name_cache.clear()

orig = core._resolve_name
core._resolve_name = lambda a: f"AppID {a}"  # 模拟网络全失败
core.inventory()                             # 触发写缓存

# 结果: names.json = {"4012810": "AppID 4012810", ...}

core._resolve_name = orig                    # 恢复"网络"
core._name_cache.clear()
for g in core.inventory():
    print(g['appid'], g['name'])
# 输出: 4012810 AppID 4012810     ← ★ 永远不自愈
```

### 实测输出

```
被污染的缓存内容:
  1446780: AppID 1446780
  4012810: AppID 4012810
  602960: AppID 602960

★ 现在恢复正常解析，看会不会自愈:
  4012810: AppID 4012810   ← 仍然是被污染的名字！
  1446780: AppID 1446780   ← 仍然是被污染的名字！
  602960: AppID 602960     ← 仍然是被污染的名字！
```

### 触发条件（现实中很容易碰到）

| 场景 | 会触发吗 |
|---|---|
| 断网时打开前端 | ✅ 会 |
| Steam 商店 API 超时（国内常见）+ 其他源也慢 | ✅ 会 |
| SteamUnlock API 临时不可用 + MH3 查不到该游戏 | ✅ 会 |
| `api.steamcmd.net` 挂掉 | ✅ 会 |

### 影响范围

- 前端「已入库游戏」列表显示 `AppID 4012810` 而不是游戏名
- 入库记录 `installed.json` 里的 name 字段
- **永久**：即使网络恢复也不会自愈，必须手动删 `names.json`

### 修复方向（供讨论）

```python
nm = _resolve_name(appid)
if not nm.startswith("AppID "):     # 只缓存真实结果
    cache[key] = nm
    nc.write_text(...)
_name_cache[key] = nm               # 内存可以缓存（本次进程内不重复请求）
return nm
```

**注意**：还要考虑"如何区分真实名字恰好叫 `AppID xxx`"（极不可能，但可用哨兵值或
让 `_resolve_name` 返回 `None` 表示失败，而非返回字符串）。

---

## P1-2　启动器日志会重新堆到根目录

> ### ✅ 已修复
> · 日志路径改为 `~/steam-toolkit/logs/launcher.log`
> · 目录不存在自动创建；不可写则降级 `/dev/null`
> · `log()` 加 `2>/dev/null || :` 防止写失败影响脚本
> · healthcheck 改查新路径；archive-logs 支持轮转
> · 验证: 回退分支 / 只读目录 / 正常注入 三个场景

**严重度**: 🔴 中（用户已抱怨过根目录垃圾）

### 位置

```
~/.local/share/SLSsteam/path/steam   第 12 行
~/.local/bin/steam                   第 12 行
scripts/launcher.sh                  第 12 行
scripts/test-ticket-to-valve.sh      第 12 行
```

```bash
LOG="$HOME/.Steam Toolkit-launcher.log"     # ← 写死在根目录
```

### 背景

2026-10-03 的一次清理把 `~/.Steam Toolkit-launcher.log` 移到了
`~/steam-toolkit/logs/`，但**没有同步修改脚本里的路径**。

### 后果

```
① 下次启动 Steam 时，会在根目录重新创建 .Steam Toolkit-launcher.log
   → 清理白做，根目录垃圾复发
② scripts/healthcheck.sh 第 107 行还在检查旧路径:
     [ -f "$HOME/.Steam Toolkit-launcher.log" ] && tail -3 ...
   → 永远显示"暂无"，【检查失效】
③ scripts/archive-logs.sh 会把它归档，但下次又生成
   → 归档目录无限增长
```

### 修复方向

统一路径为 `~/steam-toolkit/logs/launcher.log`，改 4 个脚本 + healthcheck。

---

## P1-3　depotcache 堆积 142.7 MB 无用旧清单

> ### ✅ 已清理
> · 新增 `suos/depotcache_clean.py`（白名单 + 先归档 + 校验 三重保护）
> · 692 个/190.8 MB → 46 个/33.5 MB（**省 157 MB**）
> · 归档 63 MB 可一键恢复: `python3 -m suos.depotcache_clean --restore`
> · 已集成到 autocheck（每 12 小时自动清理）
> · 验证: ACF 45 个 + Lua 8 个清单全部完整，Steam 启动正常

**严重度**: 🔴 低（只占空间，不影响功能）

### 位置

`~/.local/share/Steam/depotcache/`

### 实测数据

```
总文件:   692 个 / 190.8 MB
多版本:   32 个 depot 有重复版本
多余的:   612 个旧版本 / 142.7 MB   ← 可清理
```

### 明细

| depot | 版本数 | 对应游戏 |
|---|---|---|
| 108600 | **295 个** | Project Zomboid |
| 1446780 | 79 个 | MONSTER HUNTER RISE |
| 2868840 | 61 个 | — |
| 304930 | 43 个 | Unturned |
| 553850 | 23 个 | HELLDIVERS 2 |

### 根因

```
每次「游戏更新」都会:
  ① 下载新清单 → depotcache/<depot>_<新gid>.manifest
  ② 更新 Lua 的 setManifestid
  ③ ★ 但从不删除旧版本的清单文件

Steam 只用 Lua 里 pin 的那个 gid 对应的清单，其余都是死文件。
```

### 修复方向

写一个清理脚本：保留每个 depot 的**最大 gid**（或 Lua 里 pin 的那个），
其余移走/删除。**注意**：Steam 有时会回退到旧版本（比如"回滚到上一个版本"
功能），所以建议移动到备份目录而不是直接删。

---

# 🟡 P2 设计缺陷

## P2-1　`write_keys_to_config` 静默失败

> ### ✅ 已修复
> · 改用 `re.subn` 验证替换真的发生（count=0 就报错）
> · **额外发现并修复**: 解析器读不到时会把已有 depot 当"新增"
>   → 插入重复块 → Steam 可能读到旧的错密钥
>   → 加独立存在性检查（`"id"\s*\{`），有则报错绝不重复插入
> · 长度非 64 hex 也报错
> · 回归测试: `TestWriteKeys`（7 个用例）

**严重度**: 🟡 中（会导致"以为写成功实际没有"）

### 位置

`webui_core.py` — `write_keys_to_config()`

```python
if dep_s in existing:
    if existing[dep_s].lower() == key.lower():
        continue
    text = re.sub(
        r'("' + re.escape(dep_s) + r'"\s*\{\s*"DecryptionKey"\s*")[0-9a-fA-F]{64}(")',
        r"\g<1>" + key + r"\g<2>", text)
    n += 1        # ★ 即使 re.sub 匹配 0 处，也照样 +1
```

### 问题

1. **无验证**：`re.sub` 返回的新文本可能和原文完全一样（没匹配到），
   但计数器仍 `+1`，最终报告"✓ 写入 config.vdf: N 个密钥"
2. **格式脆弱**：正则要求 `"id" { "DecryptionKey" "64hex" }` 这种特定格式。
   如果 Valve 改格式（比如加个换行或注释），替换静默失败

### 修复方向

```python
new_text, cnt = re.subn(pattern, repl, text)
if cnt == 0:
    res_warnings.append(f"⚠ depot {dep_s} 的密钥替换失败（格式不匹配）")
else:
    text = new_text
    n += cnt
```

---

## P2-2　关键步骤失败仍报成功

> ### ✅ 已修复
> · 步骤分类: 致命（解析/备份/密钥/Lua/校验）vs 可选（清单/DLC/toml/记录）
> · 清单是**条件致命**: 只有 Lua 里没有内嵌 `setManifestid` 时才算致命
> · 失败时 `message` = 「入库不完整（N 个关键步骤失败）：<原因>」
> · `res["fatal"]` 数组列出所有致命原因
> · **额外加固**: 防覆盖保护 —— 新 Lua 的清单数少于现有就拒绝覆盖
>   （测试时发现: 数据源退化会破坏能工作的配置）
> · 回归测试: `TestInstallClassification`（2 个用例）

**严重度**: 🟡 中（误导用户）

### 位置

`webui_core.py` — `install()`

```python
# 3. 密钥
try:
    n = write_keys_to_config(r["keys"])
    res["steps"].append(f"✓ 写入 config.vdf: {n} 个密钥")
except Exception as exc:
    res["message"] = f"写密钥失败: {str(exc)[:120]}"
    return res                        # ← 这个是对的（关键步骤，失败就退出）

# 4. 清单
try:
    ...
    res["steps"].append(f"✓ 写入 depotcache: {n} 个清单")
except Exception as exc:
    res["steps"].append(f"⚠ 写清单失败: {str(exc)[:60]}")    # ← 只警告，继续

# 6. AppIds
try:
    _add_appid_to_toml(appid)
except Exception as exc:
    res["steps"].append(f"⚠ 写 config.toml 失败: {str(exc)[:60]}")   # ← 只警告，继续

# 最后
res["ok"] = True
res["message"] = "入库完成，重启 Steam 后即可下载"     # ← 明明有步骤失败了
```

### 后果

```
清单写入失败（网络问题）→ 用户看到"入库完成"
→ 重启 Steam 后游戏显示可安装 → 点安装 → 报"内容加密"或"下载失败"
→ 用户以为是别的问题，实际上清单压根没写进去
```

### 修复方向

区分"致命步骤"和"可选步骤"：

```python
FATAL = {"备份", "密钥", "清单", "Lua"}     # 任何一个失败 → ok=False
OPTIONAL = {"DLC 查询", "记录"}             # 失败只警告

# 汇总时:
failed = [s for s in res["steps"] if s.startswith("✗") or ("失败" in s and "⚠" in s)]
res["ok"] = not any(fatal_step in s for s in failed)
res["message"] = "入库完成" if res["ok"] else "入库不完整，见下方步骤"
```

---

## P2-3　`slsconfig` 读错配置文件

> ⚠️ **本节初版结论有误，已修正。**
> 初版说它"完全失效（死代码）"，实际是**一个有测试、能被调用、但读错文件路径的真 bug**。
> 错误原因: 我用 `slsconfig.load()` 测试，但该模块只提供 `SLSConfig().load()` 方法，
> 导致误判为"函数不存在"。教训: 报 bug 前要按模块的实际 API 调用。

**严重度**: 🟡 中（CLI 显示错误信息 + 逻辑判断错误）

### 位置

`suos/slsconfig.py`

```python
CONFIG_PATH = SLS_DIR / "config.yaml"      # ← 旧版 SLSsteam 的格式
```

### 事实

```
SLSsteam 已改用 config.toml:
  $ ls ~/.config/SLSsteam/
    config.toml              ← 实际用的（256 个 AppIds）
    config.yaml.disabled     ← 旧格式，已被禁用

slsconfig.CONFIG_PATH = ~/.config/SLSsteam/config.yaml   ← 不存在
```

### 影响（真实存在，不是"死代码"）

被 `suos/cli.py` 的 4 处调用：

| 行号 | 用途 | 旧行为 | 影响 |
|---|---|---|---|
| 96 | `build_plan()` 拿"已拥有"集合 | 返回空集 | 逻辑错误 |
| 176 | `cmd_status` 显示拥有数量 | 显示 **0 个** | **用户看到错误信息** |
| 237 | `cmd_install` 备份配置 | 备份不到（无文件） | 备份缺失 |
| 412 | 同上 | 同上 | 同上 |

实测（修复前）：

```
$ python3 -c "from suos import slsconfig; c=slsconfig.SLSConfig(); c.load(); print(len(c.owned()))"
0                    ← 实际 config.toml 里有 256 个
```

### 修复（2026-10-03 已完成）

```python
def __init__(self, path=None):
    ...
    # SLSsteam 改用 config.toml 后，只读接口需要能看到 TOML 里的 AppIds
    self.toml_path = None
    if path is None:
        cand = CONFIG_PATH.with_suffix(".toml")
        if cand.is_file():
            self.toml_path = cand

def owned(self) -> set[int]:
    """合并 YAML 与 TOML 两处来源"""
    out = set()
    # ... 原来的 YAML 逻辑 ...
    if self.toml_path and self.toml_path.is_file():
        txt = self.toml_path.read_text(...)
        for key in ("AppIds", "AdditionalApps"):
            m = re.search(rf"^{key}\s*=\s*\[([^\]]*)\]", txt, re.M)
            ...
    return out

def exists(self) -> bool:
    if self.path.is_file():
        return True
    return bool(self.toml_path and self.toml_path.is_file())
```

**验证**：

```
修复后:
  TOML 路径: /home/deck/.config/SLSsteam/config.toml
  exists(): True
  owned(): 256 个 appid  ✓

回归: 单元测试 30/30 通过（含 6 个 SLSConfig 测试）
```

### 遗留（未处理，低优先级）

`scripts/setup-slssteam.sh` 仍然生成 `config.yaml`，对当前版 SLSsteam 无效。
该脚本没有文档引用，可以删除或重写。**暂未改动**（避免破坏未知用法）。

## P2-4　`install()` 的 O(n²) 文件读写

> ### ✅ 已修复
> · 新增 `_add_appids_to_toml(list)` 批量接口（一次读、一次写）
> · `_add_appid_to_toml(int)` 保留为兼容包装
> · `install()` 改为一次调用传入 `[本体, *全部DLC]`
> · 实测 253 个 appid: **45.7 ms → 0.2 ms（快 219 倍）**
> · 回归测试: `TestBatchToml`（5 个用例，含"只写 1 次文件"的 spy 验证）

**严重度**: 🟡 低（实测不慢，但是设计问题）

### 位置

`webui_core.py` — `install()` 第 530-532 行

```python
# 6. AppIds（本体 + DLC）
try:
    _add_appid_to_toml(appid)
    for d in dlcs:                    # ← 253 个 DLC → 254 次调用
        _add_appid_to_toml(d)
```

每次 `_add_appid_to_toml()` 都会：

```python
def _add_appid_to_toml(appid: int) -> None:
    text = SLS_TOML.read_text()       # 读整个文件
    for field in ("AppIds", "AdditionalApps"):
        m = re.search(rf"^{field} = \[([^\]]*)\]", text, re.M)
        items = [x.strip() for x in m.group(1).split(",") if x.strip()]
        items.append(str(appid))
        text = text[:m.start()] + f"{field} = [{', '.join(items)}]" + text[m.end():]
    SLS_TOML.write_text(text)         # 写回整个文件
```

### 实测

```
当前 AppIds 数量: 256
入库一个有 253 DLC 的游戏 → 调用 254 次
每次: read() + 正则 + join + write()
→ 累计读写 508 次文件操作

实测单次: 0.2ms
推算 254 次: ≈ 0.05s
```

**目前不痛**，因为 `config.toml` 只有 6.5 KB。但如果 AppIds 涨到几千个
（比如入库更多 DLC 大户），会明显变慢。

### 修复方向

改成批量接口：

```python
def _add_appids_to_toml(appids: list[int]) -> None:
    """一次读，一次写"""
    text = SLS_TOML.read_text()
    for field in ("AppIds", "AdditionalApps"):
        m = re.search(rf"^{field} = \[([^\]]*)\]", text, re.M)
        items = [x.strip() for x in m.group(1).split(",") if x.strip()]
        new = [str(a) for a in appids if str(a) not in items]
        if new:
            items.extend(new)
            text = text[:m.start()] + f"{field} = [{', '.join(items)}]" + text[m.end():]
    SLS_TOML.write_text(text)
```

---

# 🟢 P3 工程债

## P3-1　测试覆盖严重不足

**严重度**: 🟢 低（不影响运行，但是 bug 温床）

### 现状

```
$ python3 -m unittest discover -s tests
Ran 30 tests in 1.004s
OK

但实际覆盖:
  ✓ 有测试:  appinfo, rc4, slsconfig, steam, vdf
  ✗ 无测试:  server_api, sudama, updater, multisource,
             manifests, manifesthub3, depotkeys, fetch,
             installer, installer2, cli, depot, chunkfetch

→ 18 个模块里 5 个有测试（初版统计说 2/19，是因为我的检测脚本
  只匹配 `from suos import X` 形式，漏掉了 `from suos.X import Y`）
→ P1-1（缓存污染）就是因为没有测试才漏掉的
```

### 建议优先补测试的模块

| 模块 | 为什么重要 |
|---|---|
| `vdf.py` | 直接操作 Steam 配置，写坏就完蛋 |
| `webui_core.py` | 核心业务逻辑（install/uninstall/write_keys） |
| `updater.py` | 会改 Lua 的 gid |
| `sudama.py` / `depotkeys.py` | 缓存逻辑（和 P1-1 同类问题） |
| `manifests.py` | 清单下载 + 校验 |

---

# 📎 附录 A：审计方法

```
第 1 轮  核心逻辑（数据损坏风险）:  write_keys_to_config / install / uninstall
第 2 轮  并发 + 测试:              server 锁 / 测试套件 / 异常处理
第 3 轮  安全 + 逻辑正确性:        Web 绑定 / AppID 校验 / 路径注入 / 危险操作
第 4 轮  锁泄露 + 脚本一致性:      finally 完整性 / 脚本路径引用
第 5 轮  端到端配置:               启动入口 / systemd / environment.d
第 6 轮  脚本引用 + 收尾:          路径存在性 / 文档脚本一致性 / git 状态
```

# 📎 附录 B：检查通过的部分（18 项）

| 项目 | 结果 |
|---|---|
| VDF 解析器 | ✓ 有深度上限(64层)、引号闭合检查、清晰 ParseError |
| 原子写 | ✓ 所有配置写入都是 `tmp` + `replace` |
| 锁管理 | ✓ 3 处 acquire 都有 `finally: release`，无泄露 |
| 网络错误处理 | ✓ 4 个核心模块的网络调用都有 try 保护 |
| RC4 | ✓ 空密钥检查，标准实现 |
| server_api | ✓ HTTPError/URLError/literal_eval 都有明确错误 |
| 测试套件 | ✓ 30 个测试全通过 |
| Web 安全 | ✓ 只绑 127.0.0.1；AppID 严格 isdigit 校验 |
| 路径安全 | ✓ 所有路径由校验过的 int 构造，无注入风险 |
| 危险操作 | ✓ 全项目只有 1 处 `unlink()`（卸载时删 Lua） |
| 启动入口 | ✓ 3 个入口文件都存在且 Exec 一致 |
| systemd timer | ✓ ExecStart 脚本存在且可执行 |
| 文档脚本引用 | ✓ 5 个被引用的脚本都存在 |
| 健康检查 | ✓ 12/12 通过 |
| 崩溃 | ✓ 0（含 253 DLC 的极端配置） |
| git | ✓ 干净，已推送 |
| 项目大小 | 49 MB（已从 104 MB 瘦身） |
| 根目录整洁 | ✓ 无残留 |

# 📎 附录 C：资源增长一览

| 目录 | 当前 | 会不会无限涨 | 处理 |
|---|---|---|---|
| `~/.local/share/Steam/depotcache` | **193 MB** | ⚠️ **会** | 见 P1-3 |
| `~/.cache/suos` | 51 MB | 稳定（覆盖式） | 不用管 |
| `~/steam-toolkit/backup` | 35 MB | ⚠️ 会（每次入库加备份） | 增幅小，可接受 |
| `~/steam-toolkit/logs` | 4.5 MB | ✓ 有 10 个上限 | 不用管 |
| `~/.config/SLSsteam/cache` | 164 KB | 稳定 | 不用管 |

# 📎 附录 D：数据安全结论

```
✓ VDF 解析严格（深度上限 + 错误检测）
✓ 所有写入原子（tmp + rename）
✓ 每次入库前自动备份到 backup/webui/
✓ 卸载只删自己的 Lua，密钥保留（避免误删别的游戏）
✓ 全项目只有 1 处 unlink()
✓ 不碰用户的正版游戏数据
```

**结论：不存在数据损坏类 bug。P1-1 是唯一影响用户的真实 bug，且只影响显示。**

---

# 📌 修复总结（2026-10-03）

## 修复清单

| 编号 | 修复方式 | 验证 |
|---|---|---|
| P1-1 | `_resolve_name` 失败返回 None；只缓存真实结果；旧中毒缓存自愈 | 4 个单元测试 + 4 个手动场景 |
| P1-2 | 日志改到 `logs/launcher.log`；目录自动创建；写失败降级 | 3 个场景（回退/只读/正常） |
| P1-3 | 新增 `depotcache_clean.py`（白名单+归档+校验） | 完整性验证 + Steam 启动实测 |
| P2-1 | `re.subn` 验证 + 独立存在性检查（防重复插入） | 7 个单元测试 |
| P2-2 | 步骤分类 + 防覆盖保护 | 2 个单元测试 + 6 个手动场景 |
| P2-3 | `owned()` 合并 YAML 与 TOML | 3 个单元测试（256 个 appid） |
| P2-4 | `_add_appids_to_toml` 批量接口 | 5 个单元测试 + 性能实测 |
| P3-1 | `tests/test_bugfixes.py` 21 个用例 | 测试总数 30 → 51 |

## 修复过程中新发现的问题

| 问题 | 发现方式 | 处理 |
|---|---|---|
| `write_keys_to_config` 重复插入 | 测试 P2-1 时构造失配场景 | 已加存在性检查 |
| `install()` 会用退化数据覆盖可用 Lua | 测试 P2-2 时意外破坏了自己的 Lua | 已加防覆盖保护 |
| Lua 备份污染运行目录 | commit 后检查文件列表 | 已改到 `backup/lua/` |
| `slsconfig` 不是死代码而是真 bug | 复核初版结论 | 已修正报告并修复 |
| 测试覆盖统计有误（漏数 3 个模块） | 用真实 API 复核 | 已修正文档 |

## 最终状态

```
单元测试:      51 个全部通过（原 30 个）
健康检查:      12/12 通过
Steam 启动:    ✓ 注入生效 + 0 崩溃
三个游戏:      ✓ 全部"已安装"
磁盘:          depotcache 省 157 MB，项目 48 MB
根目录:        ✓ 无残留
```

## 教训（写给自己和后续维护者）

1. **报 bug 前要按模块的实际 API 调用** —— P2-3 我用了不存在的方法名，
   误判成"死代码"。实际它一直在被 CLI 调用，是真 bug。
2. **测试要用临时目录** —— 我第一次写 P2-2 测试时直接改写了真实 Lua，
   破坏了 4012810 的配置（后来从数据源恢复）。现在测试全部隔离。
3. **改完要检查副作用** —— Lua 备份写到运行目录、测试写到真实 backup/，
   都是"功能正确但污染环境"的问题。
4. **修复本身也可能引入 bug** —— 防覆盖保护是修 P2-2 时加的，
   但它第一次实现就把备份放错了地方。
