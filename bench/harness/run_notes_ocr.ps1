param([Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NotesForeground {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
    public static uint Owner() {
        uint pid;
        GetWindowThreadProcessId(GetForegroundWindow(), out pid);
        return pid;
    }
}
'@

$work = Join-Path ([IO.Path]::GetTempPath()) "AkashaNotesDesktop-$Tag"
$null = New-Item -ItemType Directory -Path $work
$prepared = Join-Path ([IO.Path]::GetTempPath()) "AkashaGuided-$Tag\prepared-rbitnet-1\notes_store.py"
$db = Join-Path $work 'notes.db'
$app = $null
$phase = 0

function Test-NotesFocus([int]$AppId) {
    if ([NotesForeground]::Owner() -ne $AppId) { return $false }
    try {
        $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
        return ($null -ne $focused -and $focused.Current.ProcessId -eq $AppId -and
                [NotesForeground]::Owner() -eq $AppId)
    } catch [System.Windows.Automation.ElementNotAvailableException] {
        return $false
    }
}

function Focus-Notes([int]$AppId) {
    $pidProperty = [System.Windows.Automation.AutomationElement]::ProcessIdProperty
    $owner = [System.Windows.Automation.PropertyCondition]::new($pidProperty, $AppId)
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $window = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $owner)
        if ($null -ne $window -and !(Test-NotesFocus $AppId)) {
            $shell = New-Object -ComObject WScript.Shell
            $null = $shell.AppActivate($AppId)
            if (!(Test-NotesFocus $AppId)) {
                try { $window.SetFocus() } catch [System.InvalidOperationException] {}
            }
        }
        Start-Sleep -Milliseconds 200
        if ($null -ne $window -and (Test-NotesFocus $AppId)) { return $true }
    }
    return $false
}

try {
    $runtime = Join-Path $work 'python'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'python') -Destination $work -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ocr-packages') -Destination $work -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'notes_app.py'), $prepared -Destination $work
    $env:PYTHONHOME = $runtime
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPATH = Join-Path $work 'ocr-packages'
    $env:TCL_LIBRARY = Join-Path $runtime 'tcl8.6'
    $env:TK_LIBRARY = Join-Path $runtime 'tk8.6'
    $appPath = Join-Path $work 'notes_app.py'
    $appArgs = '"{0}" "{1}"' -f $appPath, $db
    $pythonw = Join-Path $runtime 'pythonw.exe'
    $python = Join-Path $runtime 'python.exe'
    $ocr = Join-Path $PSScriptRoot 'notes_ocr_guest.py'
    $ocrError = Join-Path $work 'ocr-error.txt'

    $phase = 1
    $app = Start-Process -FilePath $pythonw -ArgumentList $appArgs -WorkingDirectory $work -WindowStyle Hidden -PassThru
    if (!(Focus-Notes $app.Id)) { exit 21 }
    foreach ($keys in @('{TAB}', 'Note Akasha', '{TAB}', 'Contenu durable')) {
        if (!(Test-NotesFocus $app.Id) -and !(Focus-Notes $app.Id)) {
            [IO.File]::WriteAllText($ocrError, 'Notes did not regain foreground and UIA focus before keyboard input.')
            exit 22
        }
        [System.Windows.Forms.SendKeys]::SendWait($keys)
        Start-Sleep -Milliseconds 120
    }
    $phase = 2
    & $python $ocr save $app.Id --error-log $ocrError
    if ($LASTEXITCODE -ne 0) { exit (30 + $LASTEXITCODE) }
    Start-Sleep -Milliseconds 250
    $oldId = $app.Id
    if (!$app.CloseMainWindow() -or !$app.WaitForExit(4000)) { exit 23 }

    $phase = 3
    $app = Start-Process -FilePath $pythonw -ArgumentList $appArgs -WorkingDirectory $work -WindowStyle Hidden -PassThru
    if ($app.Id -eq $oldId -or !(Focus-Notes $app.Id)) { exit 24 }
    & $python $ocr restore $app.Id --error-log $ocrError
    $ocrExit = $LASTEXITCODE
    $phase = 4
    & $python $ocr sqlite $db --error-log $ocrError
    $sqliteExit = $LASTEXITCODE

    $packet = 0x4703
    if ($ocrExit -eq 0) { $packet = $packet -bor 12 }
    elseif ($ocrExit -eq 8) { $packet = $packet -bor 4 }
    if ($sqliteExit -eq 0) { $packet = $packet -bor 16 }
    exit $packet
} catch {
    exit (60 + $phase)
} finally {
    if ($null -ne $app -and !$app.HasExited) {
        if (!$app.CloseMainWindow() -or !$app.WaitForExit(1500)) {
            Stop-Process -InputObject $app -ErrorAction SilentlyContinue
        }
    }
}
