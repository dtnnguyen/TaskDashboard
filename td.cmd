@echo off
rem Shortcut for the TaskDashboard command line on Windows. Works from any folder:
rem   td config --data %USERPROFILE%\Documents\TaskDashboard
rem   td build --open
rem Same as: set PYTHONPATH=src ^& py -m taskdashboard ...
setlocal
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m taskdashboard %*) else (python -m taskdashboard %*)
exit /b %errorlevel%
