#!/bin/sh
# Compile every header for both targets, in C and C++, and check record
# sizes (tests/sizes.c, and every size given in defs/), and check the
# argument-block calls against the ROM. CLANG defaults to clang on the PATH.
set -e
cd "$(dirname "$0")/.."
CLANG=${CLANG:-clang}
SIZES=$(mktemp "${TMPDIR:-/tmp}/defsizes.XXXXXX")
python3 tests/defsizes.py > "$SIZES"
INLINES=$(mktemp "${TMPDIR:-/tmp}/inlines.XXXXXX")
BLOCKS=$(mktemp "${TMPDIR:-/tmp}/blocks.XXXXXX")
trap 'rm -f "$SIZES" "$INLINES" "$BLOCKS"' EXIT
python3 tests/inlines.py > "$INLINES"
$CLANG --target=m68k-apple-macos -O1 -Iinclude -x c -c "$INLINES" -o /dev/null
# Argument-block calls against the ROM's glue (data/blockinfo.json).
python3 tests/blocks.py > "$BLOCKS"
$CLANG --target=m68k-apple-macos -Wall -Werror -Wno-unused-function -Iinclude -x c -fsyntax-only "$BLOCKS"
for t in m68k-apple-macos powerpc-apple-macos9; do
  $CLANG --target=$t -fsyntax-only -Wall -Werror -Iinclude tests/all.c
  $CLANG --target=$t -fsyntax-only -Iinclude tests/sizes.c
  $CLANG --target=$t -fsyntax-only -Iinclude -x c "$SIZES"
  $CLANG --target=$t -x c++ -std=c++17 -fsyntax-only -Werror -Iinclude tests/all.c
  $CLANG --target=$t -O2 -Wall -Werror -Iinclude -c examples/hello.c -o /dev/null
  echo "$t: ok"
done
