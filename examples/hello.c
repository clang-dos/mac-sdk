/* A Toolbox "hello" that builds for 68k and PowerPC from the same source
   with the SDK's headers. */
#include <Quickdraw.h>
#include <Fonts.h>
#include <Windows.h>
#include <Menus.h>
#include <TextEdit.h>
#include <Dialogs.h>
#include <Events.h>
#include <Memory.h>
#include <Gestalt.h>
#include <OSUtils.h>

QDGlobals qd;

/* Append text, then n in hex, as a Pascal string. */
static void PStr(Str255 out, const char *s, unsigned long n) {
  int i = 0;
  for (; *s; ++s) out[++i] = *s;
  for (int sh = 28; sh >= 0; sh -= 4) out[++i] = "0123456789ABCDEF"[(n >> sh) & 15];
  out[0] = i;
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

  Rect r;
  SetRect(&r, 60, 80, 480, 260);
  WindowPtr w = NewWindow(nil, &r, "\pclang-dos SDK", true, documentProc,
                          (WindowPtr)-1, false, 0);
  SetPort(w);

  long sysv = 0;
  OSErr err = Gestalt(gestaltSystemVersion, &sysv);
  Ptr p = NewPtr(1000);               /* register-based traps */
  long ticks;
  Delay(2, &ticks);

  Str255 line;
  MoveTo(20, 30);
  DrawString(TARGET_CPU_68K ? "\pHello from 68k, using the SDK headers"
                            : "\pHello from PowerPC, using the SDK headers");
  MoveTo(20, 60);
  PStr(line, "Gestalt system version: $", err ? 0xFFFFFFFF : sysv);
  DrawString(line);
  MoveTo(20, 90);
  PStr(line, "NewPtr(1000) worked: ", p != nil && MemError() == noErr);
  DrawString(line);
  MoveTo(20, 120);
  DrawString("\pClick to quit.");
  if (p) DisposePtr(p);

  EventRecord e;
  for (;;) {
    if (GetNextEvent(everyEvent, &e) && e.what == mouseDown) break;
    SystemTask();
  }
  return 0;
}
