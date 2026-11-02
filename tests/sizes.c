/* Sizes of Toolbox records, from Inside Macintosh. They must match on
   68k and PowerPC: both use 68k alignment. */
#include <Multiverse.h>
#define SIZE(t, n) _Static_assert(sizeof(t) == (n), #t)
SIZE(Rect, 8);
SIZE(Point, 4);
SIZE(EventRecord, 16);
SIZE(BitMap, 14);
SIZE(Cursor, 68);
SIZE(GrafPort, 108);
SIZE(CGrafPort, 108);
SIZE(WindowRecord, 156);
SIZE(DialogRecord, 170);
SIZE(QDGlobals, 206);
SIZE(FInfo, 16);
SIZE(FSSpec, 70);
SIZE(RGBColor, 6);
SIZE(ColorSpec, 8);
SIZE(PenState, 18);
SIZE(FontInfo, 8);
SIZE(TERec, 98);              /* lineStarts[1]; Apple declares [16001] */
_Static_assert(__builtin_offsetof(TERec, lineStarts) == 96, "lineStarts");
SIZE(MenuInfo, 270);
SIZE(ControlRecord, 296);
SIZE(SysEnvRec, 16);
SIZE(HFileParam, 80);
SIZE(ParamBlockRec, 80);
SIZE(CInfoPBRec, 108);
SIZE(AEDesc, 8);
SIZE(PixMap, 50);
int main(void) { return 0; }
