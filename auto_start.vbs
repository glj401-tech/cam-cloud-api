' ============================================================================
'  Windows 开机自启脚本 (VBScript 无窗口运行)
'  使用方法: Win+R → shell:startup → 将此文件快捷方式放入启动文件夹
'  或者创建快捷方式放到: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
' ============================================================================
Set WshShell = CreateObject("WScript.Shell")
' 静默启动 bat (0=隐藏窗口, False=不等待完成)
WshShell.Run "D:\CAM_CLOUD_API\start_service.bat", 0, False
Set WshShell = Nothing
