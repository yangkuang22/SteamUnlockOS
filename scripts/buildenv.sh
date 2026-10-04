#!/bin/sh
# SLSsteam-Plus 构建环境（SteamOS）
export PATH=/home/deck/buildtools/wrappers:$PATH
export LD_LIBRARY_PATH=/home/deck/buildtools/usr/lib:$LD_LIBRARY_PATH
# 32 位 glibc 头 + OpenSSL 头（都在这个目录里）
export C_INCLUDE_PATH=/home/deck/buildtools/usr/include
export CPLUS_INCLUDE_PATH=/home/deck/buildtools/usr/include
export PKG_CONFIG_PATH=/home/deck/buildtools/usr/lib/pkgconfig
