#!/bin/bash
# ============================================================
# 测试：让构造的票据发给 Valve（而不是被拦截）
#
# 假设：Valve 用 off-by-four 漏洞解析票据 → 认为你有许可 → 发真密钥
#
# 使用: bash scripts/test-ticket-to-valve.sh on|off|status
# ============================================================
set -e
CFG="$HOME/.config/SLSsteam/config.toml"
BAK="$HOME/steam-toolkit/backup/known-good/config.toml"
LOG="$HOME/.Steam Toolkit-launcher.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

case "${1:-status}" in
  on)
    # 让票据发给 Valve
    if grep -q "^BlockTicketRequests = true" "$CFG" 2>/dev/null; then
        cp "$CFG" "$HOME/steam-toolkit/backup/config.toml.before-ticket-test"
        sed -i 's/^BlockTicketRequests = true/BlockTicketRequests = false/' "$CFG"
        log "✓ 已改为【票据发给 Valve】(BlockTicketRequests = false)"
    else
        log "（已经是 false 或没这行）"
    fi
    ;;
  off)
    # 恢复拦截（安全模式）
    if [ -f "$HOME/steam-toolkit/backup/config.toml.before-ticket-test" ]; then
        cp "$HOME/steam-toolkit/backup/config.toml.before-ticket-test" "$CFG"
        log "✓ 已恢复【拦截票据】(BlockTicketRequests = true)"
    else
        sed -i 's/^BlockTicketRequests = false/BlockTicketRequests = true/' "$CFG" 2>/dev/null || \
            echo "BlockTicketRequests = true" >> "$CFG"
        log "✓ 已设为拦截"
    fi
    ;;
  status)
    echo "当前配置:"
    grep -E "BlockTicketRequests|PlayNotOwnedGames|PackageInjection" "$CFG" 2>/dev/null || echo "  （读不到）"
    ;;
  *)
    echo "用法: $0 on|off|status"
    exit 1
    ;;
esac

if [ "${1}" != "status" ]; then
    echo
    echo "下一步: 重启 Steam"
    echo "  ~/.local/share/SLSsteam/path/steam"
    echo
    echo "然后试安装一个小游戏（别再拿紫色晶石试了）"
    echo "看日志: grep -E 'Dropped raw AppOwnershipTicket|Loaded local' ~/.SLSsteam.log"
fi
