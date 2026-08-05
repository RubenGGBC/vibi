' Arranca el agente de nodo sin ventana de consola.
'
' Una tarea programada que lance el .cmd directamente deja una ventana negra
' abierta toda la sesion. Este envoltorio la lanza oculta (el 0 del Run) y no
' espera a que termine (el False), que es justo lo que queremos de un proceso
' que se queda vivo indefinidamente.
Dim shell, carpeta
Set shell = CreateObject("WScript.Shell")
carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
shell.Run """" & carpeta & "agente-nodo.cmd""", 0, False
