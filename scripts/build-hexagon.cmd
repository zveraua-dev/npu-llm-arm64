@echo off
rem Build llama.cpp Hexagon (NPU) + OpenCL backend for Windows on Snapdragon
setlocal
cd /d "%~dp0..\llama.cpp"

set VS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools
call "%VS%\VC\Auxiliary\Build\vcvarsall.bat" arm64
if errorlevel 1 (echo vcvarsall FAILED & exit /b 1)

set OPENCL_SDK_ROOT=C:\Qualcomm-User\OpenCL_SDK\2.3.2
set HEXAGON_SDK_ROOT=C:\Qualcomm-User\Hexagon_SDK\6.6.0.0
set HEXAGON_TOOLS_ROOT=C:\Qualcomm-User\Hexagon_SDK\6.6.0.0\tools\HEXAGON_Tools\19.0.07
set HEXAGON_HTP_CERT=%USERPROFILE%\Certs\ggml-htp-v1.pfx
set HEXAGON_HTP_CERT_PASSWORD=npu-llm-lab
set WINDOWS_SDK_BIN=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0
set PATH=%PATH%;%USERPROFILE%\AppData\Local\Programs\Python\Python312-arm64\Scripts;%WINDOWS_SDK_BIN%\x86;%WINDOWS_SDK_BIN%\x64

where cl
where cmake

copy /Y docs\backend\snapdragon\CMakeUserPresets.json . >nul
cmake --preset arm64-windows-snapdragon-release -B build-wos
if errorlevel 1 (echo CONFIGURE FAILED & exit /b 1)

cmake --build build-wos --config Release -j 18
if errorlevel 1 (echo BUILD FAILED & exit /b 1)

cmake --install build-wos --config Release --prefix ..\bin\hexagon
if errorlevel 1 (echo INSTALL FAILED & exit /b 1)

echo BUILD OK
