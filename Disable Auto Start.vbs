Option Explicit

Dim shell, fso, shortcutPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

shortcutPath = shell.SpecialFolders("Startup") & "\DreiTrack.lnk"

If fso.FileExists(shortcutPath) Then
    fso.DeleteFile shortcutPath, True
    MsgBox "DreiTrack automatic startup has been disabled.", vbInformation, "DreiTrack"
Else
    MsgBox "DreiTrack automatic startup is already disabled.", vbInformation, "DreiTrack"
End If
