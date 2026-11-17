[CmdletBinding()]
param(
    [string] $PythonRuntime,
    [ValidateCount(3, 3)] [string[]] $Rbitnet
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf) -or !(Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw 'Préparez la venv Windows avec les étapes du README.'
}

$arguments = '-m akasha_brain.desktop'
if ($Rbitnet) {
    $artifacts = foreach ($file in $Rbitnet) {
        if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Artefact Rbitnet introuvable $file" }
        '"' + (Resolve-Path -LiteralPath $file).Path + '"'
    }
    $arguments += ' --rbitnet ' + ($artifacts -join ' ') + ' --rapidocr'
}

$programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
$shortcutPath = Join-Path $programs 'Akasha Brain.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.TargetPath -ne $pythonw) {
    throw "Ce raccourci appartient à une autre installation $shortcutPath"
}

Push-Location -LiteralPath $repo
try {
    & $python -c 'import tkinter, jsonschema'
    if ($LASTEXITCODE -ne 0) { throw 'Tkinter ou les dépendances Python du MVP sont indisponibles.' }
    if ($PythonRuntime) {
        $runtime = (Resolve-Path -LiteralPath $PythonRuntime).Path
        if (!(Test-Path -LiteralPath (Join-Path $runtime 'python.exe') -PathType Leaf)) {
            throw 'Le dossier Python portable doit contenir python.exe.'
        }
        & $python -c 'from pathlib import Path; import sys; from akasha_brain.desktop_settings import remember_runtime; remember_runtime(Path(sys.argv[1]))' $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Le dossier Python portable ne peut pas être enregistré.' }
    }
} finally {
    Pop-Location
}

$shortcut.TargetPath = $pythonw
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $repo
$shortcut.Description = 'Akasha Brain'
$shortcut.Save()
Write-Output $shortcutPath
