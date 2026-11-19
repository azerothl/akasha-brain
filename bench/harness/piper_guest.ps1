$ErrorActionPreference = 'Stop'
$folder = Join-Path $PSScriptRoot 'piper'
$wav = Join-Path $env:TEMP 'reply.wav'
trap {
    [Console]::Write((@{failure="guest"; line=$_.InvocationInfo.ScriptLineNumber; exception=$_.Exception.GetType().Name} | ConvertTo-Json -Compress))
    exit 0
}
$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = "$folder\piper.exe"
$info.WorkingDirectory = $env:TEMP
$info.Arguments = '--model "{0}\fr_FR-siwis-medium.onnx" --output_file "{1}" --espeak_data "{2}\espeak-ng-data" --length_scale 1.1' -f $PSScriptRoot,$wav,$folder
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardInput = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$p = [Diagnostics.Process]::Start($info)
$out = $p.StandardOutput.ReadToEndAsync()
$err = $p.StandardError.ReadToEndAsync()
$inputBytes = [IO.File]::ReadAllBytes("$PSScriptRoot\reply.txt")
$p.StandardInput.BaseStream.Write($inputBytes,0,$inputBytes.Length)
$p.StandardInput.Close()
$peak = 0L
while (-not $p.HasExited) {
    $p.Refresh()
    $peak = [Math]::Max($peak, $p.PeakWorkingSet64)
    [void]$p.WaitForExit(20)
}
if ($p.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $wav)) {
    [Console]::Write((@{failure="piper"; code=$p.ExitCode} | ConvertTo-Json -Compress))
    exit 0
}
if ((Get-Item -LiteralPath $wav).Length -gt 10584044) { exit 23 }
$data = [IO.File]::ReadAllBytes($wav)
$packet = @{ wav = [Convert]::ToBase64String($data); peak_bytes = $peak } | ConvertTo-Json -Compress
[Console]::Write($packet)
