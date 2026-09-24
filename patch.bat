@echo off
chcp 65001 >nul
title WHartTest Docker Hot Patch Tool
setlocal enabledelayedexpansion

:: =========================================================
:: WHartTest Docker Patch Script
:: =========================================================
:: Description: Hot-patch source code into running Docker containers
:: without rebuilding images. Supports backend (Django), frontend
:: (Vue) and MCP full updates. Runs all patches by default on
:: every invocation.
:: =========================================================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

:: ---------- Configuration (modify as needed) ----------
set BACKEND_CONTAINER=wharttest-backend
set FRONTEND_CONTAINER=wharttest-frontend
set MCP_CONTAINER=wharttest-mcp
set DJANGO_SRC=WHartTest_Django
set VUE_SRC=WHartTest_Vue
set MCP_SRC=WHartTest_MCP
:: -------------------------------------------------------

:: ---------- Optional help ----------
if "%~1"=="-h" goto :show_help
if "%~1"=="--help" goto :show_help

:: =========================================================
:: Pre-flight checks
:: =========================================================
:pre_checks

echo ========================================
echo  WHartTest Docker Hot Patch Tool
echo ========================================
echo.

:: Check Docker availability
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] docker command not found. Please ensure Docker Desktop is installed and running.
    exit /b 1
)

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker daemon is not running. Please start Docker Desktop.
    exit /b 1
)

echo.

call :check_dirs_backend
if !ERRORLEVEL! neq 0 exit /b 1
call :check_dirs_frontend
if !ERRORLEVEL! neq 0 exit /b 1
call :check_dirs_mcp
if !ERRORLEVEL! neq 0 exit /b 1

:: =========================================================
:: Main workflow (patch all by default)
:: =========================================================

echo [Backend] ^>^>^> Updating backend code ...
call :patch_backend_full
if !ERRORLEVEL! neq 0 (
    echo [Backend] [FAILED] Backend update failed
    exit /b 1
)
echo [Backend] [DONE] Backend code updated successfully
echo.

echo [Frontend] ^>^>^> Updating frontend code ...
call :patch_frontend
if !ERRORLEVEL! neq 0 (
    echo [Frontend] [FAILED] Frontend update failed
    exit /b 1
)
echo [Frontend] [DONE] Frontend code updated successfully
echo.

echo [MCP] ^>^>^> Updating MCP code ...
call :patch_mcp
if !ERRORLEVEL! neq 0 (
    echo [MCP] [FAILED] MCP update failed
    exit /b 1
)
echo [MCP] [DONE] MCP code updated successfully
echo.

:: Restart services
echo [Restart] Restarting container services ...
call :restart_backend
call :restart_frontend
call :restart_mcp

echo.
echo ========================================
echo  All operations completed!
echo ========================================
goto :eof


:: =========================================================
:: Helper functions
:: =========================================================

:check_dirs_backend
    if not exist "%DJANGO_SRC%\manage.py" (
        echo [ERROR] %DJANGO_SRC%\manage.py not found
        echo         Run this script from the WHartTest repository root
        exit /b 1
    )
    docker inspect %BACKEND_CONTAINER% >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Container %BACKEND_CONTAINER% is not running
        echo         Please start the Docker container: docker compose up -d backend
        exit /b 1
    )
    echo [Backend] Container: %BACKEND_CONTAINER%
    echo [Backend] Source: %CD%\%DJANGO_SRC%
    exit /b 0

:check_dirs_frontend
    if not exist "%VUE_SRC%\package.json" (
        echo [ERROR] %VUE_SRC%\package.json not found
        exit /b 1
    )
    if not exist "%VUE_SRC%\vite.config.ts" (
        echo [ERROR] %VUE_SRC%\vite.config.ts not found
        exit /b 1
    )
    docker inspect %FRONTEND_CONTAINER% >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Container %FRONTEND_CONTAINER% is not running
        echo         Please start the Docker container: docker compose up -d frontend
        exit /b 1
    )
    echo [Frontend] Container: %FRONTEND_CONTAINER%
    echo [Frontend] Source: %CD%\%VUE_SRC%
    exit /b 0

:check_dirs_mcp
    if not exist "%MCP_SRC%\ms_mcp_api.py" (
        echo [ERROR] %MCP_SRC%\ms_mcp_api.py not found
        echo         Run this script from the WHartTest repository root
        exit /b 1
    )
    if not exist "%MCP_SRC%\WHartTest_tools.py" (
        echo [ERROR] %MCP_SRC%\WHartTest_tools.py not found
        exit /b 1
    )
    docker inspect %MCP_CONTAINER% >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Container %MCP_CONTAINER% is not running
        echo         Please start the Docker container: docker compose up -d mcp
        exit /b 1
    )
    echo [MCP] Container: %MCP_CONTAINER%
    echo [MCP] Source: %CD%\%MCP_SRC%
    exit /b 0


:: =========================================================
:: Backend patch - Full mode
:: Copy all source directories into the container
:: =========================================================
:patch_backend_full

    echo [Backend] Copying all Python source to container ...
    setlocal enabledelayedexpansion

    :: manage.py
    docker cp "%DJANGO_SRC%\manage.py" "%BACKEND_CONTAINER%:/app/" >nul 2>&1

    :: All Django app directories
    for %%d in (
        accounts api_database_configs api_environments api_functions
        api_interfaces api_keys api_modules api_sync api_testcases
        api_testtasks httprunner knowledge langgraph_integration
        mcp_tools operation_logs orchestrator_integration projects
        prompts requirements skills task_center ui_automation
        weixin_integration testcase_templates testcases wharttest_django
        file_management client_certificates
    ) do (
        if exist "%DJANGO_SRC%\%%d" (
            docker cp "%DJANGO_SRC%\%%d\." "%BACKEND_CONTAINER%:/app/%%d/" >nul 2>&1
            if !errorlevel! equ 0 (
                echo    - %%d/  OK
            ) else (
                echo    - %%d/  SKIP (no changes)
            )
        )
    )

    endlocal
    exit /b 0


:: =========================================================
:: Frontend patch - Build and copy
:: =========================================================
:patch_frontend

    :: Check Node.js availability
    where node >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Node.js not found locally
        exit /b 1
    )

    :: Check npm version
    for /f "tokens=1 delims= " %%a in ('node -v') do set NODE_VER=%%a
    for /f "tokens=1 delims= " %%a in ('npm -v') do set NPM_VER=%%a
    echo [Frontend] Node: %NODE_VER%  npm: %NPM_VER%

    :: Enter Vue project directory
    pushd "%VUE_SRC%"

    :: Install node_modules if missing
    if not exist "node_modules" (
        echo [Frontend] Installing dependencies with npm ci  ...
        call npm ci
        if !errorlevel! neq 0 (
            echo [ERROR] npm ci failed
            popd
            exit /b 1
        )
    )

    :: Force clean rebuild
    echo [Frontend] Forcing clean rebuild ...
    if exist "node_modules\.vite" rmdir /s /q "node_modules\.vite" >nul 2>&1
    if exist "dist" rmdir /s /q "dist" >nul 2>&1

    call npm run build
    if !errorlevel! neq 0 (
        echo [ERROR] Frontend build failed. Please check for code errors.
        popd
        exit /b 1
    )

    popd

    :: Copy dist to frontend container
    echo [Frontend] Copying build artifacts to container (%FRONTEND_CONTAINER%) ...

    docker exec %FRONTEND_CONTAINER% sh -c "rm -rf /usr/share/nginx/html/*" >nul 2>&1
    docker cp "%VUE_SRC%\dist\." "%FRONTEND_CONTAINER%:/usr/share/nginx/html/" >nul 2>&1

    if !errorlevel! equ 0 (
        echo [Frontend] Copy complete
    ) else (
        echo [ERROR] Failed to copy to container
        exit /b 1
    )

    exit /b 0


:: =========================================================
:: MCP patch - Copy source files into the container
:: =========================================================
:patch_mcp

    echo [MCP] Copying source files to container (%MCP_CONTAINER%) ...
    docker cp "%MCP_SRC%\ms_mcp_api.py" "%MCP_CONTAINER%:/app/" >nul 2>&1
    docker cp "%MCP_SRC%\WHartTest_tools.py" "%MCP_CONTAINER%:/app/" >nul 2>&1
    docker cp "%MCP_SRC%\playwright-mcp-config.json" "%MCP_CONTAINER%:/app/" >nul 2>&1
    echo [MCP] Source files copied
    exit /b 0


:: =========================================================
:: Restart backend services (supervisor-managed processes)
:: =========================================================
:restart_backend

    echo [Restart] Restarting Django (uvicorn) ...
    docker exec %BACKEND_CONTAINER% supervisorctl restart django >nul 2>&1

    echo [Restart] Restarting Celery Worker ...
    docker exec %BACKEND_CONTAINER% supervisorctl restart celery_worker >nul 2>&1

    docker restart %BACKEND_CONTAINER% >nul 2>&1
    echo [Backend] Services restarted
    exit /b 0


:: =========================================================
:: Restart frontend service (nginx reload)
:: =========================================================
:restart_frontend

    echo [Restart] Reloading Nginx ...
    docker exec %FRONTEND_CONTAINER% nginx -s reload >nul 2>&1
    if !errorlevel! equ 0 (
        echo [Frontend] Nginx reloaded
    ) else (
        :: nginx -s reload may fail on first start; ignore
        echo [Frontend] Nginx reload skipped (usually not needed)
    )
    docker restart %FRONTEND_CONTAINER% >nul 2>&1
    exit /b 0


:: =========================================================
:: Restart MCP services (supervisor-managed processes)
:: =========================================================
:restart_mcp

    echo [Restart] Restarting MCP services (supervisor) ...
    docker exec %MCP_CONTAINER% supervisorctl restart ms_mcp_api >nul 2>&1
    docker exec %MCP_CONTAINER% supervisorctl restart wharttest_tools >nul 2>&1

    docker restart %MCP_CONTAINER% >nul 2>&1
    echo [MCP] Services restarted
    exit /b 0


:: =========================================================
:: Help
:: =========================================================
:show_help
    echo Usage: patch.bat [options]
    echo.
    echo Description:
    echo   Hot-patch backend (Django), frontend (Vue) and MCP source code
    echo   into the running Docker containers, then restart their services.
    echo   All three patches run by default on every invocation.
    echo.
    echo Options:
    echo   -h, --help        Show this help
    echo.
    echo Prerequisites:
    echo   - Docker Desktop is running
    echo   - Target containers are started (docker compose up -d)
    echo   - Frontend update requires Node.js
    echo.
    goto :eof
