# AddGame.AddLua 逻辑复原（从 Main.dll 字符串常量区）

> 区域偏移: 0x4b0c000 - 0x4b0e800

> Nuitka 把同一函数的常量连续存放，所以这个顺序 = 代码执行顺序


## 还原出的流程

```python
# 常量顺序（a=py str, u=py bytes, .=属性访问, w=局部变量）
#   ubool | None
#   aget_supported
#   aout
#   asupported_formats
#   uIO[str] | None
#   abool
#   aNone
#   apilinfo
#   wxu<module PIL.features>
#   acodec
#   amodule
#   aimported_module
#   amodule
#   aout
#   asupported_formats
#   wvapy_version_lines
#   apy_version
#   alibjpeg_turbo_version
#   aversion_static
#   wtazlib_ng_version
#   aextensions
#   acodec
#   aversion
#   amodule
#   amodule
#   .PyQt6-preLoad
#   aorigin
#   ahas_location
#   aos
#   w;aenviron
#   uPyQt6-preLoad.py
#   u<module PyQt6-preLoad>
#   .PyQt6.QtCore-postLoad
#   aorigin
#   ahas_location
#   aabsolute_import
#   uPyQt6.QtCore
#   aQCoreApplication
#   aQCoreApplication
#   aos
#   ajoin
#   aenviron
#   uPyQt6\QtCore-postLoad.py
#   u<module PyQt6.QtCore-postLoad>
#   u\Qt6Core.dll
#   aenviron
#   w;aqtcore_dll
#   aadd_dll_directory
#   u\not_existing
#   aorigin
#   ahas_location
#   asubmodule_search_locations
#   u<module PyQt6>
#   aos
#   aqtcore_dll
#   a__mro_entries__
#   u%s argument after ** must be a mapping, not %s
#   u%s got multiple values for keyword argument '%s'
#   u%s argument after * must be an iterable, not %s
#   ukeywords must be strings
#   u'%s' object is not a mapping
#   uEntry point for the Steam game management tool.
#   aQApplication
#   aQApplication
#   asetThemeColor
#   asetThemeColor
#   awindow
#   aWindow
#   aWindow
#   ashow
#   u<module>
#   .__parents_main__-preLoad
#   aorigin
#   ahas_location
#   u--multiprocessing-fork
#   :nnna__nuitka_original_args
#   u__parents_main__-preLoad.py
#   u<module __parents_main__-preLoad>
#   umultiprocessing.spawn
#   a__nuitka_original_args
#   aNone
#   amodules
#   uEntry point for the Steam game management tool.
#   aorigin
#   ahas_location
#   aQApplication
#   aQApplication
#   asetThemeColor
#   asetThemeColor
#   awindow
#   aWindow
#   aWindow
#   a__nuitka_freeze_support
#   u<module __parents_main__>
#   amultiprocessing
#   aOnDLC
#   aapplist
#   aNoUpdate
#   aluacode
#   aappinfo
#   aKey
#   aappkeys
#   aconfig
#   adlcs
#   aAddLua
#   u/config/stplug-in/
#   amakedirs
#   u.o
#   awb
#   awrite
#   arc4
#   aRC4_KEY
#   nnnaappid
#   acommon
#   aDLC
#   uaddappid(
#   aapp_token
#   uaddtoken(
#   aapp_token
#   adepots
#   adlcappid
#   amanifests
#   aDecryptionKey
#   aoslist
#   namacos
#   usetManifestid(
#   uPure business logic for parsing downloaded game data and generating Lua scripts.
#   No Qt dependency 
#    operates on plain dicts and strings.
#   aorigin
#   ahas_location
#   aos
#   aRC4_KEY
#   arc4
#   uParses game metadata (appinfo, keys, config) and generates Lua setup scripts.
#   a__firstlineno__
#   uAddGame.AddLua
#   agetLua
#   uAddGame.getLua
#   aOnDLC
#   aapplist
#   aNoUpdate
#   aluacode
#   aappinfo
#   aappkeys
#   aconfig
#   u<module add_game>
#   adepotid
#   adepotinfo
#   adlcappid
#   amanifests
#   aKey
#   adepot_oslist
#   aappid
#   astplug_path
#   aNoUpdate
#   .aiofiles.base
#   aloop
#   aexecutor
#   uwrap.<locals>.run
#   aloop
#   aget_running_loop
#   arun_in_executor
#   aexecutor
#   a_executor
#   a_ref_loop
#   uWe are our own iterator.
#   uSimulate normal file iteration.
#   a_coro
#   a_obj
#   uAiofilesContextManager.__await__
#   uAiofilesContextManager.__aenter__
#   uAiofilesContextManager.__aexit__
#   aorigin
#   ahas_location
#   aasyncio
#   aget_running_loop
#   ucollections.abc
#   acontextlib
#   aAbstractAsyncContextManager
#   aAbstractAsyncContextManager
#   uaiofiles.base
#   a__firstlineno__
#   a_loop
#   uAsyncBase._loop
#   a_executor
#   a_ref_loop
#   u%s.__prepare__() must return a mapping, not %s
#   aproperty
#   a__orig_bases__
#   aAiofilesContextManager
#   uAn adjusted async context manager for aiofiles.
#   a_coro
#   a_obj
#   a__slots__
#   uAiofilesContextManager.__init__
#   uaiofiles\base.py
#   u<module aiofiles.base>
#   acoro
#   aloop
#   aexecutor
#   aloop
#   aexecutor
#   aloop
#   aexecutor
#   .aiofiles
#   uUtilities for asyncio-friendly file handling.
#   aenviron
#   aNUITKA_PACKAGE_aiofiles
#   u\not_existing
#   aorigin
#   ahas_location
#   asubmodule_search_locations
#   athreadpool
#   aopen
#   astdout
#   astdout_bytes
#   astdout
#   astdout_bytes
#   aopen
#   astdout
#   astdout_bytes
#   uaiofiles\__init__.py
#   u<module aiofiles>
#   .aiofiles.tempfile
#   aAiofilesContextManager
#   a_temporary_file
#   amode
#   aencoding
#   adelete_on_close
#   aloop
#   aexecutor
#   uAsync open a named temporary file
#   amode
#   aencoding
#   aloop
#   aexecutor
#   uAsync open an unnamed temporary file
#   a_spooled_temporary_file
#   amode
#   aencoding
#   aloop
#   aexecutor
#   uAsync open a spooled temporary file
#   aAiofilesContextManagerTempDir
#   a_temporary_directory
#   aloop
#   aexecutor
#   uAsync open a temporary directory
#   uAsync method to open a temporary file with async interface
#   aloop
#   aasyncio
#   aget_running_loop
#   asyncNamedTemporaryFile
#   amode
#   adelete_on_close
#   amode
#   aencoding
#   adelete_on_close
#   asyncTemporaryFile
#   amode
#   aencoding
#   arun_in_executor
#   aexecutor
#   asyncTemporaryFileWrapper
#   aloop
#   aexecutor
#   a_closer
#   uOpen a spooled temporary file with async interface
#   asyncSpooledTemporaryFile
#   amode
#   aencoding
#   aAsyncSpooledTemporaryFile
#   uAsync method to open a temporary directory with async interface
#   asyncTemporaryDirectory
#   aAsyncTemporaryDirectory
#   a_coro
#   a_obj
#   uAiofilesContextManagerTempDir.__aenter__
#   uUnsupported IO type: 
#   uWrap the object with interface based on type of underlying IO
#   ajoin
#   aenviron
#   aNUITKA_PACKAGE_aiofiles
#   u\not_existing
#   aNUITKA_PACKAGE_aiofiles_tempfile
#   u\not_existing
#   aorigin
#   ahas_location
#   asubmodule_search_locations
#   aBufferedRandom
#   aNamedTemporaryFile
#   aNamedTemporaryFile
#   aSpooledTemporaryFile
#   aSpooledTemporaryFile
#   aTemporaryDirectory
#   aTemporaryDirectory
#   aTemporaryFile
#   aTemporaryFile
#   a_TemporaryFileWrapper
#   a_TemporaryFileWrapper
#   aAiofilesContextManager
#   uthreadpool.binary
#   uthreadpool.text
#   aAsyncSpooledTemporaryFile
#   aAsyncTemporaryDirectory
#   aNamedTemporaryFile
#   aTemporaryFile
#   aSpooledTemporaryFile
#   aTemporaryDirectory
#   u%s.__prepare__() must return a mapping, not %s
#   uaiofiles.tempfile
#   uWith returns the directory location, not the object (matching sync lib)
#   a__firstlineno__
#   a_obj
#   a__orig_bases__
#   aloop
#   aexecutor
#   nnuaiofiles\tempfile\__init__.py
#   u<module aiofiles.tempfile>
#   amode
#   aencoding
#   adelete_on_close
#   aloop
#   aexecutor
#   amode
#   aencoding
#   aloop
#   aexecutor
#   abase_io_obj
#   aloop
#   aexecutor
#   amode
#   aencoding
#   aloop
#   aexecutor
#   aloop
#   aexecutor
#   amode
#   aencoding
#   adelete_on_close
#   aloop
#   aexecutor
#   abase_io_obj
#   aloop
#   aexecutor
#   .aiofiles.tempfile.temptypes
#   a_rolled
#   arollover
#   uAsyncSpooledTemporaryFile._check
#   uImplementation to anticipate rollover
#   awrite
#   wsa_loop
#   arun_in_executor
#   a_executor
#   uAsyncSpooledTemporaryFile.write
#   awritelines
#   uAsyncSpooledTemporaryFile.writelines
#   uAsyncTemporaryDirectory.close
#   uAsync wrappers for spooled temp files and temp directory objects
#   aorigin
#   ahas_location
#   uthreadpool.utils
#   acond_delegate_to_executor
#   adelegate_to_executor
#   aproxy_property_directly
#   acond_delegate_to_executor
#   adelegate_to_executor
#   aproxy_property_directly
#   aAsyncSpooledTemporaryFile
#   u%s.__prepare__() must return a mapping, not %s
#   afileno
#   arollover
#   aclose
#   aclosed
#   aencoding
#   amode
#   uaiofiles.tempfile.temptypes
#   uAsync wrapper for SpooledTemporaryFile class
#   a__firstlineno__
#   a__orig_bases__
#   uAsync wrapper for TemporaryDirectory class
#   aAsyncTemporaryDirectory
#   l=uAsyncTemporaryDirectory.__init__
#   a_loop
#   a_executor
#   uaiofiles\tempfile\temptypes.py
#   u<module aiofiles.tempfile.temptypes>
```

## 关键结论

```python
# AddGame.AddLua 的等效伪代码（从常量顺序还原）
def AddLua(self, appid, data):
    stplug = Path(self.SteamPath) / "config/stplug-in/"
    stplug.makedirs(exist_ok=True)
    lua = ""
    lua += f"addappid({appid})\n"
    lua += f'addtoken({appid},"{data["config"]["app_token"]}")\n'
    for depot_id, depot_info in data["appkeys"]["depots"].items():
        # dlcappid / manifests / public / DecryptionKey / oslist(macos/linux) 过滤
        lua += f'addappid({depot_id},1,"{depot_info["manifests"]["public"]["DecryptionKey"]}")\n'
        lua += f'setManifestid({depot_id},"{gid}",{size})\n'
    # ★ 原样 RC4 加密写出，零变换
    (stplug / f"{appid}.o").write_bytes(rc4(lua.encode(), RC4_KEY))
```

## 因此

**.o 里的 48 字节值 = 服务器下发的值 = SteamTools `.o` 格式要求的格式。**

SteamUnlock/SteamTools 客户端**不做任何转换** —— 它只是把服务器给的
`DecryptionKey` 字符串原样拼进 Lua 再 RC4 加密。

→ 48字节 → 32字节 的转换发生在 **SteamTools 的 `Console.dll`**（`.o` 加载器），
  而该文件**不在分发包的 183 个文件里**（已逐一核对）。

## Main.dll 里没有的算法特征

| 特征 | 结果 |
|---|---|
| AES S-box (637c777bf26b6fc5...) | ✗ 不存在 |
| AES-256 Rcon (01020408102040801b36) | ✗ 不存在 |
| 标准 base64 表 | ✓ 存在（库里用） |
| sha256/hmac/zlib | ✓ 存在（库里用） |

→ **不是标准 AES**。转换算法不在 Main.dll 里。