#!/bin/bash
# Saarthi CLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/snehangshu2002/saarthi-cli/main/install.sh | bash

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

detect_os() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "macos" ;;
        *)       echo "unknown" ;;
    esac
}

check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON="python3"
    elif command -v python &> /dev/null; then
        PYTHON="python"
    else
        error "Python 3.12+ is required. Install from https://python.org"
    fi

    VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo "$VERSION" | cut -d. -f1)
    MINOR=$(echo "$VERSION" | cut -d. -f2)

    if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 12 ]; }; then
        warn "Python 3.12+ recommended. Detected $VERSION — things may not work correctly."
    else
        info "Python $VERSION detected."
    fi
}

add_to_path_hint() {
    OS=$1
    if [ "$OS" = "macos" ]; then
        warn "Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
        warn "Then run: source ~/.zshrc  (or ~/.bash_profile)"
    else
        warn "Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
        warn "Then run: source ~/.bashrc"
    fi
}

install_saarthi() {
    OS=$(detect_os)
    info "Detected OS: $OS"

    # Prefer uv tool install (cleanest for CLI tools)
    if command -v uv &> /dev/null; then
        info "Using uv..."
        uv tool install saarthi-cli
        info "Done! Run 'saarthi' to start."
        return
    fi

    # Fall back to pip --user
    if $PYTHON -m pip --version &> /dev/null 2>&1; then
        info "Using pip..."
        $PYTHON -m pip install --user saarthi-cli

        if command -v saarthi &> /dev/null; then
            info "Done! Run 'saarthi' to start."
        else
            warn "'saarthi' not found in PATH."
            add_to_path_hint "$OS"
        fi
        return
    fi

    error "Neither uv nor pip found. Install one and retry."
}

main() {
    info "Installing Saarthi CLI..."
    check_python
    install_saarthi
    info "Installation complete!"
}

main "$@"
