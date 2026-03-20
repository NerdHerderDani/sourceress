Set WshShell = CreateObject("WScript.Shell")
cmd = "powershell -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\Dani\clawd\github-sourcer\scripts\start_sourcer.ps1"""
WshShell.Run cmd, 0, False
