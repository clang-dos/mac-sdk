# mac-sdk

A redistributable SDK for classic Mac OS applications built with clang
(clang-dos/llvm): System 6 to Mac OS 9, on 68k and PowerPC.

## Headers

`include/` has the Toolbox headers. Include them the way Apple's
Universal Interfaces are included (`#include <Quickdraw.h>`,
`<Windows.h>`, `<Events.h>`, ...) or all at once with
`<Multiverse.h>`. The same headers work for both targets:

```sh
clang --target=m68k-apple-macos     -O2 -Iinclude -c hello.c   # 68k
clang --target=powerpc-apple-macos9 -O2 -Iinclude -c hello.c   # PowerPC
```

- On 68k, Toolbox calls are `pascal` functions whose calls become their
  trap words (`__attribute__((raw_inline(...)))`). Register-based traps
  (most OS traps, such as `NewPtr`, `Gestalt` and `Delay`) are inline
  functions that load the registers and emit the trap.
- On PowerPC, the calls are plain declarations that the linker imports
  from InterfaceLib and the other shared libraries.
- Records use 68k alignment on both CPUs, as on a real Mac, so they
  have the sizes Inside Macintosh gives (`tests/sizes.c` checks them).
- 32-bit types are `long`, as in Apple's headers, so existing code that
  passes `long *` compiles unchanged.

`examples/hello.c` uses them; built as a fat application it runs on
System 7.1 and 7.6.1 (68k) and Mac OS 8.1 (PowerPC). Its 68k build also
runs on a Mac Plus (in MAME) under Systems 2.0, 2.0.1, 5.0, 5.1, 6.0,
6.0.3, 6.0.4, 6.0.5 and 6.0.8. It checks that the Gestalt trap exists
before calling it, since Gestalt arrived in System 6.0.4; 6.0.8 reports
itself to Gestalt as 6.0.7.

### Mac OS 8

The Mac OS 8 Toolbox is declared too: the Appearance Manager
(`<Appearance.h>`), the Control Manager's embedding, keyboard focus and
control data calls with the Appearance control definitions
(`<Controls.h>`, `<ControlDefinitions.h>`), the Menu, Dialog and Window
Manager additions (menu command IDs, `MenuEvent`, `StandardAlert`,
`AutoSizeDialog`, window collapsing), the Collection Manager
(`<Collections.h>`) and the Contextual Menu Manager
(`<ContextualMenu.h>`).

- What Mac OS 8.0 and 8.1 ran on 68k Macs has its trap and selector,
  read from the 68k glue in 8.1's AppearanceLib and 9.2.1's
  CollectionsLib (`data/trapinfo-os8.json`). The Contextual Menu Manager
  is trap 0xAA72 with selectors 1 to 4, as the Contextual Menu Extension
  installs it.
- Mac OS 8.5 dropped 68k Macs, so its new calls (Appearance Manager 1.1,
  Window Manager 2.0's `CreateNewWindow`, window proxies and properties,
  the 32-bit control values, ...) are declared for PowerPC only. On 68k
  they are left out, so a call to one fails to compile.
- The bevel button, image well, tab and disclosure triangle accessors
  are inline calls to `GetControlData` and `SetControlData` on 68k.

`examples/appearance.c` draws with the theme, builds a hierarchy of
Appearance controls and uses a Collection and menu command IDs. Built
fat, it runs on Mac OS 8.1 on both a 68k Mac (QEMU's `q800`) and a
Power Mac (SheepShaver). Appearance 1.0.1 in 8.1 has no auto-toggling
check boxes or radio buttons (`kControlCheckBoxAutoToggleProc` draws
an ordinary check box), so the example toggles its check box itself.

### Mac OS 9

The calls new in Mac OS 8.5 to 9.2 are declared too: the HFS Plus API
(`FSRef`, Unicode names, forks, catalog iterators and bulk calls),
Icon Services, Folder Manager 9 (folder descriptors and routing), Power
Manager 2, Sound Manager 3.x (sound converters, output info), Display
Manager 2, anti-aliased text, the VM and resource-file additions, the
Thread Manager (`<Threads.h>`), Multiprocessing Services
(`<Multiprocessing.h>`), the Text Encoding and Unicode Converters
(`<TextCommon.h>`, `<TextEncodingConverter.h>`, `<UnicodeConverter.h>`),
URL Access (`<URLAccess.h>`) and the Keychain Manager (`<Keychain.h>`).

- Mac OS 9 still runs 68k applications in its emulator, and the
  PowerPC glue in 9.2.1's InterfaceLib and its other libraries still
  calls a 68k trap for many of these. Those calls have that trap and
  selector on 68k (`data/trapinfo-os9.json`; `tools/retrap.py` attaches
  them to definitions that had none). The high-level HFS Plus calls
  (`FSOpenFork`, `FSGetCatalogInfo`, ...) are inline glue that fills in
  a parameter block and calls the `PB...Sync` trap, as 9.2.1's glue
  does.
- The Thread Manager is trap 0xABF2 on 68k (System 7.5 and later, or
  the Thread Manager extension). Its callbacks are plain function
  pointers on PowerPC too, as in Apple's headers, not routine
  descriptors.
- Multiprocessing Services, the converters, URL Access and the Keychain
  live in PowerPC-only libraries, so they are declared for PowerPC
  only. On 68k a call to one fails to compile.

`examples/macos9.c` runs three cooperative threads, reads the System
Folder's Unicode name with `FSFindFolder` and `FSGetCatalogInfo`, plots
its icon with Icon Services and checks anti-aliased text on both CPUs,
and on PowerPC sums numbers in a preemptive MP task and converts Mac
Roman text to UTF-8 with the Text Encoding Converter. Built fat, it runs
on Mac OS 9.2.1 (QEMU's `mac99`) as PowerPC code, and its 68k build runs
there in the 68k emulator.

### QuickTime

`<Movies.h>`, `<ImageCompression.h>`, `<QuickTimeComponents.h>`,
`<MediaHandler.h>`, `<ImageCodec.h>` and `<MoviesFormat.h>` declare the
QuickTime 1.5 API: the Movie Toolbox, the Image Compression Manager, the
movie controller, sequence grabber, standard compression, video
digitizer, media handler and codec component calls (677 calls), with
QuickTime's own 68k code (`0xAAAA` for the Movie Toolbox, `0xAAA3` for
the Image Compression Manager, `_ComponentDispatch` for components). On
PowerPC they import from QuickTimeLib. Thirteen 1992 names were renamed
or became macros before QuickTimeLib shipped (`SetImageDescriptionExtension`,
`MCGetMovie`, `SCGetCompression`, ...); those link on 68k only.

`examples/quicktime.c` lists the installed compressors, draws 30 frames
in a GWorld, compresses them with the Animation compressor into a new
movie file, opens the file again and plays it in a loop under the
standard movie controller. Its 68k build runs on System 7.1 with
QuickTime 1.5 (QEMU's `q800`), and built fat it runs as PowerPC code on
Mac OS 9.2.1 with QuickTime 5.

### Old routine names

Code written before 1993 uses the original names (`GetCtlValue`,
`DisposPtr`, `GetDItem`, `SetCTitle`, `IUGetIntl`, `TextBox`, ...).
Compile with `-DOLDROUTINENAMES=1` and they map to the current ones, as
with Apple's interfaces; 92 names are covered.

### Where they come from

The headers are generated by `tools/gen-headers.py` from the API
definitions in `defs/`, which come from
[Multiversal Interfaces](https://github.com/autc04/multiversal)
(MIT license, `defs/COPYING.multiversal`). Those were derived from the
clean-room Executor project, not from Apple's headers, so they can be
redistributed freely. To regenerate after changing a definition:

```sh
pip install pyyaml
python3 tools/gen-headers.py
```

Since then the definitions have been extended here with the rest of
the documented Toolbox: the Component, Display, Text Services, Power,
Slot, SCSI, Cursor Device, MIDI, Dictionary and Data Access Managers,
the PPC Toolbox, AppleTalk (MPP, ATP, NBP, ZIP, ASP and AFP), Ethernet,
the Communications Toolbox (Connection, Terminal and File Transfer
Managers, the Communications Resource Manager and the CTB utilities),
the HFS Plus API and more.

The QuickTime definitions (`defs/QuickTime.yaml`, after the first 21
calls) are different: `tools/mpw2defs.py` generated them from Apple's
QuickTime 1.5 C interfaces on the Developer CD Series (1992). It parses
the headers with clang, so the records, constants and each call's
inline 68k code are what Apple's compiler saw, and writes them as
definitions; Apple's headers themselves are not in this repository.
Point the tool at your own copy to regenerate them:

```sh
CLANG=clang python3 tools/mpw2defs.py -I path/to/CIncludes -I path/to/QuickTime \
    -o defs/QuickTime.yaml ImageCompression.h Movies.h MoviesFormat.h \
    QuickTimeComponents.h MediaHandler.h ImageCodec.h
```

### Checked against a real ROM

The 68k trap words and selectors are checked against the Mac OS ROM.
A Power Macintosh ROM contains InterfaceLib, whose PowerPC glue calls
each 68k trap through the Mixed Mode Manager; that glue names the trap,
the selector and where each argument goes.

- `tools/trapinfo.py ROM > data/trapinfo.json` reads that glue (from a
  4 MB OldWorld ROM image, such as the Beige G3's) and records each
  call. The checked-in `data/trapinfo.json` came from the Beige G3 ROM.
- `tools/check-traps.py` compares every call in the headers with it.
  All 1,960 calls that the ROM and the Mac OS 8 and 9 libraries describe
  match.
- `tools/add-protos.py defs/X.yaml < protos.h` turns C prototypes into
  definitions, with the 68k details from `data/trapinfo.json`, and
  refuses a prototype whose argument sizes disagree with the ROM.
  `tools/add-types.py` does the same for records and constants.
- `tools/blockinfo.py ROM > data/blockinfo.json` does the same for the
  Communications Toolbox calls, which pass their arguments as a block
  (laid out like Pascal arguments under a selector word, with A0
  pointing at it) to `_CommToolboxDispatch`. It records the selector
  and each argument's offset and size; `tests/blocks.py` checks all 166
  such calls in the headers against it. It needs `llvm-mc` with the
  PowerPC target.
- `tools/check-mpw.py path/to/CIncludes [more dirs]` compares the 68k
  code of every call with the inline code in Apple's MPW C interfaces
  (the trap word, and the selector loaded before it, however it is
  loaded). Against MPW 3.2's interfaces (June 1992) and QuickTime 1.5's,
  all 2,105 calls both declare match; the 18 MPW calls it reports
  missing have C or glue equivalents here (the low-memory accessors,
  `Fix2X` and friends).
- `tools/coverage.py` writes [docs/coverage.md](docs/coverage.md).

Calls with no trap of their own get their 68k glue as inline C in the
headers (`m68k-body` in the definitions; `tools/set-body.py` adds it).
The AppleTalk calls set the driver and control code and call PBControl,
as the ROM's PowerPC glue does; the high-level File Manager, Device
Manager and serial calls fill in a parameter block; the lowercase
C-string calls (`fsopen`, `getwtitle`, ...) convert their strings and
call the Pascal routine. The glue avoids `memcpy`, `memset` and 32-bit
multiplies, since there is no 68k runtime library yet (BlockMoveData
copies instead). `include/needs-glue.txt` lists what is left: mostly
calls that never ran on 68k (Navigation Services, Driver Services, the
Name Registry).

## Tests

```sh
CLANG=path/to/clang tests/run.sh
```

It compiles every header for both targets in C and C++, generates code
for every 68k inline function, checks the size of every record whose
definition gives one, checks the argument-block calls against the ROM,
and builds the examples.

## Not done yet

- Coverage: the headers declare all but 3 undocumented symbols of what
  the ROM's InterfaceLib exports (see docs/coverage.md).
- 68k glue for the rest of `needs-glue.txt` that did run on 68k (the
  Fixed/extended conversions, the 64-bit Wide math, TESetWordBreak and TESetClickLoop, which need a register
  trampoline), and a runtime library (`__udivsi3`, `memcpy` and the
  other helpers clang calls on 68k).
- The linkers and tools, which are still in clang-dos/dos-sdk under
  `classicmac/`.

## License

BSD 3-Clause (`LICENSE`), except `defs/`, which is MIT
(`defs/COPYING.multiversal`).
