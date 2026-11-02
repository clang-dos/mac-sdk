/* A Mac OS 9 demo that builds for 68k and PowerPC from the same source:
   the Thread Manager, the Folder Manager and HFS Plus calls (FSRef and
   Unicode names), Icon Services and anti-aliased text on both CPUs, plus
   Multiprocessing Services and the Text Encoding Converter on PowerPC.
   The 68k build runs in Mac OS 9's 68k emulator; on System 7 or 8 it
   shows which of these the system lacks. */
#include <Quickdraw.h>
#include <Fonts.h>
#include <MacWindows.h>
#include <Menus.h>
#include <TextEdit.h>
#include <Dialogs.h>
#include <Events.h>
#include <Gestalt.h>
#include <Files.h>
#include <Folders.h>
#include <Icons.h>
#include <Threads.h>
#if !TARGET_CPU_68K
#include <Multiprocessing.h>
#include <TextEncodingConverter.h>
#include <UnicodeConverter.h>
#endif

QDGlobals qd;

static char gLine[8][100];
static int gLines;
static IconRef gIcon;

/* Start a line of text in the window. */
static char *NextLine(void) { return gLine[gLines++]; }

static char *Put(char *p, const char *s) {
  while (*s) *p++ = *s++;
  *p = 0;
  return p;
}

static char *Hex(char *p, unsigned long n, int digits) {
  for (int sh = digits * 4 - 4; sh >= 0; sh -= 4)
    *p++ = "0123456789ABCDEF"[(n >> sh) & 15];
  *p = 0;
  return p;
}

/* Decimal by subtracting powers of ten: 68k code has no divide helper. */
static char *Dec(char *p, unsigned long n) {
  static const unsigned long pow10[] = {1000000000, 100000000, 10000000, 1000000,
                                        100000, 10000, 1000, 100, 10, 1};
  int started = 0;
  for (int i = 0; i < 10; ++i) {
    char d = '0';
    while (n >= pow10[i]) { n -= pow10[i]; ++d; }
    if (d != '0' || started || i == 9) { *p++ = d; started = 1; }
  }
  *p = 0;
  return p;
}

/* Thread Manager: three cooperative threads take turns adding to a sum. */
static long gTurns;

static pascal voidPtr Worker(void *param) {
  for (int i = 0; i < 5; ++i) {
    gTurns += (long)param;
    YieldToAnyThread();
  }
  return param;
}

static void TryThreads(void) {
  char *p = Put(NextLine(), "Thread Manager: ");
  long attr;
  if (Gestalt(gestaltThreadMgrAttr, &attr) != noErr) {
    Put(p, "not installed");
    return;
  }
  ThreadEntryUPP entry = NewThreadEntryUPP(Worker);
  ThreadID ids[3];
  int made = 0;
  for (long i = 0; i < 3; ++i)
    if (NewThread(kCooperativeThread, entry, (void *)(i + 1), 0, kCreateIfNeeded,
                  nil, &ids[made]) == noErr)
      ++made;
  /* Let the threads run until each has finished. */
  for (int spins = 0; spins < 100; ++spins) {
    ThreadState s;
    int alive = 0;
    for (int i = 0; i < made; ++i)
      if (GetThreadState(ids[i], &s) == noErr)
        ++alive;
    if (!alive)
      break;
    YieldToAnyThread();
  }
  p = Dec(p, made);
  p = Put(p, " threads, sum ");
  p = Dec(p, gTurns);
  Put(p, gTurns == 30 ? " (ok)" : " (expected 30)");
}

/* Folder Manager and HFS Plus: the System Folder's Unicode name. */
static void TryFSRef(void) {
  char *p = Put(NextLine(), "FSGetCatalogInfo: ");
  long fs;
  if (Gestalt(gestaltFSAttr, &fs) != noErr || !(fs & (1L << gestaltHasHFSPlusAPIs))) {
    Put(p, "no HFS Plus APIs");
    return;
  }
  FSRef ref;
  HFSUniStr255 name;
  OSErr err = FSFindFolder(kOnSystemDisk, kSystemFolderType, kDontCreateFolder, &ref);
  if (!err)
    err = FSGetCatalogInfo(&ref, kFSCatInfoNone, nil, &name, nil, nil);
  if (err) {
    p = Put(p, "error ");
    Dec(p, -err);
    return;
  }
  *p++ = '"';
  for (int i = 0; i < name.length && i < 24; ++i)
    *p++ = name.unicode[i] < 0x80 ? name.unicode[i] : '?';
  p = Put(p, "\", ");
  p = Dec(p, name.length);
  Put(p, " UTF-16 units");
}

/* Icon Services: the System Folder icon, drawn later. */
static void TryIcons(void) {
  char *p = Put(NextLine(), "Icon Services: ");
  OSErr err = GetIconRef(kOnSystemDisk, kSystemIconsCreator, kSystemFolderIcon, &gIcon);
  if (err) {
    gIcon = nil;
    p = Put(p, "error ");
    Dec(p, -err);
  } else {
    Put(p, "GetIconRef ok, PlotIconRef at right");
  }
}

static void TryAntiAliasing(void) {
  char *p = Put(NextLine(), "Anti-aliased text: ");
  SInt16 minSize = 0;
  long sysv = 0;
  Gestalt(gestaltSystemVersion, &sysv);
  if (sysv < 0x0850) {
    Put(p, "needs Mac OS 8.5");
    return;
  }
  p = Put(p, IsAntiAliasedTextEnabled(&minSize) ? "on, from " : "off, from ");
  p = Dec(p, minSize);
  Put(p, " points");
}

#if !TARGET_CPU_68K
/* Multiprocessing Services: a preemptive task adds 1 to 100000. */
static OSStatus SumTask(void *param) {
  unsigned long sum = 0;
  for (unsigned long i = 1; i <= 100000; ++i)
    sum += i;
  *(unsigned long *)param = sum;
  return noErr;
}

static void TryMP(void) {
  char *p = Put(NextLine(), "Multiprocessing: ");
  static unsigned long sum;
  MPQueueID q;
  MPTaskID task;
  void *p1, *p2, *p3;
  p = Dec(p, MPProcessors());
  p = Put(p, " CPU, preemptive ");
  if (MPCreateQueue(&q) != noErr) {
    Put(p, "queue failed");
    return;
  }
  if (MPCreateTask(SumTask, &sum, 0, q, nil, nil, 0, &task) == noErr &&
      MPWaitOnQueue(q, &p1, &p2, &p3, kDurationForever) == noErr) {
    p = Put(p, "task summed ");
    p = Dec(p, sum);
    Put(p, sum == (unsigned long)5000050000ULL ? " (ok)" : " (wrong)");
  } else {
    Put(p, "task failed");
  }
  MPDeleteQueue(q);
}

/* Text Encoding Converter: Mac Roman to UTF-8. */
static void TryTEC(void) {
  char *p = Put(NextLine(), "TEC: \"Caf\216\" in UTF-8 is ");
  TECObjectRef conv;
  static const UInt8 in[] = {'C', 'a', 'f', 0x8E};
  UInt8 out[16];
  ByteCount inLen, outLen = 0;
  TextEncoding utf8 = CreateTextEncoding(kTextEncodingUnicodeDefault,
                                         kTextEncodingDefaultVariant, kUnicodeUTF8Format);
  OSStatus err = TECCreateConverter(&conv, kTextEncodingMacRoman, utf8);
  if (!err) {
    err = TECConvertText(conv, in, sizeof in, &inLen, out, sizeof out, &outLen);
    TECDisposeConverter(conv);
  }
  if (err) {
    p = Put(p, "error ");
    Dec(p, -err);
    return;
  }
  for (ByteCount i = 0; i < outLen; ++i) {
    p = Hex(p, out[i], 2);
    *p++ = ' ';
  }
  *p = 0;
}
#endif

static void Draw(WindowRef w) {
  Rect r;
  EraseRect(&w->portRect);
  TextFont(0);
  MoveTo(12, 22);
  DrawString(TARGET_CPU_68K ? "\pMac OS 9 calls from 68k code"
                            : "\pMac OS 9 calls from PowerPC code");
  TextFont(1);
  TextSize(12);
  for (int i = 0; i < gLines; ++i) {
    Str255 s;
    int n = 0;
    while (gLine[i][n]) { s[n + 1] = gLine[i][n]; ++n; }
    s[0] = n;
    MoveTo(12, 50 + 20 * i);
    DrawString(s);
  }
  if (gIcon) {
    SetRect(&r, w->portRect.right - 76, 8, w->portRect.right - 12, 72);
    PlotIconRef(&r, kAlignNone, kTransformNone, kIconServicesNormalUsageFlag, gIcon);
  }
  MoveTo(12, w->portRect.bottom - 10);
  DrawString("\pClick the close box or press Command-Q to quit");
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

  long sysv = 0;
  Gestalt(gestaltSystemVersion, &sysv);
  char *p = Put(NextLine(), "System version: ");
  p = Hex(p, sysv >> 8, 1);
  *p++ = '.';
  p = Hex(p, (sysv >> 4) & 15, 1);
  *p++ = '.';
  Hex(p, sysv & 15, 1);

  TryThreads();
  TryFSRef();
  TryIcons();
  TryAntiAliasing();
#if !TARGET_CPU_68K
  TryMP();
  TryTEC();
#endif

  Rect r;
  SetRect(&r, 30, 50, 590, 290);
  WindowRef w = NewCWindow(nil, &r, "\pclang-dos SDK: Mac OS 9", true,
                           noGrowDocProc, (WindowRef)-1L, true, 0);
  SetPort(w);
  for (;;) {
    EventRecord e;
    if (!WaitNextEvent(everyEvent, &e, 10, nil))
      continue;
    if (e.what == updateEvt) {
      BeginUpdate(w);
      Draw(w);
      EndUpdate(w);
    } else if (e.what == keyDown && (e.modifiers & cmdKey) &&
               (e.message & charCodeMask) == 'q') {
      break;
    } else if (e.what == mouseDown) {
      WindowRef hit;
      short part = FindWindow(e.where, &hit);
      if (part == inGoAway && TrackGoAway(w, e.where))
        break;
      if (part == inDrag)
        DragWindow(w, e.where, &qd.screenBits.bounds);
    }
  }
  if (gIcon)
    ReleaseIconRef(gIcon);
  return 0;
}
