<#
.SYNOPSIS
Abre —o cierra— el puerto de depuración de una aplicación WebView2, para que
Vibi pueda hablarle por dentro sin ponerle la ventana delante.

.DESCRIPTION
Casi todo el escritorio moderno es Chromium con un marco alrededor, y todos
hablan el protocolo de las herramientas de desarrollo. El problema es que ese
puerto solo se abre al arrancar el proceso, y las aplicaciones de la Microsoft
Store no admiten argumentos al lanzarse.

La vía que sí funciona no pasa por la línea de comandos: el runtime de WebView2
lee sus argumentos extra del registro. Con eso, la aplicación arranca
escuchando la abra quien la abra, también la persona desde su menú de inicio.

Se pide un puerto **efímero** (`=0`) a propósito. Uno fijo es adivinable por
cualquiera que pruebe los de siempre; este no se sabe hasta leer el
`DevToolsActivePort` que la propia aplicación escribe en su perfil, que es lo
que hace `web_apps.descubrir_webview2()`.

Requiere elevación: la rama `Policies` está protegida por ACL aunque sea HKCU.

.PARAMETER Ejecutable
El nombre del ejecutable tal y como lo declara el runtime, que no siempre es el
obvio: WhatsApp es `WhatsApp.Root.exe`. Sin parámetros, el script lo descubre
solo entre las aplicaciones WebView2 que estén corriendo.

.PARAMETER Quitar
Deshace el cambio: borra la entrada de esa aplicación.

.EXAMPLE
.\puerto_de_depuracion.ps1
Lista las aplicaciones WebView2 vivas y cuáles tienen ya el puerto puesto.

.EXAMPLE
.\puerto_de_depuracion.ps1 -Ejecutable WhatsApp.Root.exe

.EXAMPLE
.\puerto_de_depuracion.ps1 -Ejecutable WhatsApp.Root.exe -Quitar
#>
[CmdletBinding()]
param(
    [string] $Ejecutable,
    [switch] $Quitar
)

$ErrorActionPreference = 'Stop'
$clave = 'HKCU:\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments'

function Get-AppsWebView2Vivas {
    # El propio runtime declara a quién sirve en `--webview-exe-name`. Es la
    # única fuente fiable del nombre: el proceso que se ve en el administrador
    # de tareas puede llamarse de otra forma.
    Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($_.CommandLine -match '--webview-exe-name=([^\s"]+)') { $Matches[1] }
        } | Sort-Object -Unique
}

function Get-Puestas {
    if (-not (Test-Path $clave)) { return @{} }
    $tabla = @{}
    $item = Get-ItemProperty -Path $clave
    foreach ($p in $item.PSObject.Properties) {
        if ($p.Name -notlike 'PS*') { $tabla[$p.Name] = $p.Value }
    }
    return $tabla
}

# --- Sin argumentos: informar y salir, sin tocar nada ---
if (-not $Ejecutable) {
    $puestas = Get-Puestas
    Write-Host "`nAplicaciones WebView2 corriendo ahora:" -ForegroundColor Cyan
    $vivas = Get-AppsWebView2Vivas
    if (-not $vivas) {
        Write-Host "  (ninguna)"
    }
    foreach ($v in $vivas) {
        $estado = if ($puestas.ContainsKey($v)) { "puerto puesto" } else { "sin puerto" }
        Write-Host ("  {0,-30} {1}" -f $v, $estado)
    }
    Write-Host "`nEntradas en el registro:" -ForegroundColor Cyan
    if ($puestas.Count -eq 0) { Write-Host "  (ninguna)" }
    foreach ($k in $puestas.Keys) { Write-Host ("  {0,-30} {1}" -f $k, $puestas[$k]) }
    Write-Host "`nPara abrir una:  .\puerto_de_depuracion.ps1 -Ejecutable <nombre.exe>`n"
    return
}

# --- Elevación: la rama Policies no se deja escribir sin ella ---
$soyAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $soyAdmin) {
    Write-Host "Hace falta elevación para escribir en Policies. Aceptando UAC..." -ForegroundColor Yellow
    $argumentos = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath,
        '-Ejecutable', $Ejecutable
    )
    if ($Quitar) { $argumentos += '-Quitar' }
    Start-Process powershell -Verb RunAs -Wait -ArgumentList $argumentos
    return
}

if ($Quitar) {
    if (Test-Path $clave) {
        Remove-ItemProperty -Path $clave -Name $Ejecutable -ErrorAction SilentlyContinue
    }
    Write-Host "Quitado el puerto de $Ejecutable. Reinicia la aplicación." -ForegroundColor Green
    return
}

New-Item -Path $clave -Force | Out-Null
New-ItemProperty -Path $clave -Name $Ejecutable `
    -Value '--remote-debugging-port=0' -PropertyType String -Force | Out-Null

$leido = (Get-ItemProperty -Path $clave).$Ejecutable
Write-Host "Puesto: $Ejecutable = $leido" -ForegroundColor Green
Write-Host "Cierra y vuelve a abrir la aplicación para que tome efecto."
Write-Host "El puerto es efímero: lo publica ella en su DevToolsActivePort."
