#!/bin/sh
# SLSsteam-Plus 构建环境（SteamOS）
#
# 用途: 编译 SLSsteam-Plus（需要 32 位工具链，SteamOS 默认没有）
#   32 位工具链放在  SteamUnlockOS/buildtools/  （不需要 sudo，删了也能重装）
#
# 用法:
#   . ~/steam-toolkit/buildenv.sh
#   cd ~/slsplus-build && make -j$(nproc)
#
# ★ 用绝对路径而不是 $(dirname "$0") —— 因为脚本是用 `.` source 的，
#   这时 $0 是 shell 名而不是脚本路径，dirname 会得到错误的目录。

SLSU_ROOT="/home/deck/steam-toolkit"
SLSU_TOOLS="$SLSU_ROOT/buildtools"

export PATH="$SLSU_TOOLS/wrappers:$PATH"
export LD_LIBRARY_PATH="$SLSU_TOOLS/usr/lib:$LD_LIBRARY_PATH"
export C_INCLUDE_PATH="$SLSU_TOOLS/usr/include"
export CPLUS_INCLUDE_PATH="$SLSU_TOOLS/usr/include"
export PKG_CONFIG_PATH="$SLSU_TOOLS/usr/lib/pkgconfig"

# 等价的 32 位专属变量（有些 Makefile 只看这些）
export LIBRARY_PATH="$SLSU_TOOLS/usr/lib:$LIBRARY_PATH"
