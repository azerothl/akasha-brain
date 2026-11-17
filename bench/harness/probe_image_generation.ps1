param([Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag)
$ErrorActionPreference = 'Stop'
$path = Join-Path ([IO.Path]::GetTempPath()) "AkashaProject-$Tag\work\image-status.txt"
if (!(Test-Path -LiteralPath $path -PathType Leaf)) { exit 0x4900 }
$item = Get-Item -LiteralPath $path
if ($item.Length -gt 8 -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { exit 0x4902 }
if ([IO.File]::ReadAllText($path) -eq 'ready') { exit 0x4901 }
exit 0x4902
