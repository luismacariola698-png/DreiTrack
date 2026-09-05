Option Explicit

Dim shell, fso, root, pythonw, launcher, extra, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
launcher = root & "\launcher.py"
extra = ""

If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "/background" Then
        extra = " --no-browser"
    End If
End If

If Not fso.FileExists(pythonw) Then
    MsgBox "DreiTrack is not set up yet." & vbCrLf & vbCrLf & _
           "Run Setup DreiTrack.bat once, then double-click DreiTrack.vbs again.", _
           vbExclamation, "DreiTrack"
    WScript.Quit 1
End If

command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & launcher & Chr(34) & extra
shell.Run command, 0, False
