param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateSet('localize', 'reference', 'apply', 'verify')][string]$Phase,
    [ValidateRange(1, 2)][int]$Attempt = 1
)
$ErrorActionPreference = 'Stop'
$scratch = Join-Path ([IO.Path]::GetTempPath()) "AkashaTransfer-$Tag"
$null = New-Item -ItemType Directory -Path $scratch -Force
$runtime = Join-Path $scratch 'python'
if (!(Test-Path -LiteralPath $runtime)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'python') -Destination $scratch -Recurse
}
$trial = if ($Phase -in 'apply', 'verify') { "candidate-$Attempt" } else { $Phase }
$proposal = Join-Path $PSScriptRoot "proposal\attempt-$Attempt"
$work = Join-Path $scratch $trial
$source = Join-Path $work 'repair.py'
if ($Phase -ne 'verify') {
    $null = New-Item -ItemType Directory -Path $work
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'case\repair.py') -Destination $source
}
if ($Phase -eq 'apply') {
    $git = Join-Path $PSScriptRoot 'git\git.exe'
    $patch = Join-Path $proposal 'proposal.diff'
    $env:GIT_CONFIG_NOSYSTEM = '1'
    $env:GIT_CONFIG_GLOBAL = 'NUL'
    & $git -C $work apply --check -- $patch
    if ($LASTEXITCODE -ne 0) { exit 41 }
    & $git -C $work apply -- $patch
    if ($LASTEXITCODE -ne 0) { exit 42 }
}
if ($Phase -in 'apply', 'verify') {
    $expected = (Get-Content -LiteralPath (Join-Path $proposal 'repair.sha256') -Raw).Trim()
    if ((Get-FileHash -LiteralPath $source).Hash -ne $expected) { exit 43 }
}
if ($Phase -eq 'apply') { exit 0x4602 }
$env:PYTHONHOME = $runtime
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:TCL_LIBRARY = Join-Path $runtime 'tcl8.6'
$env:TK_LIBRARY = Join-Path $runtime 'tk8.6'
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
& (Join-Path $runtime 'python.exe') (Join-Path $PSScriptRoot 'case\oracle.py') $Phase $source $work
exit $LASTEXITCODE
