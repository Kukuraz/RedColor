@echo off
rem Сборка RedColor (Rust) в окружении Visual Studio 2022
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
set "MUPDF_MSBUILD=C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\amd64\MSBuild.exe"
set "MUPDF_MSVC_PLATFORM_TOOLSET=v143"
set "LIBCLANG_PATH=C:\Program Files\LLVM\bin"
cd /d "%~dp0"
cargo build --release -j 4 %*
