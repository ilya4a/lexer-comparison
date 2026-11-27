#!/bin/sh
set -eu

cd "$(dirname "$0")"
mkdir -p build/generated
flex -8 -Cf -o build/generated/scanner_flex.c flex/scanner.l
re2c -o build/generated/scanner_re2c.c re2c/scanner.re

cmake -S . -B build
cmake --build build
