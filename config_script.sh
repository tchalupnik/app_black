#!/bin/bash

# Script downloads YAML files from boneIO-eu/app_black for selected kind of board (eg. 24x16)
# and copies them to ~/boneio/ directory, overwriting existing files.

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <size> (np. $0 24x16)"
  exit 1
fi

SIZE="$1"
DEST_DIR="$HOME/boneio"

TMP_DIR=$(mktemp -d)

curl -fsSL "https://github.com/boneIO-eu/app_black/archive/refs/heads/dev.zip" -o "$TMP_DIR/app_black.zip"

unzip -q "$TMP_DIR/app_black.zip" -d "$TMP_DIR"

SRC_DIR="$TMP_DIR/app_black-main/boneio/example_config/$SIZE"

if [ ! -d "$SRC_DIR" ]; then
  echo "No such config: $SIZE"
  rm -rf "$TMP_DIR"
  exit 2
fi

mkdir -p "$DEST_DIR"
cp -vf "$SRC_DIR"/*.yaml "$DEST_DIR/"

rm -rf "$TMP_DIR"

echo "YAML files for $SIZE have been downloaded to $DEST_DIR"