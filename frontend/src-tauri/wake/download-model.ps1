param(
    [string]$Destination = (Join-Path $PSScriptRoot "models")
)

$ErrorActionPreference = "Stop"
$modelName = "vosk-model-small-es-0.42"
$modelDirectory = Join-Path $Destination $modelName

if (Test-Path -LiteralPath $modelDirectory) {
    Write-Host "El modelo ya está preparado en $modelDirectory"
    exit 0
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$archive = Join-Path ([IO.Path]::GetTempPath()) "$modelName.zip"
$extractDirectory = Join-Path ([IO.Path]::GetTempPath()) "$modelName-extract"

Invoke-WebRequest `
    -Uri "https://alphacephei.com/vosk/models/$modelName.zip" `
    -OutFile $archive

if (Test-Path -LiteralPath $extractDirectory) {
    $resolvedTemp = [IO.Path]::GetFullPath($extractDirectory)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolvedTemp.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "El directorio temporal calculado no está dentro de TEMP"
    }
    Remove-Item -LiteralPath $extractDirectory -Recurse -Force
}

Expand-Archive -LiteralPath $archive -DestinationPath $extractDirectory
Move-Item -LiteralPath (Join-Path $extractDirectory $modelName) -Destination $modelDirectory
Remove-Item -LiteralPath $archive -Force
Remove-Item -LiteralPath $extractDirectory -Recurse -Force
Write-Host "Modelo instalado en $modelDirectory"
