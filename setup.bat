@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo   口蘑剧情编辑器 · 环境准备
echo   ========================================
where python >nul 2>&1 || (echo   没找到 python，先装 Python 3.10+ & pause & exit /b 1)
echo   [1/3] 创建 .venv
if not exist ".venv\Scripts\python.exe" python -m venv .venv
echo   [2/3] 安装依赖（第一次要几分钟）
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo   依赖装失败 & pause & exit /b 1)
echo   [3/3] 环境自检
".venv\Scripts\python.exe" -c "import sys;sys.path.insert(0,'.');import imgui_bundle,UnityPy,PIL,numpy;from storykit import story,session;print('  OK')" || (echo   自检没过 & pause & exit /b 1)
echo.
echo   完成。双击 启动.bat 即可。
pause
