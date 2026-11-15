param(
    [Parameter(Mandatory = $true)][string]$Runtime,
    [Parameter(Mandatory = $true)][ValidateSet('faulty', 'reference')][string]$Case
)

# Exécuter dans la session utilisateur du bac, avec une entrée en lecture seule.
# Le titre et le contenu envoyés sont synthétiques. Le code de sortie indique
# la présence de la fenêtre, le focus vérifié et la présence de la ligne SQLite.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NotesForeground {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    public static uint Owner() {
        uint pid;
        GetWindowThreadProcessId(GetForegroundWindow(), out pid);
        return pid;
    }
}
'@

$work = Join-Path ([IO.Path]::GetTempPath()) ('AkashaNotesFocus-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $work
$app = $null
$phase = 0
try {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'notes_app.py') -Destination $work
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "$Case\notes_store.py") -Destination $work
    $env:PYTHONHOME = $Runtime
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:TCL_LIBRARY = Join-Path $Runtime 'tcl8.6'
    $env:TK_LIBRARY = Join-Path $Runtime 'tk8.6'
    $db = Join-Path $work 'notes.db'
    $appArgs = '"{0}" "{1}"' -f (Join-Path $work 'notes_app.py'), $db
    $app = Start-Process -FilePath (Join-Path $Runtime 'pythonw.exe') -ArgumentList $appArgs -WorkingDirectory $work -WindowStyle Hidden -PassThru
    $phase = 1
    $pidProperty = [System.Windows.Automation.AutomationElement]::ProcessIdProperty
    $owner = [System.Windows.Automation.PropertyCondition]::new($pidProperty, $app.Id)
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $window = $null
    for ($attempt = 0; $attempt -lt 40 -and $null -eq $window; $attempt++) {
        $window = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $owner)
        if ($null -eq $window) { Start-Sleep -Milliseconds 200 }
    }
    if ($null -eq $window) { exit 20 }

    $phase = 2
    function Test-NotesFocus {
        $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
        return ([NotesForeground]::Owner() -eq $app.Id -and
                $null -ne $focused -and $focused.Current.ProcessId -eq $app.Id)
    }
    $uiaActivation = 0
    try {
        $window.SetFocus()
        if (Test-NotesFocus) { $uiaActivation = 16 }
    } catch [System.InvalidOperationException] {}
    if (!(Test-NotesFocus)) {
        $shell = New-Object -ComObject WScript.Shell
        $null = $shell.AppActivate($app.Id)
        Start-Sleep -Milliseconds 250
    }
    if (!(Test-NotesFocus)) { exit 21 }
    $phase = 3
    foreach ($keys in @('{TAB}', 'AkashaFocus', '{TAB}', 'AkashaContent', '^{TAB}', ' ')) {
        if (!(Test-NotesFocus)) { exit 22 }
        [System.Windows.Forms.SendKeys]::SendWait($keys)
        Start-Sleep -Milliseconds 120
    }
    if (!(Test-NotesFocus)) { exit 23 }
    if (!$app.CloseMainWindow() -or !$app.WaitForExit(3000)) { exit 24 }

    $phase = 4
    $read = @'
import sqlite3
import sys

with sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True) as conn:
    rows = conn.execute("SELECT title, content FROM notes").fetchall()
sys.exit(0 if rows == [("AkashaFocus", "AkashaContent")] else 1 if not rows else 2)
'@
    $verifier = Join-Path $work 'verify_sqlite.py'
    [IO.File]::WriteAllText($verifier, $read)
    & (Join-Path $Runtime 'python.exe') $verifier $db
    if ($LASTEXITCODE -eq 0) { exit (0x420F -bor $uiaActivation) }
    if ($LASTEXITCODE -eq 1) { exit (0x4207 -bor $uiaActivation) }
    exit 25
} catch {
    [IO.File]::WriteAllText((Join-Path $work 'error.txt'), $_.Exception.GetBaseException().Message)
    exit (60 + $phase)
} finally {
    if ($null -ne $app -and !$app.HasExited) {
        if (!$app.CloseMainWindow() -or !$app.WaitForExit(1500)) {
            Stop-Process -InputObject $app -ErrorAction SilentlyContinue
        }
    }
}
