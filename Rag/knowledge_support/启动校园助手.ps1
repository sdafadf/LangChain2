param([ValidateRange(1024,65535)][int]$Port = 8501)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$candidates = @(
    (Join-Path $PSScriptRoot '.venv/Scripts/python.exe'),
    'D:/pycharmproject/pythonProject/.venv/Scripts/python.exe'
)
$systemPython = Get-Command python -ErrorAction SilentlyContinue
if ($systemPython) { $candidates += $systemPython.Source }
$selectedPython = $null
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    & $candidate -c "import importlib.util,sys; sys.exit(not all(importlib.util.find_spec(m) for m in ['streamlit','pymilvus','langchain_openai','langchain_deepseek','deepagents','yaml','dotenv','pandas','pypdf','docx']))"
    if ($LASTEXITCODE -eq 0) { $selectedPython = $candidate; break }
}
if (-not $selectedPython) {
    throw 'No compatible Python environment. Use Python 3.11/3.12, create .venv, then install requirements.txt.'
}
Write-Host "Python: $selectedPython"
Write-Host "Campus app: http://127.0.0.1:$Port"
& $selectedPython -B -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
exit $LASTEXITCODE
