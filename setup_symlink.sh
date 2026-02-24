#!/bin/bash
# Setup script to recreate symlink after cloning the repository
# Run this script after cloning: ./setup_symlink.sh

echo "Setting up symlink for mcp_tools..."

SYMLINK_PATH="godcomet/backend/mcp_tools"
TARGET_PATH="../../mcp-automation/src/tools"

# Check if symlink already exists
if [ -L "$SYMLINK_PATH" ]; then
    echo "Symlink already exists at $SYMLINK_PATH"
    exit 0
fi

# Remove if it's a file or directory
if [ -e "$SYMLINK_PATH" ]; then
    echo "Removing existing file/directory at $SYMLINK_PATH"
    rm -rf "$SYMLINK_PATH"
fi

# Check if target exists
FULL_TARGET=$(cd "$(dirname "$SYMLINK_PATH")" && pwd)/$TARGET_PATH
if [ ! -d "$(dirname "$SYMLINK_PATH")/$TARGET_PATH" ]; then
    echo "ERROR: Target path does not exist: $TARGET_PATH"
    echo "Make sure you're in the root of the GodComet repository"
    exit 1
fi

# Create the symlink
ln -s "$TARGET_PATH" "$SYMLINK_PATH"

if [ $? -eq 0 ]; then
    echo "✅ Symlink created successfully!"
    echo "   $SYMLINK_PATH -> $TARGET_PATH"
else
    echo "❌ Failed to create symlink"
    exit 1
fi


