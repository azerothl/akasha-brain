param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [Parameter(Mandatory = $true)][ValidatePattern('^(control|baseline|cycle-[1-3]-attempt-[1-2])$')][string]$InputName,
    [switch]$Locate
)
$ErrorActionPreference = 'Stop'
$inputDir = "C:\AkashaGuidedInput-$Tag"
$root = Join-Path ([IO.Path]::GetTempPath()) "AkashaGuided-$Tag"
$null = New-Item -ItemType Directory -Path $root -Force
$runtime = Join-Path $root 'python'
if (!(Test-Path -LiteralPath (Join-Path $runtime 'python.exe'))) {
    Copy-Item -LiteralPath (Join-Path $inputDir 'python') -Destination $root -Recurse
}
$work = Join-Path $root ([guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $work

function Invoke-Python([string]$Arguments) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = Join-Path $runtime 'python.exe'
    $start.Arguments = $Arguments
    $start.WorkingDirectory = $work
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [Text.Encoding]::UTF8
    $start.StandardErrorEncoding = [Text.Encoding]::UTF8
    $process = [Diagnostics.Process]::Start($start)
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (!$process.WaitForExit(20000)) {
            $process.Kill()
            $process.WaitForExit(3000) | Out-Null
            return @{ Exit = 15; Output = '' }
        }
        return @{
            Exit = $process.ExitCode
            Output = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
        }
    } finally {
        $process.Dispose()
    }
}

try {
    Copy-Item -LiteralPath (Join-Path $inputDir "$InputName\notes_store.py") -Destination $work
    $fixture = Join-Path $inputDir 'fixture'
    $env:PYTHONHOME = $runtime
    $env:PYTHONPATH = "$work;$fixture;$(Join-Path $inputDir 'packages')"
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
    $env:TCL_LIBRARY = Join-Path $runtime 'tcl8.6'
    $env:TK_LIBRARY = Join-Path $runtime 'tk8.6'
    $xmlPath = Join-Path $work 'pytest.xml'
    $pytestArgs = '-m pytest -q -p no:cacheprovider "{0}\tests" --basetemp "{1}\pytest-temp" --junitxml "{2}"' -f $fixture, $work, $xmlPath
    $pytest = Invoke-Python $pytestArgs
    $verifier = @{ Exit = 0; Output = '' }
    if (!$Locate) {
        $verifyArgs = '"{0}\verifiers\verify_notes.py" --db "{1}\notes-check.db" --reset' -f $fixture, $work
        $verifier = Invoke-Python $verifyArgs
    }
    $tests = $failures = $errors = $skips = 0
    if (Test-Path -LiteralPath $xmlPath) {
        [xml]$xml = Get-Content -LiteralPath $xmlPath -Raw
        $suite = $xml.testsuites.testsuite
        $tests = [int]$suite.tests
        $failures = [int]$suite.failures
        $errors = [int]$suite.errors
        $skips = [int]$suite.skipped
    }
    $diagnosis = 0
    if ($pytest.Output -match 'Cannot operate on a closed database') { $diagnosis = 1 }
    foreach ($count in @($tests,$failures,$errors,$skips,$pytest.Exit,$verifier.Exit)) {
        if ($count -lt 0 -or $count -gt 15) { exit 33 }
    }
    exit (0x40000000 -bor ($diagnosis -shl 24) -bor ($tests -shl 20) -bor ($failures -shl 16) -bor ($errors -shl 12) -bor ($skips -shl 8) -bor ($pytest.Exit -shl 4) -bor $verifier.Exit)
} catch {
    exit 34
} finally {
    $resolvedRoot = (Resolve-Path -LiteralPath $root).Path.TrimEnd('\') + '\'
    $resolvedWork = (Resolve-Path -LiteralPath $work).Path
    if ($resolvedWork.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedWork -Recurse -Force
    }
}
