Option Explicit

Dim shell, fso, root, startupFolder, shortcutPath, shortcut, wscriptPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
startupFolder = shell.SpecialFolders("Startup")
shortcutPath = startupFolder & "\DreiTrack.lnk"
wscriptPath = shell.ExpandEnvironmentStrings("%WINDIR%") & "\System32\wscript.exe"

Set shortcut = shell.CreateShortcut(shortcutPath)
shortcut.TargetPath = wscriptPath
shortcut.Arguments = Chr(34) & root & "\DreiTrack.vbs" & Chr(34) & " /background"
shortcut.WorkingDirectory = root
shortcut.Description = "Start DreiTrack automatically when this Windows user signs in"
shortcut.Save

MsgBox "DreiTrack will now start automatically when you sign in to Windows.", vbInformation, "DreiTrack"
