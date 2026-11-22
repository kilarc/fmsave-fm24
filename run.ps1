$ToolArguments = @($args)
$ErrorActionPreference = 'Stop'
$toolRoot = $PSScriptRoot
$pythonCandidates = @()
if ($env:CODEX_PRIMARY_RUNTIME_PYTHON) { $pythonCandidates += $env:CODEX_PRIMARY_RUNTIME_PYTHON }
$runtimeHint = Join-Path $toolRoot 'runtime_python.txt'
if (Test-Path -LiteralPath $runtimeHint) {
    $pythonCandidates += (Get-Content -LiteralPath $runtimeHint -Raw).Trim()
}
try {
    $runtimePackages = Get-AppxPackage -Name 'OpenAI.CodexPrimaryRuntime*' -ErrorAction SilentlyContinue
    foreach ($runtimePackage in $runtimePackages) {
        $pythonCandidates += Join-Path $runtimePackage.InstallLocation 'dependencies\python\python.exe'
    }
} catch { }
foreach ($commandName in @('python', 'python3', 'py')) {
    $candidate = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($candidate) { $pythonCandidates += $candidate.Source }
}
$pythonExecutable = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    try {
        & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExecutable = $candidate; break }
    } catch { }
}
if (-not $pythonExecutable) { throw 'Python 3.12 이상을 찾지 못했습니다.' }
$environmentDirectory = Join-Path $toolRoot '.fm24-env'
$environmentPython = Join-Path $environmentDirectory 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) {
    & $pythonExecutable -m venv $environmentDirectory
    if ($LASTEXITCODE -ne 0) { throw '실행 환경 생성에 실패했습니다.' }
}
# Python 3.14+ ships zstd itself; the bundled backports wheel is only for 3.12/3.13.
& $environmentPython -c "import sys, importlib.util as u; raise SystemExit(0 if sys.version_info >= (3,14) or u.find_spec('backports') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $environmentPython -m pip install --no-index --find-links (Join-Path $toolRoot 'wheels') 'backports.zstd==1.8.0'
    if ($LASTEXITCODE -ne 0) { throw '압축 해제 모듈 설치에 실패했습니다.' }
}
$env:PYTHONIOENCODING = 'utf-8'
if (-not $ToolArguments -or $ToolArguments.Count -eq 0) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = '분석할 FM24 세이브 선택'
    $dialog.Filter = 'Football Manager 세이브 (*.fm)|*.fm'
    $dialog.InitialDirectory = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Sports Interactive\Football Manager 2024\games'
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $ToolArguments = @('dump', $dialog.FileName, '-o', (Join-Path $toolRoot 'fm24_dump'))
    $dialog.Dispose()
}
& $environmentPython (Join-Path $toolRoot 'fm24.py') @ToolArguments
exit $LASTEXITCODE
