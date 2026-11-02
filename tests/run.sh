#!/bin/sh
# Compile every header for both targets, in C and C++, and check record
# sizes. CLANG defaults to clang on the PATH.
set -e
cd "$(dirname "$0")/.."
CLANG=${CLANG:-clang}
for t in m68k-apple-macos powerpc-apple-macos9; do
  $CLANG --target=$t -fsyntax-only -Wall -Werror -Iinclude tests/all.c
  $CLANG --target=$t -fsyntax-only -Iinclude tests/sizes.c
  $CLANG --target=$t -x c++ -std=c++17 -fsyntax-only -Werror -Iinclude tests/all.c
  $CLANG --target=$t -O2 -Wall -Werror -Iinclude -c examples/hello.c -o /dev/null
  echo "$t: ok"
done
