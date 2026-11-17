@echo off
setlocal
py -3 "%~dp0plugins\codex-cost-band\scripts\cost_band.py" watch %*
