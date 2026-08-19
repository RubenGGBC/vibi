' Arranca Vibi sin dejar ventanas negras por el escritorio.
'
' Mismo motivo que core.vbs y agente-nodo.vbs: el 0 del Run la oculta y el
' False no espera, que es lo que quieres de algo que se queda vivo.
Dim shell, carpeta
Set shell = CreateObject("WScript.Shell")
carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
shell.Run """" & carpeta & "vibi.cmd""", 0, False
