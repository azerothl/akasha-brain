$ErrorActionPreference = 'Stop'
Set-Location $env:TEMP
$env:OMP_NUM_THREADS = '4'
$inputAudio = Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'audio.*' -File
if (@($inputAudio).Count -ne 1) { exit 21 }
$target = Join-Path $env:TEMP 'akasha-transcript'
$ErrorActionPreference = 'Continue'
& "$PSScriptRoot\whisper-cli.exe" -m "$PSScriptRoot\ggml-small.bin" -f $inputAudio.FullName -l fr -ng -t 4 -bs 1 -bo 1 -nf -ojf -of $target *> $null
if ($LASTEXITCODE -ne 0) { exit 22 }
$ErrorActionPreference = 'Stop'
$result = Get-Item -LiteralPath "$target.json"
if ($result.Length -gt 2097152) { exit 23 }
$bytes = [IO.File]::ReadAllBytes($result.FullName)
[Console]::OpenStandardOutput().Write($bytes, 0, $bytes.Length)
