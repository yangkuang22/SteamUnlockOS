#!/bin/bash
# ============================================================
# Steam Toolkit 一键安装（SteamOS / Arch 系 Linux）
#
# 用法:
#   本地:   bash install.sh
#   远程:   bash <(curl -fsSL https://raw.githubusercontent.com/yangkuang22/steam-toolkit/main/install.sh)
#
# 它做的事（9 步）:
#   1. 检查环境（python3 / Steam / 架构）
#   2. 获取代码
#   3. 安装 SLSsteam-Plus（.so）—— 已有就跳过，没有则询问是否编译
#   4. 安装启动器（加固版 + 无注入安全网）
#   5. ★ 配置 3 个启动入口（桌面图标 / 开机自启 / PATH）
#   6. ★ 安装前端（Web UI）启动入口
#   7. ★ 安装自动更新检查（systemd timer）
#   8. 健康检查
#   9. 打印用法
#
# 设计原则: 每一步失败都不中断（最多警告），保证尽量装完
# ============================================================

REPO_URL="${SUOS_REPO:-https://github.com/yangkuang22/steam-toolkit}"
INSTALL_DIR="${SUOS_DIR:-$HOME/steam-toolkit}"
SLSDIR="$HOME/.local/share/SLSsteam"
STEAM_DIR="$HOME/.local/share/Steam"

ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠ $*"; }
err()  { echo "  ✗ $*"; }

echo "=============================================="
echo " Steam Toolkit 安装"
echo "=============================================="
echo

# ── 1. 环境检查 ───────────────────────────────────────────────
echo "[1/9] 检查环境..."
PY=$(command -v python3 || true)
if [ -z "$PY" ]; then err "需要 python3"; exit 1; fi
ok "python3: $($PY --version 2>&1)"
[ "$(uname -m)" = "x86_64" ] && ok "架构: x86_64" || warn "架构 $(uname -m)，32 位注入可能不适用"
if [ -d "$STEAM_DIR" ]; then ok "Steam: $STEAM_DIR"; else warn "没找到 $STEAM_DIR（继续，注入可能无效）"; fi
echo

# ── 2. 获取代码 ───────────────────────────────────────────────
echo "[2/9] 获取代码到 $INSTALL_DIR ..."
if [ -d "$INSTALL_DIR/.git" ]; then
    (cd "$INSTALL_DIR" && git pull --ff-only) 2>/dev/null && ok "已更新" || warn "更新失败（用现有代码继续）"
elif [ -d "$INSTALL_DIR" ]; then
    ok "目录已存在（不是 git 仓库，直接用）"
else
    if git clone "$REPO_URL" "$INSTALL_DIR" 2>/dev/null; then
        ok "已克隆"
    else
        err "克隆失败。请手动下载仓库到 $INSTALL_DIR 后重跑"
        exit 1
    fi
fi
cd "$INSTALL_DIR" || exit 1
echo

# ── 3. SLSsteam-Plus（.so）───────────────────────────────────
echo "[3/9] 检查 SLSsteam-Plus..."
if [ -s "$SLSDIR/SLSsteam.so" ] && [ -s "$SLSDIR/library-inject.so" ]; then
    ok "已安装 (SLSsteam.so $(stat -c%s "$SLSDIR/SLSsteam.so") 字节)"
elif [ -s "$INSTALL_DIR/prebuilt/SLSsteam.so" ] && [ -s "$INSTALL_DIR/prebuilt/library-inject.so" ]; then
    # 项目自带预编译库 —— 直接装（新用户最省事）
    mkdir -p "$SLSDIR"
    cp "$INSTALL_DIR/prebuilt/SLSsteam.so" "$SLSDIR/SLSsteam.so"
    cp "$INSTALL_DIR/prebuilt/library-inject.so" "$SLSDIR/library-inject.so"
    chmod 644 "$SLSDIR"/*.so
    ok "已从 prebuilt/ 安装（SLSsteam.so $(stat -c%s "$SLSDIR/SLSsteam.so") 字节）"
else
    warn "未安装，且项目里没有 prebuilt/ —— 这是【必需】的注入库"
    echo
    echo "  三种获取方式："
    echo "    A. 自动编译（推荐，约 5-10 分钟，会下载 162 MB 工具链）"
    echo "       bash scripts/build-slsteam-plus.sh"
    echo "    B. 用你已有的 .so"
    echo "       bash scripts/install-slsteam-plus.sh <SLSsteam.so> <library-inject.so>"
    echo "    C. 从上游下载后自己打补丁（注意：不打补丁会有特征码失配）"
    echo "       https://github.com/Hintay/SLSsteam-Plus/releases"
    echo
    if [ -t 0 ]; then
        read -r -p "  现在自动编译吗？(y/N) " ans
        case "$ans" in
            [yY]*) bash scripts/build-slsteam-plus.sh || warn "编译失败，稍后可重跑"
                   ;;
            *)     warn "跳过。装完后请先补上这一步，否则功能不生效" ;;
        esac
    else
        warn "非交互模式，跳过。请手动运行: bash scripts/build-slsteam-plus.sh"
    fi
fi
echo

# ── 4. 启动器 ─────────────────────────────────────────────────
echo "[4/9] 安装启动器..."
mkdir -p "$SLSDIR/path" "$HOME/.local/bin"
if [ -f scripts/launcher.sh ]; then
    # 部署时把实际安装目录写进启动器（日志写到 $INSTALL_DIR/logs/）
    sed "s|__SUOS_DIR__|$INSTALL_DIR|g" scripts/launcher.sh > "$SLSDIR/path/steam" && chmod +x "$SLSDIR/path/steam"
    sed "s|__SUOS_DIR__|$INSTALL_DIR|g" scripts/launcher.sh > "$HOME/.local/bin/steam" && chmod +x "$HOME/.local/bin/steam"
    ok "加固启动器（含 4 道回退 + 崩溃计数保护）"
else
    warn "找不到 scripts/launcher.sh"
fi
printf '#!/bin/sh\n# 无注入启动（出问题时的安全网）\nexec /usr/bin/steam "$@"\n' > "$HOME/.local/bin/steam-noinject"
chmod +x "$HOME/.local/bin/steam-noinject"
ok "安全网: ~/.local/bin/steam-noinject"
echo

# ── 5. ★ 三个启动入口（关键！缺了游戏模式就不生效）───────────
echo "[5/9] 配置启动入口（3 个）..."
WRAPPER="$SLSDIR/path/steam"

# ① 桌面图标（注意: 系统那个是符号链接，必须断开）
mkdir -p "$HOME/Desktop"
DESK="$HOME/Desktop/steam.desktop"
if [ -L "$DESK" ]; then
    rm -f "$DESK"
    ok "① 桌面图标: 断开了指向系统文件的符号链接"
fi
cat > "$DESK" <<DESKTOP_EOF
[Desktop Entry]
Name=Steam
Comment=Steam（通过 Steam Toolkit 注入启动）
Exec=$WRAPPER %U
Icon=steam
Terminal=false
Type=Application
Categories=Network;FileTransfer;Game;
MimeType=x-scheme-handler/steam;x-scheme-handler/steamlink;
StartupWMClass=Steam
DESKTOP_EOF
chmod +x "$DESK"
ok "① 桌面图标: $DESK"

# ② 应用菜单
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/steam.desktop" <<APPS_EOF
[Desktop Entry]
Name=Steam
Comment=Steam（通过 Steam Toolkit 注入启动）
Exec=$WRAPPER %U
Icon=steam
Terminal=false
Type=Application
Categories=Network;FileTransfer;Game;
MimeType=x-scheme-handler/steam;x-scheme-handler/steamlink;
StartupWMClass=Steam
APPS_EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
ok "② 应用菜单: ~/.local/share/applications/steam.desktop"

# ③ 开机自启（覆盖 /etc/xdg/autostart/steam.desktop）
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/steam.desktop" <<AUTO_EOF
[Desktop Entry]
Type=Application
Name=Steam
Comment=Steam（Steam Toolkit 注入启动）
Exec=$WRAPPER -silent %U
Icon=steam
Terminal=false
Categories=Network;FileTransfer;Game;
X-KDE-RunOnDiscreteGpu=true
X-GNOME-Autostart-enabled=true
AUTO_EOF
ok "③ 开机自启: ~/.config/autostart/steam.desktop"

# ④ PATH（让游戏快捷方式的 `steam steam://rungameid/N` 走包装器）
mkdir -p "$HOME/.config/environment.d"
cat > "$HOME/.config/environment.d/50-steamunlock.conf" <<ENV_EOF
# Steam Toolkit: 让 \`steam\` 命令走注入包装器
PATH=\${HOME}/.local/bin:\${PATH}
ENV_EOF
grep -q 'local/bin' "$HOME/.bashrc" 2>/dev/null || \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
ok "④ PATH: ~/.config/environment.d/50-steamunlock.conf"
echo

# ── 6. 前端（Web UI）─────────────────────────────────────────
echo "[6/9] 安装前端（Web UI）..."
chmod +x start-webui.sh 2>/dev/null || true
if [ -f start-webui.sh ]; then
    cat > "$HOME/.local/share/applications/steam-unlock-gui.desktop" <<GUI_EOF
[Desktop Entry]
Name=Steam 库管理（Steam Toolkit）
Comment=Steam 配置与库管理工具（支持批量处理 DLC）
Exec=$INSTALL_DIR/start-webui.sh
Icon=steam
Terminal=false
Type=Application
Categories=Game;Utility;
Path=$INSTALL_DIR
GUI_EOF
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    ok "前端入口已装（应用菜单里搜「Steam 库管理」）"
    ok "也可命令行启动: $INSTALL_DIR/start-webui.sh"
else
    warn "找不到 start-webui.sh"
fi
echo

# ── 7. 自动更新检查（systemd timer）──────────────────────────
echo "[7/9] 安装自动更新检查..."
chmod +x scripts/autocheck-update.sh 2>/dev/null || true
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/steamunlock-updatecheck.service" <<SVC_EOF
[Unit]
Description=Steam Toolkit 游戏更新检查
After=default.target

[Service]
Type=oneshot
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/scripts/autocheck-update.sh
StandardOutput=journal
StandardError=journal
SVC_EOF
cat > "$HOME/.config/systemd/user/steamunlock-updatecheck.timer" <<TMR_EOF
[Unit]
Description=Steam Toolkit 游戏更新检查定时器

[Timer]
OnStartupSec=2min
OnUnitActiveSec=12h
Persistent=true

[Install]
WantedBy=timers.target
TMR_EOF
systemctl --user daemon-reload 2>/dev/null || true
if systemctl --user enable --now steamunlock-updatecheck.timer 2>/dev/null; then
    ok "定时器已启用（登录后 2 分钟 + 每 12 小时）"
else
    warn "启用失败（可手动: systemctl --user enable --now steamunlock-updatecheck.timer）"
fi
echo

# ── 8. 健康检查 ───────────────────────────────────────────────
echo "[8/9] 健康检查..."
if [ -f scripts/healthcheck.sh ]; then
    bash scripts/healthcheck.sh || warn "有项目未通过，见上面输出"
else
    warn "找不到 healthcheck.sh"
fi
echo

# ── 9. 完成 ───────────────────────────────────────────────────
echo "[9/9] 完成！"
echo "=============================================="
echo
echo "用法:"
echo "  1. 打开前端:         $INSTALL_DIR/start-webui.sh"
echo "  2. 输入游戏 AppID → 搜索 → 入库（勾选 DLC 则一并入库）"
echo "  3. 重启 Steam（点桌面图标，或 $WRAPPER）"
echo "  4. 到库里点安装即可下载"
echo
echo "常用命令:"
echo "  bash scripts/healthcheck.sh                    # 体检"
echo "  python3 -m suos.cli update --all               # 检查所有游戏更新"
echo "  python3 -m suos.cli update <appid> --apply      # 应用更新"
echo "  bash scripts/check-after-steam-update.sh        # Steam 升级后体检"
echo "  bash scripts/fix-injection.sh status            # 查注入是否生效"
echo "  ~/.local/bin/steam-noinject                     # 出问题时的安全网"
echo
echo "文档:"
echo "  docs/使用手册.md              完整用法 + 原理"
echo "  docs/项目全貌与维护指南.md     架构 + 维护"
echo "  docs/恢复手册.md              出事了怎么救"
echo "  docs/BUG清单-待分析.md        已知问题"
echo
