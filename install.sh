#!/bin/bash
# Saarthi CLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/snehangshu2002/saarthi-cli/main/install.sh | bash

set -e

REPO="snehangshu2002/saarthi-cli"
BINARY_NAME="saarthi"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

detect_os() {
    case "$(uname -s)" in
        Linux*)     echo "linux" ;;
        Darwin*)    echo "macos" ;;
        CYGWIN*|MINGW*|MSYS*)    echo "windows" ;;
        *)          echo "unknown" ;;
    esac
}

check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON="python3"
    elif command -v python &> /dev/null; then
        PYTHON="python"
    else
        error "Python 3.12+ is required. Please install from https://python.org"
    fi
    
    VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo $VERSION | cut -d. -f1)
    MINOR=$(echo $VERSION | cut -d. -f2)
    
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 12 ]); then
        warn "Python 3.12+ recommended. Detected $VERSION"
    fi
}

install_with_pip() {
    info "Installing saarthi-cli via pip..."
    
    if command -v uv &> /dev/null; then
        info "Using uv for installation..."
        uv pip install --system saarthi-cli
    elif $PYTHON -m pip --version &> /dev/null; then
        info "Using pip for installation..."
        $PYTHON -m pip install --user saarthi-cli
    else
        error "pip not found. Please install pip or uv."
    fi
    
    # Verify installation
    if command -v saarthi &> /dev/null; then
        info "Successfully installed saarthi-cli!"
        saarthi --version 2>/dev/null || info "Run 'saarthi' to start."
    else
        warn "saarthi installed but not found in PATH. Try: source ~/.bashrc or ~/.zshrc"
    fi
}

# Main installation flow
main() {
    info "Installing Saarthi CLI..."
    
    OS=$(detect_os)
    info "Detected OS: $OS"
    
    check_python
    install_with_pip
    
    info "Installation complete!"
    info "Run 'saarthi' to start the chatbot."
}

main "$@"