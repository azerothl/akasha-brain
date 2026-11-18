param([ValidateSet('start','transcribe')][string]$Action,
      [ValidatePattern('^audio-[0-9a-f]{32}\.(wav|flac)$')][string]$Audio)
$ErrorActionPreference = 'Stop'
Set-Location $env:TEMP
$url = 'http://127.0.0.1:18743'
if ($Action -eq 'start') {
    $env:OMP_NUM_THREADS = '4'
    $log = Join-Path $env:TEMP 'whisper-init.log'
    # WMI starts the server outside the short-lived HCS stdout session.
    $line = 'cmd.exe /d /c "{0}\whisper-server.exe -m {0}\ggml-small.bin --host 127.0.0.1 --port 18743 -l fr -t 4 -bs 1 -bo 1 -nf -nlp >"{1}" 2>&1"' -f $PSScriptRoot,$log
    $spawn = ([wmiclass]'Win32_Process').Create($line,$env:TEMP,$null)
    if ($spawn.ReturnValue -ne 0) { exit 24 }
    for ($i = 0; $i -lt 180; $i++) {
        if (-not (Get-Process -Id $spawn.ProcessId -ErrorAction SilentlyContinue)) { break }
        if ((Test-Path -LiteralPath $log) -and (Select-String -Quiet -LiteralPath $log -SimpleMatch 'using CUDA0 backend')) {
            & curl.exe --noproxy '*' -fs --max-time 1 "$url/health" *> $null
            if ($LASTEXITCODE -eq 0) {
                $process = Get-Process -Name whisper-server
                [Console]::Write("CUDA0 $($process.Id)")
                exit 0
            }
        }
        Start-Sleep -Milliseconds 500
    }
    # A successful CPU-only startup is not a CUDA admission.
    exit 24
}
if (-not $Audio) { exit 21 }
# In v1.8.3 the server copies temperature_inc from the request even with -nf.
# It also wraps verbose segments at 60 characters unless max_len is specified.
& curl.exe --noproxy '*' -fsS --max-time 150 -F "file=@$PSScriptRoot\$Audio" -F 'response_format=verbose_json' -F 'temperature=0' -F 'temperature_inc=0' -F 'max_len=65536' "$url/inference" -o "$env:TEMP\asr-response.json"
if ($LASTEXITCODE -ne 0) { exit 22 }
try {
    $out = Get-Item "$env:TEMP\asr-response.json"
    if ($out.Length -gt 2097152) { exit 23 }
    $bytes = [IO.File]::ReadAllBytes($out.FullName)
    [Console]::OpenStandardOutput().Write($bytes, 0, $bytes.Length)
} finally {
    Remove-Item -LiteralPath "$env:TEMP\asr-response.json" -ErrorAction SilentlyContinue
}
