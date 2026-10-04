$ErrorActionPreference='SilentlyContinue'
Write-Host "=== SteamUnlock 密钥深度扫描 ===" -Fore Cyan
$p=@(Get-Process steam -ErrorAction SilentlyContinue)
if($p.Count -eq 0){Write-Host "没找到 Steam！" -Fore Red; return}
$pid0=$p[0].Id
Write-Host "Steam PID = $pid0"
Add-Type -TypeDefinition @"
using System;using System.Runtime.InteropServices;
public static class MM{
[DllImport("kernel32.dll")]public static extern IntPtr OpenProcess(uint a,bool b,int c);
[DllImport("kernel32.dll")]public static extern bool ReadProcessMemory(IntPtr h,IntPtr a,byte[] b,int s,out IntPtr r);
[DllImport("kernel32.dll")]public static extern IntPtr VirtualQueryEx(IntPtr h,IntPtr a,out MBI m,int l);
[DllImport("kernel32.dll")]public static extern bool CloseHandle(IntPtr h);
[StructLayout(LayoutKind.Sequential)]public struct MBI{public IntPtr B;public IntPtr A;public uint AP;public IntPtr S;public uint St;public uint P;public uint T;}
}
"@
$h=[MM]::OpenProcess(0x0410,$false,$pid0)
if($h -eq [IntPtr]::Zero){Write-Host "打不开进程，需要管理员权限！" -Fore Red; return}
Write-Host "已打开进程，开始扫描..."
$hexTargets=@(
 'afd931e4303e3aa3d3d4c8d1d4f432b4095db76644eaf715d0703900ad65c562',
 'd293a4ee3b76eecea9a324b1ab6b7e723bbc116560c7d885832db912177b6d09',
 '52aa2ce0848e35566d766d0002966dea8bf8515c2b7efabd02aac0c3231cbfb3',
 '5b23f759f7906de511005533c44475570c839d60ff4b9252dc119f36f2a230a6',
 '625961','4977898995281934257'
)
$binList=@()
foreach($hx in $hexTargets[0..2]){
  $by=New-Object byte[] 32
  for($i=0;$i -lt 32;$i++){$by[$i]=[Convert]::ToByte($hx.Substring($i*2,2),16)}
  $binList+=(,[System.Text.Encoding]::GetEncoding(28591).GetString($by))
}
$mbi=New-Object MM+MBI
$msz=[System.Runtime.InteropServices.Marshal]::SizeOf([type][MM+MBI])
$a=[IntPtr]::Zero;$tot=0;$regions=0
$out=New-Object System.Collections.ArrayList
for($i=0;$i -lt 300000;$i++){
  $q=[MM]::VirtualQueryEx($h,$a,[ref]$mbi,$msz)
  if($q -eq [IntPtr]::Zero){break}
  $sz=[int64]$mbi.S
  if($sz -le 0){break}
  $pr=$mbi.P
  $readable=($mbi.St -eq 0x1000) -and (($pr -band 0x100) -eq 0) -and (($pr -band 2) -or ($pr -band 4) -or ($pr -band 0x20) -or ($pr -band 0x40) -or ($pr -band 0x80))
  if($readable -and $sz -le 268435456){
    $regions++
    $buf=New-Object byte[] $sz
    $rd=[IntPtr]::Zero
    if([MM]::ReadProcessMemory($h,$mbi.B,$buf,[int]$sz,[ref]$rd)){
      $tot+=$sz
      $s=[System.Text.Encoding]::GetEncoding(28591).GetString($buf)
      foreach($b in $binList){
        $x=$s.IndexOf($b)
        if($x -ge 0){
          [void]$out.Add("*** 找到【二进制密钥】@区$($regions) 偏移$x")
          $st=[Math]::Max(0,$x-180);$en=[Math]::Min($buf.Length-1,$x+220)
          $seg=$buf[$st..$en]
          [void]$out.Add("  HEX: "+(($seg|ForEach-Object{$_.ToString('x2')}) -join ''))
          [void]$out.Add("")
        }
      }
      foreach($t in $hexTargets){
        $x=$s.IndexOf($t,[System.StringComparison]::OrdinalIgnoreCase)
        if($x -ge 0){
          $st=[Math]::Max(0,$x-180)
          $ctx=$s.Substring($st,[Math]::Min(420,$s.Length-$st)) -replace '[^\x20-\x7e]','.'
          [void]$out.Add("*** 找到【HEX:$($t.Substring(0,16))...】@区$($regions)")
          [void]$out.Add("  上下文: $ctx")
          [void]$out.Add("")
        }
      }
    }
  }
  $nx=[int64]$mbi.B+$sz
  if($nx -le [int64]$mbi.B){break}
  $a=[IntPtr]$nx
  if($nx -gt 0x7FFFFFFF0000){break}
}
[MM]::CloseHandle($h) | Out-Null
Write-Host ""
$res=$out|Select-Object -Unique
Write-Host "扫描完成: $regions 个区域, $([math]::Round($tot/1MB,1)) MB, 命中 $($res.Count) 条" -Fore Cyan
if($res.Count -eq 0){Write-Host "两种形式都没找到密钥" -Fore Yellow}
else{$res|ForEach-Object{Write-Host $_}}
$o=Join-Path ([Environment]::GetFolderPath("Desktop")) "扫描结果4.txt"
$res|Out-File $o -Encoding UTF8
Write-Host ""
Write-Host "结果已保存: $o" -Fore Green
Write-Host "请把这个文件发给我" -Fore Green
