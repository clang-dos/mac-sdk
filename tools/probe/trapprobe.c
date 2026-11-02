/* Records which traps, packages and Gestalt selectors the running System
   provides, in a file "Trap Probe" next to the application, and shows a
   summary. tools/availability.py reads the files. Runs on every ROM from
   the Mac 128K's 64K ROM on, and on PowerPC.

   File layout (big-endian):
     'TRP2', ROM85 (2), ROM version (2), SysVersion (2), CPU (1), pad (1)
     OS table: 256 bytes, toolbox table: 1024 bytes
       (0 unimplemented, 1 implemented, 2 no such entry on this ROM)
     PACK 0-15 present: 16 bytes
     count (2), then count x { selector (4), error (2), response (4) }
     'ADDR', then the address of every OS (256) and Toolbox (1024) entry
       (4 bytes each, 0 where the ROM has no such entry) */
#include <Quickdraw.h>
#include <Fonts.h>
#include <Windows.h>
#include <Menus.h>
#include <TextEdit.h>
#include <Dialogs.h>
#include <Events.h>
#include <Memory.h>
#include <Files.h>
#include <Resources.h>
#include <OSUtils.h>
#include <Gestalt.h>

QDGlobals qd;

static unsigned char buf[8192];
static unsigned long osaddr[256], tbaddr[1024];
static int len;

static void Put1(int v) { buf[len++] = v; }
static void Put2(int v) { Put1(v >> 8); Put1(v); }
static void Put4(long v) { Put2(v >> 16); Put2(v); }

static const OSType kSelectors[] = {
    'sysv', 'mach', 'proc', 'fpu ', 'mmu ', 'qd  ', 'rom ', 'romv', 'ram ',
    'lram', 'vm  ', 'addr', 'fs  ', 'alis', 'evnt', 'ppc ', 'help', 'edtn',
    'fold', 'cpnt', 'qtim', 'snd ', 'sm  ', 'tmgr', 'os  ', 'kbd ', 'dict',
    'drag', 'appr', 'menu', 'cntl', 'wind', 'dlgx', 'thds', 'mpsc', 'cfrg',
    'icmp', 'ttsc', 'tsmv', 'nlup', 'font', 'qdtx', 'ctbv', 'cmtb', 'atlk',
    'mtcp', 'scsi', 'sysa', 'sysu', 'hfs+', 'nav ', 'cmnu', 'kcmr', 'icon',
};

static char gLine[4][64];

static char *Hex(char *p, unsigned long n, int digits) {
  for (int sh = digits * 4 - 4; sh >= 0; sh -= 4)
    *p++ = "0123456789ABCDEF"[(n >> sh) & 15];
  return p;
}

static char *Put(char *p, const char *s) {
  while (*s) *p++ = *s++;
  return p;
}

static void ShowLine(int i, char *end) {
  *end = 0;
  MoveTo(16, 24 + 18 * i);
  Str255 s;
  int n = 0;
  while (gLine[i][n]) { s[n + 1] = gLine[i][n]; ++n; }
  s[0] = n;
  DrawString(s);
}

static OSErr WriteResults(short vref) {
  OSErr err = Create("\pTrap Probe", vref, 'MPS ', 'TEXT');
  short ref = 0;
  if (err == noErr || err == dupFNErr) err = FSOpen("\pTrap Probe", vref, &ref);
  if (err == noErr) {
    long count = len;
    err = SetEOF(ref, 0);
    if (!err) err = FSWrite(ref, &count, buf);
    FSClose(ref);
    FlushVol(nil, vref);
  }
  return err;
}

int main(void) {
  InitGraf(&qd.thePort);
  InitFonts();
  FlushEvents(everyEvent, 0);
  InitWindows();
  InitMenus();
  TEInit();
  InitDialogs(nil);
  InitCursor();

  short rom85 = 0, romv = 0, sysv = 0;
  unsigned char cpu = 0xFF;
#if TARGET_CPU_68K
  rom85 = LMGetROM85();
  romv = *(short *)(*(long *)0x2AE + 8);   /* ROMBase + 8 */
  sysv = *(short *)0x15A;                  /* SysVersion, 0 before System 4.1 */
  cpu = rom85 < 0 ? 0 : *(unsigned char *)0x12F;   /* CPUFlag */
#endif
  Put4('TRP2');
  Put2(rom85);
  Put2(romv);
  Put2(sysv);
  Put1(cpu);
  Put1(0);

  int nos = 0, ntb = 0;
#if TARGET_CPU_68K
  if (rom85 < 0) {
    /* The 64K ROM: one table of 512 entries. OS traps use entries
       0-0x4F and Toolbox traps A850-A9FF use 0x50-0x1FF. */
    ProcPtr unimp = GetTrapAddress(0x9F);
    for (int i = 0; i < 256; ++i) {
      if (i < 0x50) osaddr[i] = (unsigned long)GetTrapAddress(i);
      int v = i < 0x50 ? GetTrapAddress(i) != unimp : 2;
      nos += v == 1;
      Put1(v);
    }
    for (int i = 0; i < 1024; ++i) {
      if (i >= 0x50 && i < 0x200) tbaddr[i] = (unsigned long)GetTrapAddress(i);
      int v = i >= 0x50 && i < 0x200 ? GetTrapAddress(i) != unimp : 2;
      ntb += v == 1;
      Put1(v);
    }
  } else
#endif
  {
    ProcPtr unimp = NGetTrapAddress(0xA89F, kToolboxTrapType);
    /* With a 0x200-entry Toolbox table the upper half repeats the lower. */
    int tbsize = NGetTrapAddress(0xA86E, kToolboxTrapType) ==
                         NGetTrapAddress(0xAA6E, kToolboxTrapType)
                     ? 0x200
                     : 0x400;
    for (int i = 0; i < 256; ++i) {
      osaddr[i] = (unsigned long)NGetTrapAddress(0xA000 | i, kOSTrapType);
      int v = NGetTrapAddress(0xA000 | i, kOSTrapType) != unimp;
      nos += v;
      Put1(v);
    }
    for (int i = 0; i < 1024; ++i) {
      if (i < tbsize) tbaddr[i] = (unsigned long)NGetTrapAddress(0xA800 | i, kToolboxTrapType);
      int v = i < tbsize ? NGetTrapAddress(0xA800 | i, kToolboxTrapType) != unimp : 2;
      ntb += v == 1;
      Put1(v);
    }
  }

  int npack = 0;
  SetResLoad(false);
  for (int i = 0; i < 16; ++i) {
#if TARGET_CPU_68K
    if (rom85 >= 0)
      *(unsigned char *)0xB9E = 0xFF;   /* RomMapInsert: look in the ROM too */
#endif
    int v = GetResource('PACK', i) != nil;
    npack += v;
    Put1(v);
  }
  SetResLoad(true);

  Boolean hasGestalt = TrapAvailable(0xA1AD);
  int n = hasGestalt ? sizeof kSelectors / sizeof kSelectors[0] : 0;
  Put2(n);
  for (int i = 0; i < n; ++i) {
    long r = 0;
    OSErr e = Gestalt(kSelectors[i], &r);
    Put4(kSelectors[i]);
    Put2(e);
    Put4(r);
  }

  Put4('ADDR');
  for (int i = 0; i < 256; ++i) Put4(osaddr[i]);
  for (int i = 0; i < 1024; ++i) Put4(tbaddr[i]);

  /* Let GetNextEvent mount the other disks (it handles disk-inserted
     events), then write next to the application, or on the first
     writable volume when the application runs from a CD. */
  for (long t = TickCount(); TickCount() - t < 120;) {
    EventRecord ev;
    GetNextEvent(everyEvent, &ev);
    SystemTask();
  }
  OSErr err = WriteResults(0);
  int nvols = 0;
  for (int i = 1; err && i < 16; ++i) {
    ParamBlockRec pb;
    pb.volumeParam.ioCompletion = nil;
    pb.volumeParam.ioNamePtr = nil;
    pb.volumeParam.ioVolIndex = i;
    if (PBGetVInfoSync(&pb) != noErr)
      break;
    ++nvols;
    err = WriteResults(pb.volumeParam.ioVRefNum);
  }

  /* No writable disk (QEMU booted from a CD): send the results out of the
     modem port in hex, one line, for the emulator's serial log. */
  if (err) {
    short sref;
    if (OpenDriver("\p.AOut", &sref) == noErr) {
      char hex[140];
      char *h = Put(hex, "TRP:");
      OSErr e = noErr;
      for (int i = 0; i < len && !e; ++i) {
        h = Hex(h, buf[i], 2);
        if (h - hex >= 128 || i + 1 == len) {
          if (i + 1 == len) h = Put(h, "\r\n");
          long count = h - hex;
          e = FSWrite(sref, &count, hex);
          h = hex;
        }
      }
      if (e == noErr)
        err = 1;      /* reported as "sent to the modem port" below */
    }
  }

  Rect r;
  SetRect(&r, 40, 60, 470, 160);
  WindowPtr w = NewWindow(nil, &r, "\pTrap probe", true, documentProc, (WindowPtr)-1, false, 0);
  SetPort(w);
  char *p = Put(gLine[0], "ROM85 $");
  p = Hex(p, rom85, 4);
  p = Put(p, "  ROM version $");
  p = Hex(p, romv, 4);
  p = Put(p, "  SysVersion $");
  p = Hex(p, sysv, 4);
  ShowLine(0, p);
  p = Put(gLine[1], "OS traps $");
  p = Hex(p, nos, 3);
  p = Put(p, "  Toolbox traps $");
  p = Hex(p, ntb, 3);
  p = Put(p, "  PACKs $");
  p = Hex(p, npack, 2);
  ShowLine(1, p);
  p = Put(gLine[2], hasGestalt ? "Gestalt: yes" : "Gestalt: no");
  ShowLine(2, p);
  p = Put(gLine[3], err == 1 ? "Sent the results to the modem port"
                   : err ? "Writing \"Trap Probe\" failed, error $" : "Wrote \"Trap Probe\"");
  if (err && err != 1) {
    p = Hex(p, (unsigned short)err, 4);
    p = Put(p, " on ");
    p = Hex(p, nvols, 1);
    p = Put(p, " volumes");
  }
  ShowLine(3, p);

  EventRecord e;
  for (;;) {
    if (GetNextEvent(everyEvent, &e) && e.what == mouseDown) break;
    SystemTask();
  }
  return 0;
}
