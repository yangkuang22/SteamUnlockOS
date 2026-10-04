# Windows 取证指南：找出 SteamUnlock 的密钥来源

## 我们要回答的问题

```
SteamUnlock 能下未授权的游戏 → 密钥从哪来？
  ① 是 Valve 发的？    → 工具目录里不会有密钥库
  ② 是工具自带的？     → 工具目录里会有数据库/配置文件
  ③ 是实时从网上拉的？ → 会有缓存文件
```

**找出答案只需要看几个目录。**

---

## 准备：打开命令提示符

1. 按 **Win + R**
2. 输入 `cmd`
3. 回车（会出现黑窗口）

**接下来每条命令：复制 → 粘贴到黑窗口 → 回车 → 把输出复制给我。**

> 提示：在黑窗口里**右键就是粘贴**（不需要 Ctrl+V）

---

## 第 1 步：找 SteamUnlock 的安装位置

```
where /r C:\ SteamUnlock*.exe
```

**这一条可能跑 1-5 分钟**（要扫全盘），耐心等。

如果太慢，按 `Ctrl+C` 中断，改用这个（更快）：
```
dir /s /b C:\Users\%USERNAME%\Downloads\*SteamUnlock* 2>nul
dir /s /b D:\*SteamUnlock* 2>nul
dir /s /b E:\*SteamUnlock* 2>nul
dir /s /b F:\*SteamUnlock* 2>nul
```

**把找到的路径告诉我。**

---

## 第 2 步：看 SteamUnlock 自己的目录里有什么

把上面找到的路径替换进去（假设是 `F:\SteamUnlock`）：

```
dir /s /b "F:\SteamUnlock"
```

**我要看**：有没有 `.db`、`.json`、`.dat`、`.key`、`.bin` 之类的文件
（这些可能就是密钥库）

---

## 第 3 步：看 Steam 的 stplug-in 目录（工具的工作目录）

```
dir /a "C:\Program Files (x86)\Steam\config\stplug-in"
```
如果你 Steam 装在 F 盘：
```
dir /a "F:\steam\config\stplug-in"
```

**我要看**：除了 `.o` 文件，还有没有别的文件（比如缓存、数据库）

---

## 第 4 步：找工具可能在 AppData 里藏的缓存

```
dir /s /b "%LOCALAPPDATA%\*steamunlock*" 2>nul
dir /s /b "%APPDATA%\*steamunlock*" 2>nul
dir /s /b "%LOCALAPPDATA%\*caigamer*" 2>nul
dir /s /b "%APPDATA%\*caigamer*" 2>nul
dir /s /b "%TEMP%\*steamunlock*" 2>nul
```

（这几条很快，没找到是正常的）

---

## 第 5 步：最关键的一步 —— 看 Steam 里有哪些工具放的文件

```
dir /a "C:\Program Files (x86)\Steam\config"
```
（或 `dir /a "F:\steam\config"`）

**重点看**：有没有修改日期**和你用工具入库的时间一致**的文件。

---

## 第 6 步：在 Steam 目录里全局搜"密钥库"特征文件

```
dir /s /b "C:\Program Files (x86)\Steam\*.db" 2>nul
dir /s /b "C:\Program Files (x86)\Steam\config\*.json" 2>nul
dir /s /b "C:\Program Files (x86)\Steam\config\depotcache\*" 2>nul | findstr /i "key"
```

---

## 第 7 步（最有价值）：抓 Steam 内存里的密钥

**这一步能直接解决问题**，但需要一个小工具。

### 7.1 先确认紫色晶石在 Windows 上能玩
（你说能玩，确认一下）

### 7.2 下载 Cheat Engine
https://cheatengine.org/ → 下载安装（安装时**注意取消捆绑的广告软件**）

### 7.3 让我告诉你搜什么

先做完第 1-6 步，把结果发我。我会根据你找到的路径，
告诉你**具体搜哪个值**（可能是那 96 字节，也可能是别的）。

---

## 最省事的做法（如果你想跳过）

**只做第 2 步和第 3 步**，把输出贴给我。

这两步能回答最核心的问题：
- 工具目录里有数据库 → **可能 B**（自带密钥库）
- 什么都没有 → **可能 A 或 C**（Valve 发的 / 实时拉的）
