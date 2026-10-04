# SteamUnlock 密钥提取 —— 简化版（只用 .NET 内置功能，最稳）
$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  SteamUnlock 密钥提取" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. 找 Steam 进程 ──
$procs = @(Get-Process -Name steam -ErrorAction SilentlyContinue)
if ($procs.Count -eq 0) {
    Write-Host "[错误] 没找到 Steam 进程！" -ForegroundColor Red
    Write-Host "请先用 SteamUnlock 启动 Steam，再运行本脚本。" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}
$proc = $procs[0]
Write-Host "[OK] Steam 进程 PID = $($proc.Id)" -ForegroundColor Green
Write-Host ""

# ── 2. 目标数据 ──
$known = [ordered]@{
    "553851" = "6b40282b237b0cafc4d89014b5ec5f925f9aaa02f2d37f4d956acffdde2e0219"
    "108600" = "fc06c9893d7792ec35292dfc1b216f92d0f9e173df982804f4ab00293e9ab25b"
    "294100" = "44498055cce67eea5d84c5b6bc1bd5ca9e8c988963aea857574277fc217cbad0"
    "228983" = "77c8e812cd79e67e2d376721253ebb07e06b3646f05671c6c9517b27be14734b"
}
$markers = @('{"Keys"', 'depot_encryption_key', 'DecryptionKey', 'applist', 'GetDepotDecryptionKey')

Write-Host "目标：搜索 4 个已知密钥 + 5 个明文标记" -ForegroundColor Yellow
Write-Host ""

# ── 3. 编译 P/Invoke（用 Add-Type 的 -ErrorAction 捕获）──
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class M {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr OpenProcess(uint a, bool b, int c);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool ReadProcessMemory(IntPtr h, IntPtr a, byte[] b, int s, out IntPtr r);
    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")]
    public static extern IntPtr VirtualQueryEx(IntPtr h, IntPtr a, out MEMORY_BASIC_INFORMATION m, int l);
    [StructLayout(LayoutKind.Sequential)]
    public struct MEMORY_BASIC_INFORMATION {
        public IntPtr BaseAddress;
        public IntPtr AllocationBase;
        public uint AllocationProtect;
        public IntPtr RegionSize;
        public uint State;
        public uint Protect;
        public uint Type;
    }
}
"@ -ErrorAction Stop
    Write-Host "[OK] P/Invoke 编译成功" -ForegroundColor Green
} catch {
    Write-Host "[错误] P/Invoke 编译失败: $_" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# ── 4. 打开进程 ──
$PROCESS_VM_READ = 0x0010
$PROCESS_QUERY_INFORMATION = 0x0400
$h = [M]::OpenProcess($PROCESS_VM_READ -bor $PROCESS_QUERY_INFORMATION, $false, $proc.Id)
if ($h -eq [IntPtr]::Zero) {
    Write-Host "[错误] 无法打开进程 (错误码 $([System.Runtime.InteropServices.Marshal]::GetLastWin32Error()))" -ForegroundColor Red
    Write-Host "请用【管理员身份】运行此脚本。" -ForegroundColor Yellow
    Read-Host "按回车退出"
    exit 1
}
Write-Host "[OK] 进程句柄 = $h" -ForegroundColor Green
Write-Host ""

# ── 5. 扫描 ──
Write-Host "开始扫描内存（1-3 分钟，请等待）..." -ForegroundColor Yellow
$results = New-Object System.Collections.ArrayList
$mbi = New-Object M+MEMORY_BASIC_INFORMATION
$mbiSize = [System.Runtime.InteropServices.Marshal]::SizeOf([type][M+MEMORY_BASIC_INFORMATION])
$addr = [IntPtr]::Zero
$total = 0
$regions = 0

for ($i = 0; $i -lt 200000; $i++) {
    $q = [M]::VirtualQueryEx($h, $addr, [ref]$mbi, $mbiSize)
    if ($q -eq [IntPtr]::Zero) { break }
    $size = [int64]$mbi.RegionSize
    if ($size -le 0) { break }
    $regions++

    # 可读性判断
    $isCommit = ($mbi.State -eq 0x1000)
    $p = $mbi.Protect
    $isReadable = ($p -band 0x100) -eq 0 -and (($p -band 0x02) -or ($p -band 0x04) -or ($p -band 0x20) -or ($p -band 0x40) -or ($p -band 0x80))
    $isGuarded = ($p -band 0x100) -ne 0

    if ($isCommit -and $isReadable -and (-not $isGuarded) -and $size -le 268435456) {
        $buf = New-Object byte[] $size
        $read = [IntPtr]::Zero
        $ok = [M]::ReadProcessMemory($h, $mbi.BaseAddress, $buf, [int]$size, [ref]$read)
        if ($ok) {
            $total += $size
            $s = [System.Text.Encoding]::GetEncoding(28591).GetString($buf)

            foreach ($dep in $known.Keys) {
                $kv = $known[$dep]
                $idx = $s.IndexOf($kv)
                if ($idx -ge 0) {
                    [void]$results.Add("★★★ 找到密钥 depot=$dep  地址=$($mbi.BaseAddress)")
                    $st = [Math]::Max(0, $idx - 80)
                    $ctx = $s.Substring($st, [Math]::Min(240, $s.Length - $st))
                    [void]$results.Add("    上下文: " + ($ctx -replace '[^\x20-\x7e]', '.'))
                }
            }
            foreach ($mk in $markers) {
                $idx = $s.IndexOf($mk)
                if ($idx -ge 0) {
                    [void]$results.Add("★★★ 找到标记 '$mk'  地址=$($mbi.BaseAddress)")
                    $ctx = $s.Substring($idx, [Math]::Min(400, $s.Length - $idx))
                    [void]$results.Add("    内容: " + ($ctx -replace '[^\x20-\x7e]', '.'))
                    [void]$results.Add("")
                }
            }
        }
    }
    $next = [int64]$mbi.BaseAddress + $size
    if ($next -le [int64]$mbi.BaseAddress) { break }
    $addr = [IntPtr]$next
    if ($next -gt 0x7FFFFFFF0000) { break }
}

[M]::CloseHandle($h) | Out-Null

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  扫描完成" -ForegroundColor Cyan
Write-Host "  内存区域: $regions 个" -ForegroundColor Cyan
Write-Host "  扫描字节: $([math]::Round($total/1MB,1)) MB" -ForegroundColor Cyan
Write-Host "  命中: $($results.Count) 条" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

if ($results.Count -eq 0) {
    Write-Host "没有命中任何密钥或标记。" -ForegroundColor Yellow
    Write-Host "可能原因：密钥不是明文存放 / 需要管理员权限" -ForegroundColor Yellow
} else {
    $unique = $results | Select-Object -Unique
    $unique | ForEach-Object { Write-Host $_ }
}

$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "密钥扫描结果.txt"
$results | Select-Object -Unique | Out-File -FilePath $out -Encoding UTF8
Write-Host ""
Write-Host "结果已保存: $out" -ForegroundColor Green
Write-Host ""
Read-Host "按回车退出"
