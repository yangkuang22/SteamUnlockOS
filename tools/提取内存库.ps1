# ============================================================
# SteamUnlock 内存数据库提取
#
# 原理: SteamUnlock 必须把 applist.json 解密到内存才能用
#       → 内存里一定有【明文】的 depot 密钥库
#
# 用法:
#   1. 以管理员身份运行 PowerShell
#   2. 先打开 SteamUnlock 让它完全启动（加载完数据）
#   3. 粘贴本脚本运行
#   4. 把生成的 txt 发给我
# ============================================================
$ErrorActionPreference = 'Continue'
Add-Type -TypeDefinition @"
using System;using System.Runtime.InteropServices;
public static class MM{
  [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a,bool b,int c);
  [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr h,IntPtr a,byte[] b,int s,out IntPtr r);
  [DllImport("kernel32.dll")] public static extern IntPtr VirtualQueryEx(IntPtr h,IntPtr a,out MBI m,int l);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct MBI{public IntPtr B;public IntPtr A;public uint AP;public IntPtr S;public uint St;public uint P;public uint T;}
}
"@

# 找 SteamUnlock 进程（可能是主 exe 或子进程）
Write-Host "=== 查找 SteamUnlock 进程 ===" -Fore Cyan
$procs = Get-Process | Where-Object { $_.ProcessName -match 'SteamUnlock|steamunlock' }
if ($procs.Count -eq 0) {
    Write-Host "没找到 SteamUnlock！" -Fore Red
    Write-Host "请先启动 SteamUnlock（让它加载完数据），再运行本脚本"
    Write-Host ""
    Write-Host "当前所有进程（前 30 个，供参考）:" -Fore Yellow
    Get-Process | Select-Object -First 30 | ForEach-Object { Write-Host "  $($_.Id)`t$($_.ProcessName)" }
    Read-Host "按回车退出"
    return
}
$out = New-Object System.Collections.ArrayList
foreach ($proc in $procs) {
    $id = $proc.Id
    Write-Host "  进程: $($proc.ProcessName) PID=$id 内存=$([math]::Round($proc.WorkingSet64/1MB,1))MB"

    $h = [MM]::OpenProcess(0x0410, $false, $id)
    if ($h -eq [IntPtr]::Zero) { $h = [MM]::OpenProcess(0x0010, $false, $id) }
    if ($h -eq [IntPtr]::Zero) { Write-Host "    打不开（需要管理员权限）" -Fore Red; continue }

    $mbi = New-Object MM+MBI
    $msz = [System.Runtime.InteropServices.Marshal]::SizeOf([type][MM+MBI])
    $addr = [IntPtr]::Zero
    $region = 0; $total = 0; $kept = 0
    # 收集可读内存
    $chunks = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt 500000; $i++) {
        $q = [MM]::VirtualQueryEx($h, $addr, [ref]$mbi, $msz)
        if ($q -eq [IntPtr]::Zero) { break }
        $sz = [int64]$mbi.S
        if ($sz -le 0) { break }
        $pr = $mbi.P
        $readable = ($mbi.St -eq 0x1000) -and (($pr -band 0x100) -eq 0) -and
                    (($pr -band 2) -or ($pr -band 4) -or ($pr -band 0x20) -or ($pr -band 0x40) -or ($pr -band 0x80))
        if ($readable -and $sz -le 134217728) {
            $region++
            $buf = New-Object byte[] $sz
            $rd = [IntPtr]::Zero
            if ([MM]::ReadProcessMemory($h, $mbi.B, $buf, [int]$sz, [ref]$rd)) {
                $total += $sz
                # 快速过滤：如果不是全零/全FF，就保留
                $nonzero = 0
                for ($k = 0; $k -lt [Math]::Min($sz, 4096); $k++) { if ($buf[$k] -ne 0 -and $buf[$k] -ne 255) { $nonzero++ } }
                if ($nonzero -gt 32) {
                    [void]$chunks.Add(@{addr=$mbi.B; data=$buf; size=$sz})
                    $kept++
                }
            }
        }
        $nx = [int64]$mbi.B + $sz
        if ($nx -le [int64]$mbi.B) { break }
        $addr = [IntPtr]$nx
        if ($nx -gt 0x7FFFFFFF0000) { break }
    }
    [MM]::CloseHandle($h) | Out-Null
    Write-Host "    扫描: $region 区域 / $([math]::Round($total/1MB,1)) MB / 保留 $kept 块" -Fore Green

    # 搜索关键内容：已知的 depot 密钥（紫色晶石）
    Write-Host "    搜索已知密钥..." -Fore Cyan
    $knownHex = "afd931e4303e3aa3d3d4c8d1d4f432b4095db76644eaf715d0703900ad65c562"
    $knownBytes = New-Object byte[] 32
    for ($k = 0; $k -lt 32; $k++) { $knownBytes[$k] = [Convert]::ToByte($knownHex.Substring($k*2, 2), 16) }
    $found = 0
    foreach ($c in $chunks) {
        $d = $c.data
        for ($k = 0; $k -le $d.Length - 32; $k++) {
            if ($d[$k] -eq $knownBytes[0] -and $d[$k+1] -eq $knownBytes[1] -and $d[$k+31] -eq $knownBytes[31]) {
                $match = $true
                for ($m = 2; $m -lt 31; $m++) { if ($d[$k+$m] -ne $knownBytes[$m]) { $match = $false; break } }
                if ($match) {
                    $found++
                    [void]$out.Add("=== 找到已知密钥(紫色晶石) @ $($c.addr) + $k ===")
                    $st = [Math]::Max(0, $k - 200); $en = [Math]::Min($d.Length - 1, $k + 500)
                    $seg = $d[$st..$en]
                    [void]$out.Add("HEX: " + (($seg | ForEach-Object { $_.ToString('x2') }) -join ''))
                    [void]$out.Add("TXT: " + (($seg | ForEach-Object { if ($_ -ge 32 -and $_ -lt 127) { [char]$_ } else { '.' } }) -join ''))
                    [void]$out.Add("")
                }
            }
        }
    }
    Write-Host "    找到 $found 处已知密钥" -Fore Yellow

    # 搜索 JSON 结构（明文数据库的特征）
    Write-Host "    搜索 JSON/depot 结构..." -Fore Cyan
    $jsonHits = 0
    foreach ($c in $chunks) {
        $s = [System.Text.Encoding]::UTF8.GetString($c.data)
        foreach ($pat in @('"Keys"', '"depots"', 'DecryptionKey', '"applist"', '"app_id"', '"depot_id"')) {
            $x = $s.IndexOf($pat)
            if ($x -ge 0 -and $jsonHits -lt 40) {
                $jsonHits++
                $st = [Math]::Max(0, $x - 150); $len = [Math]::Min(600, $s.Length - $st)
                [void]$out.Add("=== JSON特征 [$pat] @ $($c.addr) ===")
                [void]$out.Add($s.Substring($st, $len) -replace '[^\x20-\x7e]', '.')
                [void]$out.Add("")
            }
        }
    }
    Write-Host "    JSON 特征命中 $jsonHits 处" -Fore Yellow
    Write-Host ""
}

$path = Join-Path ([Environment]::GetFolderPath("Desktop")) "steamunlock内存.txt"
$out | Out-File $path -Encoding UTF8
Write-Host "=========================================="
Write-Host "已保存: $path" -Fore Green
Write-Host "大小: $([math]::Round((Get-Item $path).Length/1KB,1)) KB"
Write-Host "把它发给我" -Fore Cyan
Write-Host "=========================================="
Read-Host "按回车退出"
