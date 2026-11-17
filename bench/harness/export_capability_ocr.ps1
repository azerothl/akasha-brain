param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateRange(-1, 96)][int]$Offset
)

$ErrorActionPreference = 'Stop'
$path = Join-Path ([IO.Path]::GetTempPath()) "AkashaProject-$Tag\work\ocr-result.bin"
$item = Get-Item -LiteralPath $path
if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    $item.Length -lt 1 -or $item.Length -gt 97) { exit 0x4910 }
$bytes = [IO.File]::ReadAllBytes($path)
if ($Offset -eq -1) { exit (0x49000000 -bor $bytes.Length) }
$packet = 0x49000000
for ($index = 0; $index -lt 3 -and $Offset + $index -lt $bytes.Length; $index++) {
    $packet = $packet -bor ([int]$bytes[$Offset + $index] -shl (8 * $index))
}
exit $packet
