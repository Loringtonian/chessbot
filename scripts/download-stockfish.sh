#!/bin/bash
# Download Stockfish binary for the current platform

set -e

VERSION="17"
BASE_URL="https://github.com/official-stockfish/Stockfish/releases/download/sf_${VERSION}"
DEST_DIR="$(dirname "$0")/../backend/engines/stockfish"

# Detect platform
PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

echo "Detecting platform: $PLATFORM / $ARCH"

# Determine download URL and directory name
case "$PLATFORM" in
    darwin)
        if [ "$ARCH" = "arm64" ]; then
            ARCHIVE_NAME="stockfish-macos-arm64.tar"
            DIR_NAME="stockfish-macos-arm64"
        else
            ARCHIVE_NAME="stockfish-macos-x86-64.tar"
            DIR_NAME="stockfish-macos-x86-64"
        fi
        ;;
    linux)
        if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            # Note: Official releases may not have ARM Linux, fallback to x86-64
            ARCHIVE_NAME="stockfish-ubuntu-x86-64.tar"
            DIR_NAME="stockfish-linux-x86-64"
        else
            ARCHIVE_NAME="stockfish-ubuntu-x86-64.tar"
            DIR_NAME="stockfish-linux-x86-64"
        fi
        ;;
    *)
        echo "Unsupported platform: $PLATFORM"
        echo "Please download Stockfish manually from https://stockfishchess.org/download/"
        exit 1
        ;;
esac

DOWNLOAD_URL="${BASE_URL}/${ARCHIVE_NAME}"

echo "Creating destination directory: $DEST_DIR"
mkdir -p "$DEST_DIR"

echo "Downloading Stockfish from: $DOWNLOAD_URL"
cd "$DEST_DIR"

# Download and extract
curl -L -o stockfish.tar "$DOWNLOAD_URL"
tar -xf stockfish.tar
rm stockfish.tar

# Rename extracted directory to match our naming convention
EXTRACTED_DIR=$(ls -d stockfish-* 2>/dev/null | head -n1)
if [ -n "$EXTRACTED_DIR" ] && [ "$EXTRACTED_DIR" != "$DIR_NAME" ]; then
    # The tarball extracts to a directory like "stockfish"
    # We need to find the binary inside
    if [ -d "$EXTRACTED_DIR" ]; then
        echo "Found extracted directory: $EXTRACTED_DIR"
    fi
fi

# Make binary executable
find . -name "stockfish*" -type f ! -name "*.tar" -exec chmod +x {} \;

echo ""
echo "Stockfish installed successfully!"
echo "Binary location: $DEST_DIR"
ls -la "$DEST_DIR"
