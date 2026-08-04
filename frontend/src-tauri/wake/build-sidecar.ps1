$ErrorActionPreference = "Stop"

python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias" }

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "morgana-wake",
    # Vosk carga libvosk.dll y sus runtimes buscando físicamente dentro de la
    # carpeta del paquete. Sin esta recogida explícita PyInstaller los aplana y
    # el ejecutable falla antes incluso de procesar --help.
    "--collect-binaries", "vosk",
    "--distpath", (Join-Path $PSScriptRoot "dist"),
    "--workpath", (Join-Path $PSScriptRoot "build"),
    "--specpath", $PSScriptRoot,
    (Join-Path $PSScriptRoot "wake_listener.py")
)
python @pyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el sidecar" }

Write-Host "Sidecar creado en $(Join-Path $PSScriptRoot 'dist\morgana-wake.exe')"
