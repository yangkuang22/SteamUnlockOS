# SLSsteam-Plus RequestCode 崩溃修复

## 症状

在 SteamOS 上点「安装」未授权的游戏时，Steam **随机崩溃**（`/tmp/dumps/crash_*.dmp` + `assert_*.dmp`）。

## 根因（实测定位）

崩溃点在 `src/feats/requestcode.cpp` 的 **构造响应注入** 路径：

```
[15:10:13] RequestCode: drop+fabricate for app=209370 depot=209383 jobid=4086049243978118896
[15:10:15] RequestCode: injected fabricated response code=3081889165680798035 for jobid=4086049243978118896
[15:10:15] RequestCode: drop+fabricate for app=209370 depot=209378 jobid=4086049243978118896  ← 同一个 jobid！
[15:10:15] 💥 崩溃
```

**Steam 会对同一批的多个 depot 复用同一个 `jobid_source`。**

RequestCode 的 `g_pending` 以 jobid 索引，同一个 jobid 出现两次 →
两次注入针对同一 jobid 的 `ServiceMethodResponse` → **Steam 的 RPC 层收到重复响应后崩溃**。

另一个相关场景（也会崩）：

```
[14:39:45] DepotKeyNet: response depot=625960 eresult=15 — ...
[14:39:45] RequestCode: drop+fabricate for app=625960 depot=625960  ← depot == appid
[14:39:48] 💥 崩溃
```

## 修复（两处，都是精准规避，不改变正常行为）

### 1. 同一 jobid 只注入一次

```cpp
// src/feats/requestcode.cpp — nextInjection()
std::unordered_set<uint64_t> g_injectedJobIds;
std::mutex g_injectedJobIdMtx;
...
// 同一 jobid 只注入一次（否则 Steam 收到重复响应会崩溃）
{
    std::lock_guard<std::mutex> lk(g_injectedJobIdMtx);
    if (!g_injectedJobIds.insert(ready.jobId).second)
    {
        g_pLog->debug("RequestCode: jobid=%llu already injected once — skipping duplicate\n", ...);
        return false;
    }
    if (g_injectedJobIds.size() > 4096) g_injectedJobIds.clear();
}
```

### 2. `depotId == appId` 时交给 CM（不接管）

```cpp
// src/feats/requestcode.cpp — onSendFrame()
if (depotId == appId)
{
    g_pLog->debug("RequestCode: skip malformed depot==app (%u) — pass through to CM\n", appId);
    return false;
}
```

**为什么需要 #2**：Steam 会请求「depot == appid」这种畸形请求
（实测 app 625960、1446780 都出现过）。这种请求没有对应的真实 depot，
交给 Valve 处理是安全的（Valve 会正常拒绝）。

## 验证

```
修复后：
  点安装 → RequestCode 正常接管 → 拿到清单请求码 → 下载 ✓
  无崩溃（连续多次测试 0 个 dmp）
```

## 注意：不要全局禁用 RequestCode

**曾经试过**（用 `SLS_REQUEST_CODE` 环境变量全局禁用），**这是错的**：

```
禁用后：
  捆绑了清单的游戏（紫色晶石）→ 不需要请求码 → 能下 ✓
  没捆绑清单的游戏（Analogue）→ 需要请求码 → 拿不到 → "No connection" ✗
    [15:08:46] BYldRequestDepotManifest: Failed to get manifest request code, 'Access Denied'
    [15:08:46] AppID 209370 update canceled : Failed downloading 5 manifests (No connection)
```

**正确做法是精准规避上面两种畸形场景，其余照常接管。**

## 相关补丁

`scripts/slsplus.patch`（应用到 `~/slsplus-build`）：
- `Makefile` — GCC 15 兼容 + 链接标志（SteamOS 构建必需）
- `res/patterns.toml` — 4 条特征码标记 `optional`（Steam 更新后不 abort）
- `src/feats/requestcode.cpp` — 上述崩溃修复
