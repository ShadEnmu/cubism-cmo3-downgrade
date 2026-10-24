@echo off
rem Builds dist\Cmo3_54_to_53\ (folder build: fewer antivirus false positives than --onefile)
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name Cmo3_54_to_53 ^
  --version-file version_info.txt ^
  --paths src ^
  src\gui.py || exit /b 1
copy /y README.md dist\Cmo3_54_to_53\ >nul
copy /y LICENSE dist\Cmo3_54_to_53\LICENSE.txt >nul
echo.
echo Done: dist\Cmo3_54_to_53\Cmo3_54_to_53.exe
