param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateSet('admit', 'faulty', 'reference')][string]$Phase
)
$ErrorActionPreference = 'Stop'
$scratch = Join-Path ([IO.Path]::GetTempPath()) "AkashaTaskTransfer-$Tag"
$null = New-Item -ItemType Directory -Path $scratch -Force
$runtime = Join-Path $scratch 'python'
if (!(Test-Path -LiteralPath $runtime)) {
    Copy-Item -LiteralPath "C:\AkashaGuidedInput-$Tag\python" -Destination $runtime -Recurse
}
$env:PYTHONHOME = $runtime
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:TCL_LIBRARY = Join-Path $runtime 'tcl8.6'
$env:TK_LIBRARY = Join-Path $runtime 'tk8.6'
$python = Join-Path $runtime 'python.exe'
if ($Phase -eq 'admit') {
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'packages'
    & $python (Join-Path $PSScriptRoot 'admit.py')
    exit $LASTEXITCODE
}
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$work = Join-Path $scratch $Phase
$null = New-Item -ItemType Directory -Path $work
$control = Join-Path $PSScriptRoot 'control.py'
if ($Phase -eq 'reference') {
    & $python $control initialize $work --reference
} else {
    & $python $control initialize $work
}
if ($LASTEXITCODE -ne 0) { exit 51 }
& $python $control observe $work
if ($LASTEXITCODE -ne 0) { exit 52 }
& $python $control verify $work
exit $LASTEXITCODE
