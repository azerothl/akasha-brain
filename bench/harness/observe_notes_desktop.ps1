param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [ValidateSet('capture', 'before_save', 'after_save', 'after_restart', 'begin', 'save', 'restart', 'observe', 'close')]
    [string]$Mode = 'capture',
    [int]$NotesId,
    [switch]$KeepRestarted
)

$ErrorActionPreference = 'Stop'
$work = Join-Path ([IO.Path]::GetTempPath()) "AkashaDesktopState-$Tag"
$replayPath = Join-Path $work 'observations.json'
if ($Mode -in 'before_save', 'after_save', 'after_restart') {
    $observations = Get-Content -LiteralPath $replayPath -Raw | ConvertFrom-Json
    exit ([int]$observations.$Mode)
}

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class DesktopStateForeground {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
    public static uint Owner() {
        uint pid;
        GetWindowThreadProcessId(GetForegroundWindow(), out pid);
        return pid;
    }
}
'@

$runtime = Join-Path $work 'python'
$db = Join-Path $work 'notes.db'
$driver = Join-Path $work 'observe_notes_desktop.py'
$python = Join-Path $runtime 'python.exe'
$pythonw = Join-Path $runtime 'pythonw.exe'
$title = "Notes $([char]0x2014) banc Akasha"
$app = $null
$keepOpen = $false
$failure = 21

function Get-NotesWindow([int]$AppId) {
    $element = [System.Windows.Automation.AutomationElement]
    $owner = [System.Windows.Automation.PropertyCondition]::new($element::ProcessIdProperty, $AppId)
    $name = [System.Windows.Automation.PropertyCondition]::new($element::NameProperty, $title)
    $match = [System.Windows.Automation.AndCondition]::new($owner, $name)
    return $element::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $match)
}

function Test-NotesFocus([int]$AppId) {
    try {
        $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
        return ($null -ne $focused -and $focused.Current.ProcessId -eq $AppId)
    } catch [System.Windows.Automation.ElementNotAvailableException] {
        return $false
    }
}

function Focus-Notes([int]$AppId) {
    $shell = New-Object -ComObject WScript.Shell
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $window = Get-NotesWindow $AppId
        if ($null -ne $window) {
            if ([DesktopStateForeground]::Owner() -eq $AppId -and (Test-NotesFocus $AppId)) {
                return
            }
            $null = $shell.AppActivate($AppId)
            try { $window.SetFocus() } catch [System.InvalidOperationException] {}
        }
        Start-Sleep -Milliseconds 200
    }
    throw 'Notes did not expose a foreground window and UIA focus.'
}

function Wait-NotesWindow([int]$AppId) {
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($null -ne (Get-NotesWindow $AppId)) { return }
        Start-Sleep -Milliseconds 200
    }
}

function Read-Database {
    & $python $driver sqlite $db
    if ($LASTEXITCODE -notin 0x4650, 0x4651) {
        throw "Unexpected SQLite result: $LASTEXITCODE"
    }
    return ($LASTEXITCODE - 0x4650)
}

function Observe-Notes([int]$AppId, [int]$DatabaseResult) {
    if ($AppId -le 0 -or $AppId -gt 0xFFFFF) { throw 'PID outside packet range.' }
    $packet = 0x60000000 -bor ($AppId -shl 8) -bor ($DatabaseResult -shl 5)
    if (Get-Process -Id $AppId -ErrorAction SilentlyContinue) { $packet = $packet -bor 1 }
    $window = Get-NotesWindow $AppId
    if ($null -ne $window) {
        $packet = $packet -bor 2
        if (!$window.Current.IsOffscreen) { $packet = $packet -bor 4 }
    }
    if ([DesktopStateForeground]::Owner() -eq $AppId) { $packet = $packet -bor 8 }
    if (Test-NotesFocus $AppId) { $packet = $packet -bor 16 }
    return $packet
}

function Initialize-Notes {
    $null = New-Item -ItemType Directory -Path $work
    foreach ($name in @('python', 'notes_app.py', 'notes_store.py', 'observe_notes_desktop.py')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $work -Recurse
    }
}

function Invoke-NotesSave {
    $null = New-Item -ItemType File -Path (Join-Path $work 'save.request')
    $receipt = Join-Path $work 'save.done'
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (Test-Path -LiteralPath $receipt -PathType Leaf) { return (Read-Database) }
        Start-Sleep -Milliseconds 100
    }
    throw 'Notes did not acknowledge the save via Tk.'
}

$env:PYTHONHOME = $runtime
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:TCL_LIBRARY = Join-Path $runtime 'tcl8.6'
$env:TK_LIBRARY = Join-Path $runtime 'tk8.6'

try {
    if ($Mode -in 'capture', 'begin') {
        Initialize-Notes
        $failure = 22
        $argsOpen = '"{0}" open "{1}"' -f $driver, $db
        $app = Start-Process -FilePath $pythonw -ArgumentList $argsOpen -WorkingDirectory $work -WindowStyle Hidden -PassThru
        Focus-Notes $app.Id
        $before = Observe-Notes $app.Id (Read-Database)
        if ($Mode -eq 'begin') {
            $keepOpen = $true
            exit $before
        }
    } else {
        $ownedApp = Get-Process -Id $NotesId
        if ($ownedApp.Path -ne $pythonw) { throw 'Unexpected Notes executable.' }
        $app = $ownedApp
    }

    if ($Mode -eq 'observe') {
        $state = Observe-Notes $app.Id (Read-Database)
        $keepOpen = $true
        exit $state
    }
    if ($Mode -eq 'close') {
        if (!$app.CloseMainWindow() -or !$app.WaitForExit(4000)) { throw 'Notes did not close.' }
        exit 0x4601
    }

    if ($Mode -in 'capture', 'save') {
        $failure = 23
        $dbResult = Invoke-NotesSave
        if ($Mode -eq 'capture') { Focus-Notes $app.Id }
        $after = Observe-Notes $app.Id $dbResult
        if ($Mode -eq 'save') {
            $keepOpen = $true
            exit $after
        }
    }

    $failure = 24
    $oldId = $app.Id
    if (!$app.CloseMainWindow() -or !$app.WaitForExit(4000)) { throw 'Notes did not close.' }
    $appPath = Join-Path $work 'notes_app.py'
    $argsRestart = '"{0}" "{1}"' -f $appPath, $db
    $app = Start-Process -FilePath $pythonw -ArgumentList $argsRestart -WorkingDirectory $work -WindowStyle Hidden -PassThru
    if ($Mode -eq 'capture') {
        if ($app.Id -eq $oldId) { throw 'Notes PID reused.' }
        Focus-Notes $app.Id
    } else {
        Wait-NotesWindow $app.Id
    }
    $restarted = Observe-Notes $app.Id (Read-Database)
    if ($Mode -eq 'restart') {
        $keepOpen = $KeepRestarted.IsPresent
        exit $restarted
    }
    @{ before_save = $before; after_save = $after; after_restart = $restarted } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $replayPath -Encoding Ascii
    exit 0x4600
} catch {
    exit $failure
} finally {
    if (!$keepOpen -and $null -ne $app -and !$app.HasExited) {
        if (!$app.CloseMainWindow() -or !$app.WaitForExit(1500)) {
            Stop-Process -InputObject $app -ErrorAction SilentlyContinue
        }
    }
}
