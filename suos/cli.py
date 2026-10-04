"""Steam Toolkit 命令行入口。

用法（在 ~/steam-toolkit 下）：
    python3 -m suos.cli status                    看环境
    python3 -m suos.cli plan 379720               只演算不落盘：这个游戏缺什么
    python3 -m suos.cli install 379720            入库（写 SLSsteam 配置 + 放清单）
    python3 -m suos.cli install 379720 --apply    真正落盘
    python3 -m suos.cli list                      列出本地已备好清单、可入库的游戏
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import steam, vdf
from .slsconfig import SLSConfig, find_slssteam

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup"
MANIFEST_DIR = Path(__file__).resolve().parent.parent / "manifests"


@dataclass
class DepotPlan:
    depotid: int
    gid: int
    manifest_name: str
    key: str | None
    from_cache: bool


@dataclass
class InstallPlan:
    appid: int
    title: str
    depots: list[DepotPlan]
    already_owned: bool

    @property
    def missing_keys(self) -> list[int]:
        return [d.depotid for d in self.depots if not d.key]


def _depot_index(paths: steam.SteamPaths) -> dict[int, tuple[int, str]]:
    """{depotid: (gid, 文件名)}，每个 depot 取 gid 最大的清单。

    来源：Steam 的 depotcache + 我们的 manifests/ 裸清单目录（后者优先补缺）。
    """
    index = steam.best_manifests([MANIFEST_DIR], paths=paths)
    if MANIFEST_DIR.is_dir():
        for entry in MANIFEST_DIR.iterdir():
            if entry.suffix != ".manifest":
                continue
            parts = entry.stem.split("_")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                depotid, gid = int(parts[0]), int(parts[1])
                if depotid not in index or index[depotid][0] < gid:
                    index[depotid] = (gid, entry.name)
    return index


def _manifests_for_app(paths: steam.SteamPaths, appid: int) -> list[tuple[int, int, str]]:
    """找出某 appid 的 appmanifest_<appid>.acf 里列出的 depot 及各 depotid 的清单。

    ACF 里的 InstalledDepots 段给出该游戏用到的 depotid；清单 GID 从 depotcache 找。
    ACF 不存在时返回空列表（需要服务端提供清单，暂未接入）。
    """
    acf = steam.acf_path(paths, appid)
    if acf is None:
        return []
    from . import vdf

    try:
        data = vdf.load(acf)
    except Exception:
        return []
    node = data.get("AppState", data)
    depots = node.get("InstalledDepots") or {}
    out: list[tuple[int, int, str]] = []
    index = _depot_index(paths)
    for depotid_str in depots:
        if not str(depotid_str).isdigit():
            continue
        depotid = int(depotid_str)
        if depotid in index:
            gid, name = index[depotid]
            out.append((depotid, gid, name))
    return out


def build_plan(paths: steam.SteamPaths, appid: int) -> InstallPlan:
    keys = steam.load_depot_keys(paths)
    owned = SLSConfig().load().owned()
    installed = steam.installed_appids(paths)

    entries = _manifests_for_app(paths, appid)
    index = _depot_index(paths)

    depots: list[DepotPlan] = []
    if entries:
        for depotid, gid, name in entries:
            depots.append(
                DepotPlan(
                    depotid=depotid,
                    gid=gid,
                    manifest_name=name,
                    key=keys.get(depotid),
                    from_cache=(paths.depotcache / name).is_file(),
                )
            )
    else:
        # 没有 ACF（未安装）：退回到"depotcache 里按 depotid 前缀归属该 appid 的清单"
        for depotid, (gid, name) in sorted(index.items()):
            if steam.app_of_depot(depotid) == appid:
                depots.append(
                    DepotPlan(
                        depotid=depotid,
                        gid=gid,
                        manifest_name=name,
                        key=keys.get(depotid),
                        from_cache=(paths.depotcache / name).is_file(),
                    )
                )

    return InstallPlan(
        appid=appid,
        title=f"appid {appid}",
        depots=depots,
        already_owned=appid in owned or appid in installed,
    )


def cmd_update(paths, args):
    """检查/应用游戏更新"""
    from . import updater
    if getattr(args, "all", False):
        results = updater.check_all(verbose=True)
        need = [r for r in results if r.get("has_update")]
        print(f"\n{len(results)} 个游戏，{len(need)} 个有更新")
        if need and getattr(args, "apply", False):
            for r in need:
                res = updater.apply(r["appid"])
                print(f"  AppID {r['appid']}: {res.get('message')}")
        elif need:
            print("加 --apply 参数实际更新")
        return
    if not getattr(args, "appid", None):
        print("用法: python3 -m suos.cli update <appid> [--apply]")
        print("      python3 -m suos.cli update --all [--apply]")
        return 1
    appid = int(args.appid)
    if getattr(args, "apply", False):
        res = updater.apply(appid, verbose=True)
        print(f"\n{res.get('message')}")
        for s in res.get("steps", []):
            print(f"  {s}")
        if res.get("ok") and res.get("downloaded"):
            print("\n→ 重启 Steam 后自动开始下载")
    else:
        updater.check(appid, verbose=True)


def cmd_status(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    print(paths.describe())
    keys = steam.load_depot_keys(paths)
    print(f"\nconfig.vdf 里的 depot 密钥: {len(keys)} 个")
    manifests = list(paths.depotcache.glob("*.manifest")) if paths.depotcache.is_dir() else []
    print(f"depotcache 里的清单       : {len(manifests)} 个")
    print(f"已安装游戏 (ACF)          : {len(steam.installed_appids(paths))} 个")
    print(f"我们的裸清单目录          : {MANIFEST_DIR} "
          f"({len(list(MANIFEST_DIR.glob('*.manifest'))) if MANIFEST_DIR.is_dir() else 0} 个)")

    cfg = SLSConfig().load()
    print(f"\nSLSsteam 配置             : {cfg.path} ({'存在' if cfg.exists() else '不存在'})")
    print(f"  已声明拥有              : {len(cfg.owned())} 个 appid")
    sls = find_slssteam()
    print(f"SLSsteam 安装             : {'已安装' if sls['installed'] else '未安装'}")
    if sls["installed"]:
        print(f"  SLSsteam.so             : {sls['lib']}")
        print(f"  library-inject.so       : {sls['inject']}")
    else:
        print("  → 运行 python3 -m suos.cli setup-slssteam 安装（需要网络）")
    return 0


def cmd_list(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """列出本地清单能覆盖到的 appid（按 depotid 前缀归组）。"""
    keys = steam.load_depot_keys(paths)
    installed = steam.installed_appids(paths)
    index = _depot_index(paths)
    # 用"已安装游戏的 appid"当候选集合，能显著提高 depotid -> appid 的归组准确率
    candidates = steam.installed_appids(paths)
    by_app: dict[int, list[int]] = {}
    for depotid in index:
        by_app.setdefault(steam.app_of_depot(depotid, candidates), []).append(depotid)
    print(f"{'appid':>9} {'depot':>6} {'有密钥':>7} {'已安装':>7}")
    for appid in sorted(by_app):
        deps = by_app[appid]
        has_key = sum(1 for d in deps if d in keys)
        print(f"{appid:>9} {len(deps):>6} {has_key:>7} {'是' if appid in installed else '否':>7}")
    print(f"\n共 {len(by_app)} 个 appid 可以入库（清单已在本机）")
    return 0


def cmd_plan(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    plan = build_plan(paths, args.appid)
    print(f"目标 appid : {plan.appid}")
    print(f"已拥有     : {'是' if plan.already_owned else '否（将写入 SLSsteam 配置）'}")
    print(f"清单数量   : {len(plan.depots)}")
    if not plan.depots:
        print("\n⚠ 没找到该 appid 的清单。需要先从服务端拉取 .lua + .manifest（阶段 2 未接入）。")
        return 1
    print(f"\n{'depotid':>10} {'manifest gid':>20} {'密钥':>6} {'来源':>10}")
    for d in plan.depots:
        print(f"{d.depotid:>10} {d.gid:>20} {'有' if d.key else '缺':>6} "
              f"{'Steam 缓存' if d.from_cache else '待放置':>10}")
    if plan.missing_keys:
        print(f"\n注意: {len(plan.missing_keys)} 个 depot 没有解密密钥（config.vdf 里没有），"
              f"这些 depot 的文件将无法解密下载。")
    return 0


def cmd_install(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    plan = build_plan(paths, args.appid)
    if not plan.depots:
        print(f"✗ appid {args.appid} 在本地找不到清单，无法入库。")
        return 1

    print(f"计划入库 appid {args.appid}：{len(plan.depots)} 个 depot")
    if not args.apply:
        print("\n（这是预演，未写入任何文件。加 --apply 真正执行）")
        return cmd_plan(paths, args)

    cfg = SLSConfig().load()
    backup = cfg.backup(BACKUP_DIR)
    if backup:
        print(f"✓ 已备份原配置 -> {backup}")

    # 1) 声明拥有权
    cfg.add_app(args.appid, additional=True)
    # 2) 清单覆盖 + 密钥
    copied = 0
    for d in plan.depots:
        cfg.set_manifest(d.depotid, d.gid)
        if d.key:
            cfg.set_cdkey(d.depotid, d.key)
        src = paths.depotcache / d.manifest_name
        if not src.is_file() and (MANIFEST_DIR / d.manifest_name).is_file():
            paths.depotcache.mkdir(parents=True, exist_ok=True)
            shutil.copy2(MANIFEST_DIR / d.manifest_name, paths.depotcache / d.manifest_name)
            copied += 1
    written = cfg.save()
    print(f"✓ 已写入 {written}")
    print(f"  声明 AppIds/AdditionalApps: {args.appid}")
    print(f"  ManifestIds 条目          : {len(plan.depots)}")
    print(f"  CDKeys 条目               : {sum(1 for d in plan.depots if d.key)}")
    if copied:
        print(f"  从裸清单目录补进 depotcache: {copied} 个")
    print("\n下一步：用带注入的方式重启 Steam（SLSsteam），然后库里就会出现该游戏。")
    return 0


def cmd_setup_slssteam(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent.parent
    print("SLSsteam 安装/更新脚本：")
    print(f"    bash {root}/scripts/setup-slssteam.sh")
    print("带注入重启 Steam：")
    print(f"    bash {root}/scripts/restart-steam-injected.sh")
    return 0


def cmd_fetch(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """从作者服务端拉一个 appid 的入库数据（仅下载+解析，不落盘）。"""
    from . import server_api

    cache = Path(__file__).resolve().parent.parent / "cache"
    try:
        payload = server_api.install_plan(args.appid, cache_dir=cache)
    except Exception as exc:  # 网络/协议问题都给用户看得懂的提示
        print(f"✗ 拉取失败: {exc}")
        return 1
    print(payload.describe())
    if payload.depots:
        print(f"\n{'depotid':>9} {'gid':>20} {'大小':>10} {'平台':>8} {'密钥':>4}")
        for d in payload.depots:
            size = (
                f"{d.size / 1024**3:.2f}GB"
                if d.size > 10**9
                else f"{d.size / 1024**2:.1f}MB"
            )
            print(f"{d.depotid:>9} {d.gid or 0:>20} {size:>10} "
                  f"{d.oslist or '-':>8} {'有' if d.key else '缺':>4}")
    print(f"\n原始响应已缓存到 {cache}/GetAppinfo_{args.appid}.bin")
    print("要真正入库请跑：python3 -m suos.cli install <appid> --from-server --apply")
    return 0



def cmd_list_branches(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """列出某个游戏可选的版本分支（来自 SteamUnlock 服务端 appinfo）"""
    import ast
    from . import rc4, server_api, appinfo_parse
    from pathlib import Path as _P
    appid = args.appid
    server_api.install_plan(appid, cache_dir=_P("cache"))
    f = _P("cache/GetAppinfo_%d.bin" % appid)
    if not f.is_file():
        print("✗ 拿不到 appinfo")
        return 1
    j = ast.literal_eval(rc4.rc4(rc4.RC4_KEY, f.read_bytes()).decode("utf-8", "replace"))
    dep = appinfo_parse.parse_depots(j.get("appinfo", ""))
    if not dep:
        print("✗ 解析不到 depot")
        return 1
    # 汇总所有分支及其大小
    allb = {}
    for depid, info in dep.items():
        for b, m in info.get("manifests", {}).items():
            allb.setdefault(b, []).append((depid, m["gid"], m.get("size", 0)))
    print(f"== appid {appid} 的可选版本（共 {len(allb)} 个）==")
    for b in list(allb)[:40]:
        tot = sum(x[2] for x in allb[b])
        print(f"  {b:<28} {len(allb[b])} 个 depot, {tot/1048576:.0f} MB")
    print()
    print("用法: python3 -m suos.cli prepare <appid> --branch <分支名>")
    return 0


def cmd_mh3(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """★ 从 ManifestHub3 一键准备（数据最全：lua+密钥+清单）"""
    from . import installer2
    r = installer2.install(args.appid, dry_run=getattr(args, "dry_run", False))
    if not r.get("ok"):
        print(f"✗ 失败: {r.get('reason')}")
        print("  如果提示 no_branch，说明这个游戏社区还没收录（通常是新游戏）")
        return 1
    if not r.get("dry_run"):
        print()
        print("== 下一步 ==")
        print("  1. 重启 Steam（必须！密钥只在启动时读）")
        print("     ~/.local/share/SLSsteam/path/steam")
        print("  2. 库里搜索游戏 → 点「安装」→ 自动下载")
    return 0


def cmd_mh3_check(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """检查某个 appid 在 ManifestHub3 有没有数据"""
    from . import manifesthub3 as m3
    if m3.branch_exists(args.appid):
        files = m3.list_files(args.appid)
        print(f"★ {args.appid} 有数据（{len(files)} 个文件）")
        for f in files:
            print(f"    {f['name']:<44} {f.get('size',0):>9} B")
        return 0
    print(f"✗ {args.appid} 没有数据")
    return 1


def cmd_prepare(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """★ 一键准备：SteamUnlock 服务端 + 社区密钥库 → 写配置，然后重启 Steam 即可下载

    这是实测有效的流程（紫色晶石 625960 完整下载 853MB 验证通过）
    """
    from . import installer
    appid = args.appid
    print(f"== 为 appid {appid} 准备下载环境 ==")
    try:
        r = installer.prepare(appid, branch=getattr(args, "branch", "public"))
    except Exception as e:
        print(f"✗ 失败: {e}")
        return 1
    print()
    print("== 完成！下一步 ==")
    print("  1. 重启 Steam（关键！密钥只在启动时读取）")
    print(f"     ~/.local/share/SLSsteam/path/steam")
    print("  2. 在库里搜索游戏，点「安装」")
    print("  3. 会自动开始下载（不再显示'内容加密'）")
    if r["missing"]:
        print()
        print(f"  注意: 有 {len(r['missing'])} 个 depot 无密钥，已从清单覆盖中跳过：")
        print(f"        {r['missing']}")
        print("        （在 SteamUnlock 里这些通常是 40 字节的空 depot，会以 0 字节形式占位）")
    return 0

def cmd_install_server(paths: steam.SteamPaths, args: argparse.Namespace) -> int:
    """从服务端取数据并**完整**入库：配置 + 许可证密钥 + 清单文件 + ACF。

    这是"能下载"的完整四件套（顺序即依赖关系）：
      1. SLSsteam 配置：AppIds（所有权放行）+ ManifestIds（版本覆写）+ CDKeys
      2. Steam 的 config.vdf：写入 depot **解密密钥**（Steam 靠这个解下载内容）
      3. depotcache/：写入 **.manifest 文件本体**（Steam 靠这个建 depot 挂载点）
      4. steamapps/：ACF（保留 Steam 自己写的那份，不动它）
    """
    from . import manifests, server_api

    cache = Path(__file__).resolve().parent.parent / "cache"
    try:
        payload = server_api.install_plan(args.appid, cache_dir=cache)
    except Exception as exc:
        print(f"✗ 拉取服务端数据失败: {exc}")
        return 1

    print(payload.describe())
    if not args.apply:
        print("\n（预演，未落盘。加 --apply 真正执行）")
        return 0

    # ---------- 1) SLSsteam 配置 ----------
    cfg = SLSConfig().load()
    backup = cfg.backup(BACKUP_DIR)
    if backup:
        print(f"✓ 备份 SLSsteam 配置 -> {backup}")
    cfg.add_app(payload.appid, additional=False)   # AppIds：能下载；AdditionalApps 会破坏下载
    for dlc in payload.dlcs:
        cfg.add_app(dlc, additional=False)
    for d in payload.depots:
        if d.gid:
            cfg.set_manifest(d.depotid, d.gid)
        if d.key:
            cfg.set_cdkey(d.depotid, d.key)
    if payload.app_token:
        cfg.set_token(payload.appid, payload.app_token)
    cfg.data["SafeMode"] = "yes"
    print(f"✓ SLSsteam 配置: {cfg.save()}")

    # ---------- 2) Steam config.vdf 里的 depot 解密密钥 ----------
    cfg_vdf = paths.config_vdf
    if cfg_vdf.is_file():
        import shutil as _sh
        _sh.copy2(cfg_vdf, BACKUP_DIR / f"config.vdf.{__import__('time').strftime('%Y%m%d-%H%M%S')}.bak")
        tree = vdf.load(cfg_vdf)
        depots_node = (
            tree.get("InstallConfigStore", {})
            .get("Software", {})
            .get("Valve", {})
            .get("Steam", {})
            .setdefault("depots", {})
        )
        wrote = 0
        for d in payload.depots:
            if not d.key:
                continue
            node = depots_node.setdefault(str(d.depotid), {})
            if node.get("DecryptionKey") != d.key:
                node["DecryptionKey"] = d.key
                wrote += 1
        if wrote:
            cfg_vdf.write_text(vdf.dumps(tree) + "\n", encoding="utf-8")
            print(f"✓ config.vdf: 写入 {wrote} 个 depot 解密密钥")
        else:
            print("✓ config.vdf: 密钥已是最新")

    # ---------- 3) 清单文件本体 ----------
    placed = failed = 0
    for d in payload.depots:
        if not d.gid:
            continue
        local = paths.depotcache / f"{d.depotid}_{d.gid}.manifest"
        if local.is_file():
            print(f"  清单已在本地: {local.name}")
            placed += 1
            continue
        print(f"  获取清单 depot {d.depotid} gid {d.gid} …")
        res = manifests.fetch_manifest(payload.appid, d.depotid, d.gid)
        if res is None:
            failed += 1
            continue
        manifests.install_manifest(paths.depotcache, d.depotid, d.gid, res.data)
        print(f"    ✓ {res.provider}: {res.size} 字节")
        placed += 1

    print(f"\n清单: 就位 {placed} 个" + (f"，失败 {failed} 个" if failed else ""))
    print(f"密钥: {sum(1 for d in payload.depots if d.key)} 个")
    print(f"所有权: appid {payload.appid}" + (f" + {len(payload.dlcs)} 个 DLC" if payload.dlcs else ""))
    print("\n下一步：bash scripts/restart-steam-injected.sh，然后在 Steam 里点安装")
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suos", description="Steam Toolkit —— SteamUnlock 的 SteamOS 数据管道")
    parser.add_argument("--steam-root", help="手动指定 Steam 根目录")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="显示环境状态")
    p_status.set_defaults(func=cmd_status)

    p_list = sub.add_parser("list", help="列出本地有清单的游戏")
    p_list.set_defaults(func=cmd_list)

    p_plan = sub.add_parser("plan", help="演算某个 appid 的入库计划（不落盘）")
    p_plan.add_argument("appid", type=int)
    p_plan.set_defaults(func=cmd_plan)

    p_install = sub.add_parser("install", help="入库某个 appid")
    p_install.add_argument("appid", type=int)
    p_install.add_argument("--apply", action="store_true", help="真正写入（默认只预演）")
    p_install.set_defaults(func=cmd_install)

    p_setup = sub.add_parser("setup-slssteam", help="安装 SLSsteam 的说明")
    p_setup.set_defaults(func=cmd_setup_slssteam)

    p_fetch = sub.add_parser("fetch", help="从服务端拉取某个 appid 的入库数据（不落盘）")
    p_fetch.add_argument("appid", type=int)
    p_fetch.set_defaults(func=cmd_fetch)

    p_prep = sub.add_parser("prepare", help="★ 一键准备下载环境（写密钥+清单配置，然后重启 Steam）")
    p_prep.add_argument("appid", type=int, help="Steam AppID")
    p_prep.add_argument("--branch", default="public", help="版本分支（默认 public=最新；可用 list-branches 查看）")
    p_prep.set_defaults(func=cmd_prepare)

    p_mh3 = sub.add_parser("install-mh3", help="★ 从 ManifestHub3 一键准备（推荐，数据最全）")
    p_mh3.add_argument("appid", type=int)
    p_mh3.add_argument("--dry-run", action="store_true", help="只看不写")
    p_mh3.set_defaults(func=cmd_mh3)

    p_mh3c = sub.add_parser("check-mh3", help="检查 ManifestHub3 有没有该游戏的数据")
    p_mh3c.add_argument("appid", type=int)
    p_mh3c.set_defaults(func=cmd_mh3_check)

    p_br = sub.add_parser("list-branches", help="列出游戏的可选版本（来自 SteamUnlock appinfo）")
    p_br.add_argument("appid", type=int, help="Steam AppID")
    p_br.set_defaults(func=cmd_list_branches)

    p = sub.add_parser("update", help="检查/应用游戏更新")

    p.add_argument("appid", nargs="?", default=None, help="AppID（留空配合 --all）")

    p.add_argument("--all", action="store_true", help="检查所有已入库游戏")

    p.add_argument("--apply", action="store_true", help="实际更新（下新清单+改Lua）")

    p.set_defaults(func=cmd_update)

    p_isrv = sub.add_parser("install-server", help="从服务端取数据并入库（推荐）")
    p_isrv.add_argument("appid", type=int)
    p_isrv.add_argument("--apply", action="store_true", help="真正写入（默认只预演）")
    p_isrv.set_defaults(func=cmd_install_server)

    args = parser.parse_args(argv)
    try:
        paths = steam.find_steam(args.steam_root)
    except steam.SteamNotFound as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    return args.func(paths, args)


if __name__ == "__main__":
    raise SystemExit(main())
