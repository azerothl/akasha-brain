param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateRange(0, 93)][int]$Offset
)

# Export borné d'un diagnostic du harnais via la CLI Windows Sandbox.
$path = Join-Path ([IO.Path]::GetTempPath()) "AkashaNotesDesktop-$Tag\ocr-error.txt"
$packet = 0x48000000
if (Test-Path -LiteralPath $path) {
    $bytes = [IO.File]::ReadAllBytes($path)
    for ($index = 0; $index -lt 3 -and $Offset + $index -lt $bytes.Length; $index++) {
        $packet = $packet -bor ([int]$bytes[$Offset + $index] -shl (8 * $index))
    }
}
exit $packet
