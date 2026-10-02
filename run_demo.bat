@echo off
rem Copyright 2026 Ib Helmer Nielsen
rem SPDX-License-Identifier: Apache-2.0
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 dijkstra_routing_demo.py %*
goto finished
:try_python
python dijkstra_routing_demo.py %*
:finished
set "result=%errorlevel%"
if not "%result%"=="0" (
    echo.
    echo The demo did not start successfully.
    echo Check that Python 3.10 or newer and Tcl/Tk support are installed.
    echo Try: python -m tkinter
    pause
)
endlocal & exit /b %result%
