' Nalox launcher — runs the supervisor silently (no window).
' The Startup shortcut points here.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = base & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"   ' fallback: system pythonw
End If
sh.CurrentDirectory = base
sh.Run """" & pythonw & """ """ & base & "\supervisor.py""", 0, False
