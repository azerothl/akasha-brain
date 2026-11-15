param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag,
    [Parameter(Mandatory = $true)][ValidatePattern('^(control|baseline|cycle-[1-3]-attempt-[1-2]|rbitnet-[1-2])$')][string]$InputName,
    [switch]$Locate,
    [switch]$PrepareReference,
    [switch]$VerifyPrepared,
    [switch]$ApplyDiff
)
$ErrorActionPreference = 'Stop'
$inputDir = "C:\AkashaGuidedInput-$Tag"
$root = Join-Path ([IO.Path]::GetTempPath()) "AkashaGuided-$Tag"
$null = New-Item -ItemType Directory -Path $root -Force
$reference = Join-Path $inputDir 'baseline\notes_store.py'
$preparedDir = Join-Path $root "prepared-$InputName"
$prepared = Join-Path $preparedDir 'notes_store.py'
$isRepair = $InputName -match '^rbitnet-[1-2]$'
if (@($Locate, $PrepareReference, $VerifyPrepared, $ApplyDiff | Where-Object { $_ }).Count -gt 1) { exit 35 }
if ($PrepareReference -and $InputName -ne 'baseline') { exit 35 }
if ($VerifyPrepared -and $InputName -ne 'baseline' -and !$isRepair) { exit 35 }
if ($ApplyDiff -and !$isRepair) { exit 35 }
if ($PrepareReference) {
    try {
        $null = New-Item -ItemType Directory -Path $preparedDir
        Copy-Item -LiteralPath $reference -Destination $prepared
        if ((Get-FileHash -LiteralPath $reference).Hash -ne (Get-FileHash -LiteralPath $prepared).Hash) { exit 36 }
        exit 0x4601
    } catch {
        exit 36
    }
}
if ($ApplyDiff) {
    try {
        $null = New-Item -ItemType Directory -Path $preparedDir
        Copy-Item -LiteralPath (Join-Path $inputDir 'control\notes_store.py') -Destination $prepared
        $patch = Join-Path $inputDir "$InputName\proposal.diff"
        $git = Join-Path $inputDir 'git\git.exe'
        $env:GIT_CONFIG_NOSYSTEM = '1'
        $env:GIT_CONFIG_GLOBAL = 'NUL'
        & $git -C $preparedDir apply --check -- $patch
        if ($LASTEXITCODE -ne 0) { exit 41 }
        & $git -C $preparedDir apply -- $patch
        if ($LASTEXITCODE -ne 0) { exit 42 }
        $expectedHash = (Get-Content -LiteralPath (Join-Path $inputDir "$InputName\notes-store.sha256") -Raw).Trim()
        if ((Get-FileHash -LiteralPath $prepared).Hash -ne $expectedHash) { exit 43 }
        exit 0x4602
    } catch {
        exit 43
    }
}
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
    $source = Join-Path $inputDir "$InputName\notes_store.py"
    if ($VerifyPrepared) {
        $expectedHash = if ($isRepair) {
            (Get-Content -LiteralPath (Join-Path $inputDir "$InputName\notes-store.sha256") -Raw).Trim()
        } else {
            (Get-FileHash -LiteralPath $reference).Hash
        }
        if ((Get-FileHash -LiteralPath $prepared).Hash -ne $expectedHash) { exit 36 }
        $source = $prepared
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $work 'notes_store.py')
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
    if ($VerifyPrepared) {
        $names = Get-Content -LiteralPath (Join-Path $inputDir 'notes-test-cases.json') -Raw | ConvertFrom-Json
        if ($tests -ne 4) { exit 38 }
        if ($names.Count -ne 4) { exit 37 }
        $packed = 0
        for ($index = 0; $index -lt $names.Count; $index++) {
            $testCase = @($suite.testcase | Where-Object { $_.name -ceq $names[$index] })
            if ($testCase.Count -ne 1) { exit 37 }
            $status = 0
            if ($testCase[0].SelectSingleNode('failure')) { $status = 1 }
            elseif ($testCase[0].SelectSingleNode('error')) { $status = 2 }
            elseif ($testCase[0].SelectSingleNode('skipped')) { $status = 3 }
            $packed = $packed -bor ($status -shl (8 + 2 * $index))
        }
        exit (0x50000000 -bor ($diagnosis -shl 16) -bor $packed -bor ($pytest.Exit -shl 4) -bor $verifier.Exit)
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
