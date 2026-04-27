@echo off
setlocal

set "BASE_DIR=%~dp0"
set "PY310=C:\Program Files\Python310\python.exe"
set "VENV_DIR=%BASE_DIR%.venv"

if not exist "%PY310%" (
  echo [ERROR] Python 3.10 not found at: %PY310%
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [SETUP] Creating venv: %VENV_DIR%
  "%PY310%" -m venv "%VENV_DIR%"
)

echo [SETUP] Upgrading pip...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip

echo [SETUP] Installing GPU requirements...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%BASE_DIR%requirements-gpu.txt"

echo [CHECK] Runtime GPU status...
"%VENV_DIR%\Scripts\python.exe" -c "import torch, onnxruntime as ort; print('torch', torch.__version__, 'cuda=', torch.cuda.is_available(), 'cuda_ver=', torch.version.cuda); print('onnx providers', ort.get_available_providers())"

echo [RUN] Starting server...
"%VENV_DIR%\Scripts\python.exe" "%BASE_DIR%server.py"

endlocal