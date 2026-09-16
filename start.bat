@echo off
rem One-click launcher for Daily AI News Agent
title Daily AI News Agent
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python start.py
if errorlevel 1 pause
