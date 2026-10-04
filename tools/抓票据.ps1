# ============================================================
# 票据提取器（在 Windows 上运行）
#
# 作用: 从 Steam 的注册表里提取【你真拥有】游戏的 AppOwnershipTicket
#       这些"源票据"可以用来伪造其他游戏的票据
#
# 原理: Steam 把票据存在 HKCU\Software\Valve\Steam\Apps\<appid>\AppTicket
#       如果 SLSsteam-Plus 有了源票据，就能用 off-by-four 漏洞伪造出其他游戏的
#
# 用法: 管理员 PowerShell，直接粘贴运行
# ============================================================
$ErrorActionPreference = 'Continue'
Write-Host "=== Steam 票据提取器 ===" -Fore Cyan
Write-Host ""

# 1. 先看用户拥有哪些游戏（从 config.vdf 读 AppIds）
Write-Host "[1/4] 查找 Steam 安装路径..." -Fore Yellow
$steamPath = $null
foreach ($p in @("$env:ProgramFiles(x86)\Steam", "$env:ProgramFiles\Steam",
                 "C:\Steam", "D:\Steam", "E:\Steam",
                 (Get-ItemProperty -Path "HKCU:\Software\Valve\Steam" -Name SteamPath -EA SilentlyContinue).SteamPath)) {
    if ($p -and (Test-Path (Join-Path $p "steam.exe"))) { $steamPath = $p; break }
}
if (-not $steamPath) { Write-Host "  找不到 Steam！" -Fore Red; Read-Host "回车退出"; return }
Write-Host "  Steam: $steamPath"

# 2. 读取你拥有的 appid 列表
Write-Host "[2/4] 读取你拥有的游戏..." -Fore Yellow
$owned = @()
$vdf = Join-Path $steamPath "config\config.vdf"
if (Test-Path $vdf) {
    $txt = Get-Content $vdf -Raw -Encoding UTF8
    # 匹配 "depots" 段里的 "<数字>" { "DecryptionKey" ... }
    $m = [regex]::Matches($txt, '"(\d{3,8})"\s*\{\s*"DecryptionKey"')
    $owned = $m | ForEach-Object { [int]$_.Groups[1].Value } | Sort-Object -Unique
    Write-Host "  config.vdf 里有 $($owned.Count) 个 depot"
}

# 3. 枚举注册表里所有有票据的 appid
Write-Host "[3/4] 扫描注册表票据..." -Fore Yellow
$regBase = "HKCU:\Software\Valve\Steam\Apps"
$withTicket = @()
if (Test-Path $regBase) {
    Get-ChildItem $regBase -EA SilentlyContinue | ForEach-Object {
        $appid = $_.PSChildName
        if ($appid -match '^\d+$') {
            $props = Get-ItemProperty $_.PSPath -EA SilentlyContinue
            foreach ($name in @('AppTicket','ETicket','SteamID')) {
                $val = $props.$name
                if ($val -and $val.Length -gt 0) {
                    $withTicket += [PSCustomObject]@{ AppId = [int]$appid; Kind = $name; Bytes = $val.Length; Path = $_.PSPath }
                }
            }
        }
    }
    Write-Host "  找到 $($withTicket.Count) 个票据条目"
} else {
    Write-Host "  注册表路径不存在（可能 Steam 没运行过或权限不足）" -Fore Red
}

# 4. 导出
Write-Host "[4/4] 导出..." -Fore Yellow
$out = New-Object System.Collections.ArrayList
[void]$out.Add("# Steam 票据导出 - $(Get-Date)")
[void]$out.Add("# 共 $($withTicket.Count) 个票据")
[void]$out.Add("")

$byApp = $withTicket | Group-Object AppId
foreach ($g in $byApp) {
    [void]$out.Add("=== AppId $($g.Name) ===")
    foreach ($t in $g.Group) {
        $props = Get-ItemProperty $t.Path -EA SilentlyContinue
        $hex = ($props.($t.Kind) | ForEach-Object { $_.ToString("x2") }) -join ''
        [void]$out.Add("  $($t.Kind) ($($t.Bytes) 字节): $($hex.Substring(0, [Math]::Min(120, $hex.Length)))...")
        [void]$out.Add("  FULL: $hex")
    }
    [void]$out.Add("")
}

# 也导出完整的，供分析
$dump = @{}
foreach ($g in $byApp) {
    $props = Get-ItemProperty $g.Group[0].Path -EA SilentlyContinue
    $entry = @{}
    foreach ($t in $g.Group) {
        $hex = ($props.($t.Kind) | ForEach-Object { $_.ToString("x2") }) -join ''
        $entry[$t.Kind] = $hex
    }
    $dump[$g.Name] = $entry
}
$dump | ConvertTo-Json -Depth 4 | Out-File (Join-Path ([Environment]::GetFolderPath("Desktop")) "steam票据.json") -Encoding UTF8

$p = Join-Path ([Environment]::GetFolderPath("Desktop")) "steam票据.txt"
$out | Out-File $p -Encoding UTF8
Write-Host ""
Write-Host "=========================================="
Write-Host "已保存:" -Fore Green
Write-Host "  $p"
Write-Host "  $(Join-Path ([Environment]::GetFolderPath('Desktop')) 'steam票据.json')"
Write-Host ""
Write-Host "把你拥有的游戏票据发我（尤其是 appid 7 / 220 / 440 等基础 app）"
Write-Host "它将用于伪造其他游戏的票据" -Fore Cyan
Write-Host "=========================================="
Read-Host "回车退出"
