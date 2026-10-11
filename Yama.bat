@echo off
rem Abre el control del teclado. La primera vez instala lo necesario en .venv
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe goto run

where python >nul 2>nul
if errorlevel 1 (
  echo No encontre Python. Instalalo desde https://www.python.org/downloads/
  echo y marca la casilla "Add python.exe to PATH". Luego vuelve a abrir Yama.bat.
  pause
  exit /b 1
)
echo Primera vez: instalando lo necesario (tarda unos segundos)...
python -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto error

:run
start "" .venv\Scripts\pythonw.exe -m yama
exit /b 0

:error
echo No se pudo completar la instalacion. Revisa tu conexion a internet y vuelve a intentar.
if exist .venv rmdir /s /q .venv
pause
exit /b 1
