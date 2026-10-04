# ============================================================
# SteamUnlock 解密 Hook（Frida 脚本）
#
# 用途: 拦截 SteamUnlock 调用 Windows 加密 API 的瞬间，
#       拿到【AES 密钥】+【解密后的明文】
#
# 用法（Windows）:
#   1. 安装 Python 和 Frida:  pip install frida-tools
#   2. 启动 SteamUnlock（让它完全加载）
#   3. 运行:  python hook解密.py
#   4. 把输出发我
# ============================================================
import frida, sys, time, os, json

SCRIPT = r"""
// Hook Windows CryptoAPI 的解密函数
var cryptDecrypt = Module.findExportByName("advapi32.dll", "CryptDecrypt");
var bcryptDecrypt = Module.findExportByName("bcrypt.dll", "BCryptDecrypt");
var cryptImportKey = Module.findExportByName("advapi32.dll", "CryptImportKey");

console.log("[*] CryptDecrypt = " + cryptDecrypt);
console.log("[*] BCryptDecrypt = " + bcryptDecrypt);
console.log("[*] CryptImportKey = " + cryptImportKey);

// 记录导入的密钥
var keys = {};

if (cryptImportKey) {
    Interceptor.attach(cryptImportKey, {
        onEnter: function (args) {
            // BOOL CryptImportKey(hProv, pbData, dwDataLen, hPubKey, dwFlags, phKey)
            var pbData = args[1];
            var dwDataLen = args[2].toInt32();
            if (dwDataLen > 0 && dwDataLen <= 64) {
                var hex = "";
                try {
                    var bytes = Memory.readByteArray(pbData, dwDataLen);
                    var arr = new Uint8Array(bytes);
                    for (var i = 0; i < arr.length; i++) {
                        hex += ("0" + arr[i].toString(16)).slice(-2);
                    }
                } catch (e) { hex = "ERROR"; }
                console.log("\n★★★ KEY IMPORT (" + dwDataLen + " bytes): " + hex);
                this.keyHex = hex;
            }
        },
        onLeave: function (retval) {
            if (this.keyHex) {
                try {
                    var phKey = this.context.esp ? null : null; // 简化
                } catch (e) {}
            }
        }
    });
}

if (cryptDecrypt) {
    Interceptor.attach(cryptDecrypt, {
        onEnter: function (args) {
            // BOOL CryptDecrypt(hKey, hHash, Final, dwFlags, pbData, pdwDataLen)
            this.pbData = args[4];
            this.pdwDataLen = args[5];
            this.len = args[5].toInt32() ? Memory.readU32(args[5]) : 0;
            this.hKey = args[0];
            console.log("\n=== CryptDecrypt called, len=" + this.len);
        },
        onLeave: function (retval) {
            var ok = retval.toInt32();
            console.log("    result=" + ok);
            if (ok && this.pbData && this.len > 0 && this.len < 16777216) {
                try {
                    var bytes = Memory.readByteArray(this.pbData, this.len);
                    var arr = new Uint8Array(bytes);
                    // 检查是否像 JSON/文本
                    var printable = 0;
                    for (var i = 0; i < Math.min(200, arr.length); i++) {
                        if ((arr[i] >= 32 && arr[i] < 127) || arr[i] === 10 || arr[i] === 13) printable++;
                    }
                    var ratio = printable / Math.min(200, arr.length);
                    console.log("    printable ratio = " + ratio.toFixed(2));
                    if (ratio > 0.85) {
                        var head = "";
                        for (var i = 0; i < Math.min(300, arr.length); i++) {
                            head += String.fromCharCode(arr[i]);
                        }
                        console.log("★★★ 明文头 300 字节:\n" + head);
                        // 保存完整明文
                        var f = new File("C:\\decrypted_" + Date.now() + ".bin", "wb");
                        f.write(bytes);
                        f.close();
                        console.log("★★★ 已保存完整明文到 C:\\decrypted_" + Date.now() + ".bin (" + this.len + " 字节)");
                    }
                } catch (e) { console.log("    read error: " + e); }
            }
        }
    });
}

if (bcryptDecrypt) {
    Interceptor.attach(bcryptDecrypt, {
        onEnter: function (args) {
            // NTSTATUS BCryptDecrypt(hKey, pbInput, cbInput, pPaddingInfo, pbIV, cbIV, pbOutput, cbOutput, pcbResult, dwFlags)
            this.pbOutput = args[6];
            this.pcbResult = args[8];
            this.cbInput = args[2].toInt32();
            this.pbIV = args[4];
            this.cbIV = args[5].toInt32();
            var ivHex = "";
            if (this.pbIV && this.cbIV > 0 && this.cbIV <= 32) {
                try {
                    var b = Memory.readByteArray(this.pbIV, this.cbIV);
                    var a = new Uint8Array(b);
                    for (var i = 0; i < a.length; i++) ivHex += ("0" + a[i].toString(16)).slice(-2);
                } catch (e) {}
            }
            console.log("\n=== BCryptDecrypt: cbInput=" + this.cbInput + " IV=" + ivHex);
        },
        onLeave: function (retval) {
            console.log("    status=0x" + retval.toInt32().toString(16));
            if (retval.toInt32() === 0 && this.pcbResult && this.pbOutput) {
                try {
                    var outLen = Memory.readU32(this.pcbResult);
                    if (outLen > 0 && outLen < 16777216) {
                        var bytes = Memory.readByteArray(this.pbOutput, outLen);
                        var arr = new Uint8Array(bytes);
                        var printable = 0;
                        for (var i = 0; i < Math.min(200, arr.length); i++) {
                            if ((arr[i] >= 32 && arr[i] < 127) || arr[i] === 10 || arr[i] === 13) printable++;
                        }
                        var ratio = printable / Math.min(200, arr.length);
                        console.log("    输出 " + outLen + " 字节, printable=" + ratio.toFixed(2));
                        if (ratio > 0.85) {
                            var head = "";
                            for (var i = 0; i < Math.min(300, arr.length); i++) head += String.fromCharCode(arr[i]);
                            console.log("★★★ 明文头:\n" + head);
                            var fn = "C:\\bcrypt_dec_" + Date.now() + ".bin";
                            var f = new File(fn, "wb");
                            f.write(bytes);
                            f.close();
                            console.log("★★★ 已保存到 " + fn);
                        }
                    }
                } catch (e) { console.log("    err: " + e); }
            }
        }
    });
}

console.log("\n[*] Hook 已安装，等待解密调用...");
console.log("[*] 触发方法: 让 SteamUnlock 刷新游戏列表/下载游戏");
"""

def main():
    print("=== SteamUnlock 解密 Hook ===")
    # 查找进程
    device = frida.get_local_device()
    target = None
    for p in device.enumerate_processes():
        if "steamunlock" in p.name.lower():
            target = p
            break
    if not target:
        print("找不到 SteamUnlock 进程！")
        print("当前进程列表（前 20）:")
        for p in device.enumerate_processes()[:20]:
            print(f"  {p.pid} {p.name}")
        return
    print(f"找到: {target.name} (PID {target.pid})")
    session = frida.attach(target.pid)
    script = session.create_script(SCRIPT)
    script.on("message", lambda m, d: print(m.get("payload", m)))
    script.load()
    print("\n[*] Hook 运行中。请让 SteamUnlock 刷新/下载游戏。")
    print("[*] 按 Ctrl+C 退出\n")
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    session.detach()

if __name__ == "__main__":
    main()
