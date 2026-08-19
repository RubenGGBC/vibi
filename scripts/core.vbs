' Arranca el core de Vibi sin ventana de consola.
'
' Mismo motivo que agente-nodo.vbs: una tarea programada que lance el .cmd
' directamente deja una ventana negra abierta toda la sesion. El 0 del Run la
' oculta y el False no espera, que es lo que quieres de un proceso que se queda
' vivo indefinidamente.
Dim shell, carpeta
Set shell = CreateObject("WScript.Shell")
carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
shell.Run """" & carpeta & "core.cmd""", 0, False
