# Steam Toolkit

在 **SteamOS / Linux** 上管理 Steam 客户端配置与运行时扩展的一套工具。

提供图形前端、配置写入、运行时加载、版本同步、健康检查与崩溃恢复，
并附带一键安装脚本。所有改动都在用户目录内，可随时完整回滚。

## 一键安装

```bash
git clone https://github.com/yangkuang22/steam-toolkit.git ~/steam-toolkit
cd ~/steam-toolkit
bash install.sh
```

> `install.sh` 会：检查环境 → 拉代码 → 装启动器（含 4 道回退保护）→ 装桌面图标 → 跑健康检查

## 🎮 图形界面（推荐）

双击应用菜单里的 **「游戏库管理」**，或者：

```bash
~/steam-toolkit/start-webui.sh
```

输入 AppID → 查询 → 添加 → 重启 Steam → 在库中管理

详见 [前端使用说明](docs/前端使用说明.md)。

## 命令行用法

## 快速开始

```bash
cd ~/steam-toolkit
python3 -m suos.cli install-mh3 <appid>      # 一键准备
~/.local/share/SLSsteam/path/steam           # 重启 Steam
# 然后库里点「安装」
```

## ⚠️ 重要修复

**RequestCode 崩溃**（点安装就崩）已修复 —— Steam 会对同批多个 depot
复用同一个 jobid，导致重复构造响应而崩溃。

细节见 [RequestCode崩溃修复](docs/RequestCode崩溃修复.md)。

## 📖 完整技术文档

**[项目全貌与维护指南](docs/项目全貌与维护指南.md)** —— 942 行完整文档，包含:
- 系统架构与数据流全景
- 核心技术原理（配置键机制 / 清单机制 / 运行时加载 / DLC 处理 / 注入机制）
- 6 个关键问题的根因与解决方案（含崩溃日志证据）
- 完整文件清单与职责
- 环境部署细节（32 位编译环境、补丁内容）
- 常用操作手册 + 故障排查表
- 维护升级指南（Steam 升级/游戏更新/扩充密钥源）
- 已知限制与未完成事项

## ⚠️ 已知 BUG 清单（待分析）

**[BUG清单-待分析.md](docs/BUG清单-待分析.md)** —— 通篇审计结果，8 个问题:

| 编号 | 标题 | 严重度 |
|---|---|---|
| P1-1 | 名字缓存被永久污染，永不自愈 | 🔴 真实 Bug（已复现） |
| P1-2 | 启动器日志会重新堆到根目录 | 🔴 真实 Bug |
| P1-3 | depotcache 堆积 142.7 MB 无用旧清单 | 🔴 资源泄漏 |
| P2-1 | `write_keys_to_config` 静默失败 | 🟡 设计缺陷 |
| P2-2 | 关键步骤失败仍报"添加完成" | 🟡 设计缺陷 |
| P2-3 | `slsconfig.py` 完全失效（死代码） | 🟡 设计缺陷 |
| P2-4 | `install()` 的 O(n²) 文件读写 | 🟡 性能隐患 |
| P3-1 | 测试覆盖严重不足（2/19 模块） | 🟢 工程债 |

**数据安全结论: 不存在数据损坏类 bug。P1-1 是唯一影响用户的真实 bug。**

## 文档

| 文档 | 内容 |
|---|---|
| [使用手册](docs/使用手册.md) | **怎么用**（命令、原理、限制） |
| [恢复手册](docs/恢复手册.md) | **出问题了怎么救**（Steam 更新、回滚） |
| [构建说明](docs/构建说明.md) | 怎么重新编译 SLSsteam-Plus |
| [成功方案](docs/成功方案.md) | 技术方案总结 |
| [manual/](manual/) | 探索阶段的记录（SteamUnlock 分析等） |

## 常用命令

```bash
# 健康检查（出问题先跑这个）
bash scripts/healthcheck.sh

# 检查某游戏有没有数据
python3 -m suos.cli check-mh3 <appid>

# 只看不写
python3 -m suos.cli install-mh3 <appid> --dry-run

# 看可选版本（来自 SteamUnlock 服务端）
python3 -m suos.cli list-branches <appid>

# 安全网：不带注入启动 Steam
~/.local/bin/steam-noinject
```

## 架构

```
数据源                     运行时机制              目标
─────────────────────     ──────────────────     ─────────────
ManifestHub3 (62000+分支)  SLSsteam-Plus          SteamOS 原生 Steam
  ├─ <appid>.lua           ├─ 所有权放行            ├─ 库里显示游戏
  ├─ key.vdf               ├─ 清单版本锁定          ├─ 自下载
  ├─ <appid>.json          └─ 请求码获取            └─ 能玩
  └─ *.manifest
        ↓
  写入 Steam 配置
  ├─ config.vdf（密钥）
  ├─ depotcache/（清单）
  └─ config/lua/（Lua）
```

**核心原理**：Steam 启动时从 `config.vdf` 预加载 depot 密钥，
所以把密钥写进去即可，**不需要 hook 注入密钥**。

## 项目结构

```
SteamUnlockOS/
├── suos/                   核心 Python 模块（3181 行）
│   ├── manifesthub3.py     ★ 数据源（GitHub 分支）
│   ├── installer2.py       ★ 一键安装
│   ├── cli.py              命令行
│   ├── depotkeys.py        备用密钥库
│   ├── manifests.py        备用清单源
│   ├── server_api.py       SteamUnlock 服务端接口
│   ├── appinfo_parse.py    版本解析
│   └── depot.py / vdf.py / rc4.py / steam.py   底层
├── scripts/
│   └── healthcheck.sh      ★ 健康检查
├── tools/                  Windows 内存提取脚本
├── docs/                   文档
├── manual/                 探索阶段记录
└── backup/                 所有备份
```

## ⚠️ 一个必知的坑

**无密钥的小 depot 会阻塞整个下载**——某些游戏在 Valve 的 appinfo 里有
几十字节的"空 depot"，密钥社区库里没有，Steam 一遇到就取消整个更新。

**工具已自动处理**（写 32 字节全零的占位密钥跳过它）。

细节见 [使用手册](docs/使用手册.md)。

## 状态

- ✅ 端到端验证通过（紫色晶石 853MB 完整下载）
- ✅ 7/7 主流大作数据覆盖
- ✅ 启动器已加固（4 道回退，Steam 一定开得起来）
- ✅ 系统文件未被修改（可完全回滚）
- ⚠️ 新游戏（几个月内）社区未收录，暂时无数据
