param([Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{8}$')][string]$Tag)

$ErrorActionPreference = 'Stop'
$inputDir = "C:\AkashaGuidedInput-$Tag"
$scratch = Join-Path ([IO.Path]::GetTempPath()) "AkashaProject-$Tag"
$pristine = Join-Path $inputDir 'snapshot'
$work = Join-Path $scratch 'work'
$null = New-Item -ItemType Directory -Path $scratch
Copy-Item -LiteralPath $pristine -Destination $work -Recurse
$request = [IO.File]::ReadAllText((Join-Path $inputDir 'validation.json')) | ConvertFrom-Json

switch -Exact ($request.operation) {
    'replace' {
        $env:GIT_CONFIG_NOSYSTEM = '1'
        $env:GIT_CONFIG_GLOBAL = 'NUL'
        $git = Join-Path $inputDir 'git\git.exe'
        $patch = Join-Path $inputDir 'proposal.diff'
        & $git -C $work apply --check -- $patch
        if ($LASTEXITCODE -ne 0) { exit 0x4711 }
        & $git -C $work apply -- $patch
        if ($LASTEXITCODE -ne 0) { exit 0x4712 }
    }
    'delete' {
        $source = Join-Path $work $request.target
        if (!(Test-Path -LiteralPath $source -PathType Leaf)) { exit 0x4716 }
        [IO.File]::Delete($source)
    }
    'move' {
        [IO.File]::Move((Join-Path $work $request.target), (Join-Path $work $request.destination))
    }
    default { exit 0x4717 }
}

function Test-CopyHashes {
    foreach ($name in $request.absent) {
        if (Test-Path -LiteralPath (Join-Path $work $name)) { return $false }
    }
    foreach ($file in $request.files.PSObject.Properties) {
        $path = Join-Path $work $file.Name
        if (!(Test-Path -LiteralPath $path -PathType Leaf) -or (Get-FileHash -LiteralPath $path).Hash -ne $file.Value) {
            return $false
        }
    }
    return $true
}
if (!(Test-CopyHashes)) { exit 0x4713 }

$runtime = Join-Path $inputDir 'python'
$python = Join-Path $runtime 'python.exe'
$packages = Join-Path $scratch 'packages'
if ($request.dependencies.Count -gt 0) {
    $installer = Join-Path $inputDir 'install_project_dependencies.py'
    & $python -I -B -X utf8 $installer $inputDir $scratch
    if ($LASTEXITCODE -ne 0) { exit 0x4718 }
}
$test = Join-Path $pristine $request.test
$bootstrap = 'import runpy, sys; sys.path[0:0] = sys.argv[1:3]; sys.argv = sys.argv[3:]; runpy.run_path(sys.argv[0], run_name=''__main__'')'
Set-Location -LiteralPath $work
& $python -I -B -X utf8 -c $bootstrap $work $packages $test
if ($LASTEXITCODE -ne 0) { exit 0x4714 }
if (!(Test-CopyHashes)) { exit 0x4715 }
exit 0x4700
