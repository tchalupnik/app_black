#!/bin/bash

# Script downloads YAML files from boneIO-eu/app_black for selected kind of board (eg. 24x16)
# and copies them to ~/boneio/ directory, overwriting existing files.

## USAGE: curl -fsSL https://raw.githubusercontent.com/boneIO-eu/app_black/refs/heads/dev/config_script.sh | bash -s -- 24x16

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <size> (e.g. $0 24x16)"
  exit 1
fi

SIZE="$1"
DEST_DIR="$HOME/boneio"
TMP_DIR=$(mktemp -d)

# Sposób 1: git clone (najprostszy i najszybszy)
git clone --depth 1 --branch dev https://github.com/boneIO-eu/app_black.git "$TMP_DIR/app_black"

SRC_DIR="$TMP_DIR/app_black/boneio/example_config/$SIZE"

if [ ! -d "$SRC_DIR" ]; then
  echo "No such config: $SIZE"
  rm -rf "$TMP_DIR"
  exit 2
fi

mkdir -p "$DEST_DIR"
cp -vf "$SRC_DIR"/*.yaml "$DEST_DIR/"

rm -rf "$TMP_DIR"

echo "YAML files for $SIZE have been downloaded to $DEST_DIR"
