#!/usr/bin/env bash
# =========================================================
# WHartTest Docker Patch Script (Linux/macOS)
# =========================================================
# Description: Hot-patch source code into running Docker containers
# without rebuilding images. Supports backend (Django) and
# frontend (Vue) full updates.
# =========================================================

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# ---------- Configuration (modify as needed) ----------
BACKEND_CONTAINER=wharttest-backend
FRONTEND_CONTAINER=wharttest-frontend
DJANGO_SRC=WHartTest_Django
VUE_SRC=WHartTest_Vue
# -------------------------------------------------------

DO_BACKEND=0
DO_FRONTEND=0

# =========================================================
# Parse command-line arguments
# =========================================================
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -b|--backend)  DO_BACKEND=1  ; shift ;;
            -f|--frontend) DO_FRONTEND=1 ; shift ;;
            -a|--all)      DO_BACKEND=1; DO_FRONTEND=1 ; shift ;;
            -h|--help)     show_help; exit 0 ;;
            *) echo "[ERROR] Unknown argument: $1" ; exit 1 ;;
        esac
    done
}

parse_args "$@"

# Default: update both if nothing specified
if [ "$DO_BACKEND" -eq 0 ] && [ "$DO_FRONTEND" -eq 0 ]; then
    DO_BACKEND=1
    DO_FRONTEND=1
fi

# =========================================================
# Pre-flight checks
# =========================================================
pre_checks() {
    echo "========================================"
    echo " WHartTest Docker Hot Patch Tool"
    echo "========================================"
    echo ""

    # Check Docker availability
    if ! command -v docker &>/dev/null; then
        echo "[ERROR] docker command not found. Please ensure Docker is installed and running."
        exit 1
    fi

    if ! docker info &>/dev/null; then
        echo "[ERROR] Docker daemon is not running. Please start Docker."
        exit 1
    fi

    echo ""

    if [ "$DO_BACKEND" -eq 1 ]; then
        check_dirs_backend || exit 1
    fi
    if [ "$DO_FRONTEND" -eq 1 ]; then
        check_dirs_frontend || exit 1
    fi
}

# =========================================================
# Helper functions
# =========================================================

check_dirs_backend() {
    if [ ! -f "$DJANGO_SRC/manage.py" ]; then
        echo "[ERROR] $DJANGO_SRC/manage.py not found"
        echo "         Run this script from the WHartTest repository root"
        return 1
    fi
    if ! docker inspect "$BACKEND_CONTAINER" &>/dev/null; then
        echo "[ERROR] Container $BACKEND_CONTAINER is not running"
        echo "         Please start the Docker container: docker compose up -d backend"
        return 1
    fi
    echo "[Backend] Container: $BACKEND_CONTAINER"
    echo "[Backend] Source:    $PWD/$DJANGO_SRC"
    return 0
}

check_dirs_frontend() {
    if [ ! -f "$VUE_SRC/package.json" ]; then
        echo "[ERROR] $VUE_SRC/package.json not found"
        return 1
    fi
    if [ ! -f "$VUE_SRC/vite.config.ts" ]; then
        echo "[ERROR] $VUE_SRC/vite.config.ts not found"
        return 1
    fi
    if ! docker inspect "$FRONTEND_CONTAINER" &>/dev/null; then
        echo "[ERROR] Container $FRONTEND_CONTAINER is not running"
        echo "         Please start the Docker container: docker compose up -d frontend"
        return 1
    fi
    echo "[Frontend] Container: $FRONTEND_CONTAINER"
    echo "[Frontend] Source:    $PWD/$VUE_SRC"
    return 0
}

# =========================================================
# Backend patch - Full mode
# Copy all source directories into the container
# =========================================================
patch_backend_full() {
    echo "[Backend] Copying all Python source to container ..."

    # manage.py
    docker cp "$DJANGO_SRC/manage.py" "$BACKEND_CONTAINER:/app/" &>/dev/null

    # All Django app directories
    for d in \
        accounts api_database_configs api_environments api_functions \
        api_interfaces api_keys api_modules api_sync api_testcases \
        api_testtasks httprunner knowledge langgraph_integration \
        mcp_tools operation_logs orchestrator_integration projects \
        prompts requirements skills task_center ui_automation \
        weixin_integration testcase_templates testcases wharttest_django
    do
        if [ -d "$DJANGO_SRC/$d" ]; then
            docker cp "$DJANGO_SRC/$d/." "$BACKEND_CONTAINER:/app/$d/" &>/dev/null
            rc=$?
            if [ $rc -eq 0 ]; then
                echo "   - $d/  OK"
            else
                echo "   - $d/  SKIP (no changes)"
            fi
        fi
    done

    return 0
}

# =========================================================
# Frontend patch - Build and copy
# =========================================================
patch_frontend() {
    # Check Node.js availability
    if ! command -v node &>/dev/null; then
        echo "[ERROR] Node.js not found locally"
        return 1
    fi

    NODE_VER=$(node -v)
    NPM_VER=$(npm -v)
    echo "[Frontend] Node: $NODE_VER  npm: $NPM_VER"

    # Enter Vue project directory
    pushd "$VUE_SRC" >/dev/null || return 1

    # Install node_modules if missing
    if [ ! -d "node_modules" ]; then
        echo "[Frontend] Installing dependencies with npm ci ..."
        if ! npm ci; then
            echo "[ERROR] npm ci failed"
            popd >/dev/null || return 1
            return 1
        fi
    fi

    # Force clean rebuild
    echo "[Frontend] Forcing clean rebuild ..."
    rm -rf "node_modules/.vite" "dist"

    if ! npm run build; then
        echo "[ERROR] Frontend build failed. Please check for code errors."
        popd >/dev/null || return 1
        return 1
    fi

    popd >/dev/null || return 1

    # Copy dist to frontend container
    echo "[Frontend] Copying build artifacts to container ($FRONTEND_CONTAINER) ..."

    docker exec "$FRONTEND_CONTAINER" sh -c "rm -rf /usr/share/nginx/html/*" &>/dev/null
    docker cp "$VUE_SRC/dist/." "$FRONTEND_CONTAINER:/usr/share/nginx/html/" &>/dev/null

    rc=$?
    if [ $rc -eq 0 ]; then
        echo "[Frontend] Copy complete"
    else
        echo "[ERROR] Failed to copy to container"
        return 1
    fi

    return 0
}

# =========================================================
# Restart backend services (supervisor-managed processes)
# =========================================================
restart_backend() {
    echo "[Restart] Restarting Django (uvicorn) ..."
    docker exec "$BACKEND_CONTAINER" supervisorctl restart django &>/dev/null

    echo "[Restart] Restarting Celery Worker ..."
    docker exec "$BACKEND_CONTAINER" supervisorctl restart celery_worker &>/dev/null

    docker restart "$BACKEND_CONTAINER" &>/dev/null
    echo "[Backend] Services restarted"
    return 0
}

# =========================================================
# Restart frontend service (nginx reload)
# =========================================================
restart_frontend() {
    echo "[Restart] Reloading Nginx ..."
    docker exec "$FRONTEND_CONTAINER" nginx -s reload &>/dev/null
    rc=$?
    if [ $rc -eq 0 ]; then
        echo "[Frontend] Nginx reloaded"
    else
        # nginx -s reload may fail on first start; ignore
        echo "[Frontend] Nginx reload skipped (usually not needed)"
    fi
    docker restart "$FRONTEND_CONTAINER" &>/dev/null
    return 0
}

# =========================================================
# Help
# =========================================================
show_help() {
    cat <<EOF
Usage: $0 [options]

Options:
  -b, --backend     Update backend only (Django)
  -f, --frontend    Update frontend only (Vue)
  -a, --all         Update both backend and frontend (default)
  -h, --help        Show this help

Examples:
  $0                    Update both (full mode)
  $0 -b                 Update backend only
  $0 -f                 Update frontend only

Prerequisites:
  - Docker is installed and running
  - Target containers are started (docker compose up -d)
  - Frontend update requires Node.js
EOF
}

# =========================================================
# Main workflow
# =========================================================

pre_checks

if [ "$DO_BACKEND" -eq 1 ]; then
    echo "[Backend] >>> Updating backend code ..."
    if ! patch_backend_full; then
        echo "[Backend] [FAILED] Backend update failed"
        exit 1
    fi
    echo "[Backend] [DONE] Backend code updated successfully"
    echo ""
fi

if [ "$DO_FRONTEND" -eq 1 ]; then
    echo "[Frontend] >>> Updating frontend code ..."
    if ! patch_frontend; then
        echo "[Frontend] [FAILED] Frontend update failed"
        exit 1
    fi
    echo "[Frontend] [DONE] Frontend code updated successfully"
    echo ""
fi

# Restart services
echo "[Restart] Restarting container services ..."
[ "$DO_BACKEND" -eq 1 ] && restart_backend
[ "$DO_FRONTEND" -eq 1 ] && restart_frontend

echo ""
echo "========================================"
echo " All operations completed!"
echo "========================================"
