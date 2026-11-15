param([Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag)

$ErrorActionPreference = 'Stop'
$inputDir = "C:\AkashaGuidedInput-$Tag"
$sentinel = Join-Path $inputDir 'isolation-sentinel.txt'

function Test-WriteDenied([string]$Path, [IO.FileMode]$Mode) {
    try {
        $file = [IO.File]::Open($Path, $Mode, [IO.FileAccess]::Write)
        $file.Dispose()
        return $false
    } catch {
        return (($_.Exception.GetBaseException().HResult -band 65535) -in 5, 19, 65)
    }
}

$code = 0x4500
if ([IO.File]::ReadAllText($sentinel) -ceq $Tag) { $code = $code -bor 1 }
if (Test-WriteDenied $sentinel ([IO.FileMode]::Open)) { $code = $code -bor 2 }
if (Test-WriteDenied (Join-Path $inputDir 'isolation-probe.tmp') ([IO.FileMode]::CreateNew)) {
    $code = $code -bor 4
}
$scratch = Join-Path ([IO.Path]::GetTempPath()) "AkashaNotesProbe-$Tag.txt"
try {
    [IO.File]::WriteAllText($scratch, $Tag)
    if ([IO.File]::ReadAllText($scratch) -ceq $Tag) { $code = $code -bor 8 }
} finally {
    [IO.File]::Delete($scratch)
}
exit $code
