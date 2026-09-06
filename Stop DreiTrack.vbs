Option Explicit

Dim shell, fso, root, pythonw, stopper, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
stopper = root & "\stop_dreitrack.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "DreiTrack is not set up yet.", vbExclamation, "DreiTrack"
    WScript.Quit 1
End If

command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & stopper & Chr(34)
shell.Run command, 0, True
MsgBox "DreiTrack has been stopped.", vbInformation, "DreiTrack"
