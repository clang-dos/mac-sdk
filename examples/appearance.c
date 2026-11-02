/* A Mac OS 8 Appearance Manager demo that builds for 68k and PowerPC from
   the same source: theme drawing, the Appearance controls in an embedding
   hierarchy, a menu command ID and a Collection. Appearance 1.0.1 (Mac OS
   8.1) has no auto-toggling check boxes, so the check box toggles here. */
#include <Quickdraw.h>
#include <Fonts.h>
#include <MacWindows.h>
#include <Menus.h>
#include <TextEdit.h>
#include <Dialogs.h>
#include <Events.h>
#include <Gestalt.h>
#include <Appearance.h>
#include <Controls.h>
#include <ControlDefinitions.h>
#include <Collections.h>

QDGlobals qd;

static ControlRef gProgress, gArrows;

/* Append text, then n in hex, as a Pascal string. */
static void PStr(Str255 out, const char *s, unsigned long n, int digits) {
  int i = 0;
  for (; *s; ++s) out[++i] = *s;
  for (int sh = digits * 4 - 4; sh >= 0; sh -= 4)
    out[++i] = "0123456789ABCDEF"[(n >> sh) & 15];
  out[0] = i;
}

static void ShowValue(short y, const char *s, unsigned long n, int digits) {
  Str255 t;
  PStr(t, s, n, digits);
  MoveTo(250, y);
  DrawString(t);
}

static long gAppr, gApvr, gItems, gGot, gCmd, gMenuH, gCollapsable, gPart;

static void Draw(WindowRef w) {
  Rect r;
  SetThemeWindowBackground(w, kThemeBrushDialogBackgroundActive, false);
  EraseRect(&w->portRect);

  SetRect(&r, -1, 0, w->portRect.right + 1, 24);
  DrawThemeWindowHeader(&r, kThemeStateActive);
  MoveTo(10, 16);
  DrawString(TARGET_CPU_68K ? "\pAppearance Manager from 68k"
                            : "\pAppearance Manager from PowerPC");

  SetRect(&r, 240, 36, 500, 188);
  DrawThemePrimaryGroup(&r, kThemeStateActive);
  SetThemeTextColor(kThemeTextColorDialogActive, 8, true);
  ShowValue(54, "Gestalt appr: ", gAppr, 2);
  ShowValue(72, "Appearance version: ", gApvr, 4);
  ShowValue(90, "Collection items: ", gItems, 2);
  ShowValue(108, "Collection item: ", gGot, 8);
  ShowValue(126, "Menu command ID: ", gCmd, 8);
  ShowValue(144, "Menu bar height: ", gMenuH, 2);
  ShowValue(162, "Collapsable: ", gCollapsable, 1);
  ShowValue(180, "Last control part: ", gPart, 2);

  SetRect(&r, 240, 196, 500, 197);
  DrawThemeSeparator(&r, kThemeStateActive);
  SetRect(&r, 244, 210, 360, 232);
  DrawThemeEditTextFrame(&r, kThemeStateActive);
  DrawThemeFocusRect(&r, true);
  SetRect(&r, 380, 208, 420, 248);
  DrawThemeGenericWell(&r, kThemeStateActive, true);
  SetRect(&r, -1, w->portRect.bottom - 16, 200, w->portRect.bottom + 1);
  DrawThemePlacard(&r, kThemeStateActive);
  MoveTo(8, w->portRect.bottom - 4);
  DrawString("\pClick the close box to quit");

  DrawControls(w);
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

  if (Gestalt(gestaltAppearanceAttr, &gAppr) != noErr) {
    SysBeep(10);
    return 0;
  }
  if (Gestalt(gestaltAppearanceVersion, &gApvr) != noErr)
    gApvr = 0x0100;
  RegisterAppearanceClient();

  MenuHandle m = NewMenu(128, "\pDemo");
  AppendMenu(m, "\pQuit/Q");
  InsertMenu(m, 0);
  DrawMenuBar();
  SetMenuItemCommandID(m, 1, 'quit');
  UInt32 cmd = 0;
  GetMenuItemCommandID(m, 1, &cmd);
  gCmd = cmd;
  SInt16 mh = 0;
  GetThemeMenuBarHeight(&mh);
  gMenuH = mh;

  Collection c = NewCollection();
  if (c) {
    static long v = 0x1998ABCD, v2 = 2;
    long got = 0, size = 4;
    AddCollectionItem(c, 'demo', 1, sizeof v, &v);
    AddCollectionItem(c, 'demo', 2, sizeof v2, &v2);
    gItems = CountCollectionItems(c);
    GetCollectionItem(c, 'demo', 1, &size, &got);
    gGot = got;
    DisposeCollection(c);
  }

  Rect r;
  SetRect(&r, 40, 60, 560, 340);
  WindowRef w = NewCWindow(nil, &r, "\pclang-dos SDK: Mac OS 8", true,
                           kWindowDocumentProc, (WindowRef)-1L, true, 0);
  SetPort(w);
  gCollapsable = IsWindowCollapsable(w);

  ControlRef root, group;
  CreateRootControl(w, &root);
  SetRect(&r, 12, 34, 226, 196);
  group = NewControl(w, &r, "\pControls", true, 0, 0, 0,
                     kControlGroupBoxTextTitleProc, 0);
  SetRect(&r, 24, 56, 120, 74);
  EmbedControl(NewControl(w, &r, "\pCheck box", true, 1, 0, 1,
                          kControlCheckBoxProc, 0), group);
  SetRect(&r, 24, 78, 120, 96);
  EmbedControl(NewControl(w, &r, "\pRadio", true, 1, 0, 1,
                          kControlRadioButtonProc, 0), group);
  SetRect(&r, 24, 104, 210, 126);
  EmbedControl(NewControl(w, &r, nil, true, 40, 0, 100, kControlSliderProc, 0),
               group);
  SetRect(&r, 24, 134, 180, 148);
  gProgress = NewControl(w, &r, nil, true, 0, 0, 100, kControlProgressBarProc, 0);
  EmbedControl(gProgress, group);
  SetRect(&r, 190, 132, 206, 148);
  gArrows = NewControl(w, &r, nil, true, 0, 0, 1, kControlChasingArrowsProc, 0);
  EmbedControl(gArrows, group);
  SetRect(&r, 140, 54, 212, 92);
  EmbedControl(NewControl(w, &r, "\pBevel", true, 0, 0, 0,
                          kControlBevelButtonNormalBevelProc, 0), group);
  SetRect(&r, 24, 160, 40, 176);
  EmbedControl(NewControl(w, &r, nil, true, 0, 0, 1,
                          kControlTriangleAutoToggleProc, 0), group);
  SetRect(&r, 120, 214, 210, 234);
  NewControl(w, &r, "\pOK", true, 0, 0, 1, kControlPushButtonProc, 0);
  SetRect(&r, 24, 214, 104, 234);
  NewControl(w, &r, "\pCancel", true, 0, 0, 1, kControlPushButtonProc, 0);

  Draw(w);
  for (;;) {
    EventRecord e;
    if (!WaitNextEvent(everyEvent, &e, 2, nil)) {
      IdleControls(w);
      short v = GetControlValue(gProgress) + 1;
      SetControlValue(gProgress, v > 100 ? 0 : v);
      continue;
    }
    if (e.what == updateEvt) {
      BeginUpdate(w);
      Draw(w);
      EndUpdate(w);
    } else if (e.what == keyDown && (e.modifiers & cmdKey)) {
      UInt32 sel = MenuEvent(&e);
      if (sel >> 16 == 128)
        break;
    } else if (e.what == mouseDown) {
      WindowRef hit;
      short part = FindWindow(e.where, &hit);
      if (part == inMenuBar) {
        if (MenuSelect(e.where) >> 16 == 128)
          break;
        HiliteMenu(0);
      } else if (part == inGoAway && TrackGoAway(w, e.where)) {
        break;
      } else if (part == inDrag) {
        DragWindow(w, e.where, &qd.screenBits.bounds);
      } else if (part == inContent) {
        Point p = e.where;
        SInt16 cpart;
        GlobalToLocal(&p);
        ControlRef ctl = FindControlUnderMouse(p, w, &cpart);
        if (ctl) {
          Rect inval;
          gPart = HandleControlClick(ctl, p, e.modifiers, (ControlActionUPP)-1L);
          if (gPart == kControlCheckBoxPart)
            SetControlValue(ctl, !GetControlValue(ctl));
          SetRect(&inval, 250, 168, 490, 186);
          InvalRect(&inval);
        }
      }
    }
  }
  UnregisterAppearanceClient();
  return 0;
}
