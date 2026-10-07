# Start the TaskDashboard tray icon at login on Windows, and start it now.
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1                  install
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Data <folder>   install, keeping your plan,
#                                                                                history and page in <folder>
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Remove          uninstall (data is left alone)
param([switch]$Remove, [string]$Data)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "windows\taskdashboard_tray.py"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "TaskDashboard.lnk"

# Files from a downloaded release carry Windows' "from the internet" mark; clear it.
Get-ChildItem -Path $Root -Recurse -File | Unblock-File

if ($Remove) {
    Remove-Item $Shortcut -ErrorAction SilentlyContinue
    Write-Host "Removed $Shortcut (quit the running icon from its menu)"
    exit 0
}

# Find Python: the py launcher (python.org / winget installs), else python on PATH.
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = (& py -3 -c "import sys; print(sys.executable)").Trim()
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = (& python -c "import sys; print(sys.executable)").Trim()
} else {
    Write-Host "Python not found. Install it with:  winget install Python.Python.3.13"
    exit 1
}
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"   # same Python, no console window
if (-not (Test-Path $PythonW)) { $PythonW = $Python }

& $Python -m pip install --user --quiet -r (Join-Path $Root "windows\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$env:PYTHONPATH = Join-Path $Root "src"

# -Data: remember the folder in the config file, which the tray icon reads too.
if ($Data) {
    & $Python -m taskdashboard config --data $Data
    if ($LASTEXITCODE -ne 0) { throw "taskdashboard config failed" }
}

# First install: start from the example plan (an existing plan is never touched).
& $Python -m taskdashboard init
if ($LASTEXITCODE -ne 0) { throw "taskdashboard init failed" }

$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut($Shortcut)
$Link.TargetPath = $PythonW
$Link.Arguments = "`"$Script`""
$Link.WorkingDirectory = $Root
$Link.Description = "TaskDashboard tray icon"
$Link.Save()
Write-Host "Installed $Shortcut"

Start-Process -FilePath $PythonW -ArgumentList "`"$Script`"" -WorkingDirectory $Root
Write-Host "Started. Look for the ring icon in the notification area (click ^ if it's hidden)."
