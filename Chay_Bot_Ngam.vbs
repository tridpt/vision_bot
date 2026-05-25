Option Explicit

Dim fso, shell, wmi, processes, process
Dim botScript, botScriptFullPath, isRunning

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

botScript = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "bot_giam_sat.py")
botScriptFullPath = LCase(fso.GetAbsolutePathName(botScript))
isRunning = False

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set processes = wmi.ExecQuery("SELECT ProcessId, Name, CommandLine FROM Win32_Process WHERE Name='pythonw.exe' OR Name='python.exe'")

For Each process In processes
    If Not IsNull(process.CommandLine) Then
        If InStr(1, LCase(process.CommandLine), botScriptFullPath, vbTextCompare) > 0 Then
            isRunning = True
            Exit For
        End If
    End If
Next

If Not isRunning Then
    shell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
    shell.Run "pythonw.exe """ & botScript & """", 0, False
End If
