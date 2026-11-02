/* A QuickTime demo for System 7 with QuickTime 1.5 or later, and for Mac OS
   8 and 9 on 68k and PowerPC: it lists the installed compressors, draws 30
   frames off screen, compresses each with the Animation compressor into a
   new movie file, opens the file again and plays the movie in a loop with
   the standard movie controller. The calls are the ones in Apple's QuickTime 1.5 interfaces. */
#include <Quickdraw.h>
#include <Fonts.h>
#include <MacWindows.h>
#include <Menus.h>
#include <TextEdit.h>
#include <Dialogs.h>
#include <Events.h>
#include <Gestalt.h>
#include <Files.h>
#include <Script.h>
#include <Movies.h>
#include <ImageCompression.h>

QDGlobals qd;

enum { kWidth = 160, kHeight = 120, kFrames = 30 };
#define kAnimationCodec 'rle '

static char gLine[12][64];
static int gLines;

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

static char *Error(char *p, const char *what, long err) {
  p = Put(p, what);
  p = Put(p, " failed, error -");
  return Dec(p, -err);
}

/* The Image Compression Manager's list of compressors. */
static void ListCodecs(void) {
  CodecNameSpecListPtr list;
  char *p = Put(NextLine(), "Compressors: ");
  if (GetCodecNameList(&list, 0) != noErr) {
    Put(p, "none");
    return;
  }
  for (int i = 0; i < list->count; ++i) {
    unsigned char *name = (unsigned char *)list->list[i].typeName;
    if (p - gLine[gLines - 1] + name[0] > 56)
      p = Put(NextLine(), "   ");
    for (int j = 1; j <= name[0]; ++j)
      *p++ = name[j];
    p = Put(p, i + 1 < list->count ? ", " : "");
  }
  DisposeCodecNameList(list);
}

/* Frame n: a ball that moves across a striped background. */
static void DrawFrame(int x, int n) {
  static RGBColor sky = {0x9999, 0xCCCC, 0xFFFF}, ground = {0x3333, 0x9999, 0x3333},
                  ball = {0xFFFF, 0x3333, 0x0000}, black = {0, 0, 0};
  Rect r;
  SetRect(&r, 0, 0, kWidth, 80);
  RGBForeColor(&sky);
  PaintRect(&r);
  SetRect(&r, 0, 80, kWidth, kHeight);
  RGBForeColor(&ground);
  PaintRect(&r);
  SetRect(&r, x, 40, x + 40, 80);
  RGBForeColor(&ball);
  PaintOval(&r);
  RGBForeColor(&black);
  TextFont(0);
  TextSize(12);
  MoveTo(6, 16);
  char s[16];
  char *e = Put(s + 1, "frame ");
  e = Dec(e, n + 1);
  s[0] = e - (s + 1);
  DrawString((unsigned char *)s);
}

/* Draws the frames into a GWorld, compresses them and writes a movie
   file. Returns the movie, still open in memory, or nil. */
static Movie MakeMovie(void) {
  char *p = NextLine();
  Rect r;
  GWorldPtr gw;
  CGrafPtr oldPort;
  GDHandle oldDevice;
  SetRect(&r, 0, 0, kWidth, kHeight);
  OSErr err = NewGWorld(&gw, 8, &r, nil, nil, 0);
  if (err) {
    Error(p, "NewGWorld", err);
    return nil;
  }
  PixMapHandle pm = GetGWorldPixMap(gw);
  LockPixels(pm);

  FSSpec spec;
  short resRef;
  Movie movie;
  FSMakeFSSpec(0, 0, "\pclang-dos movie", &spec);
  err = CreateMovieFile(&spec, 'TVOD', smSystemScript, createMovieFileDeleteCurFile,
                        &resRef, &movie);
  if (err) {
    Error(p, "CreateMovieFile", err);
    DisposeGWorld(gw);
    return nil;
  }
  Track track = NewMovieTrack(movie, (Fixed)kWidth << 16, (Fixed)kHeight << 16, 0);
  Media media = NewTrackMedia(track, VideoMediaType, 600, nil, 0);
  long maxSize = 0, total = 0;
  GetMaxCompressionSize(pm, &r, 8, codecNormalQuality, kAnimationCodec, 0, &maxSize);
  Handle data = NewHandle(maxSize);
  ImageDescriptionHandle desc = (ImageDescriptionHandle)NewHandle(4);
  const char *step = "BeginMediaEdits";
  err = data && desc ? BeginMediaEdits(media) : memFullErr;
  GetGWorld(&oldPort, &oldDevice);
  for (int f = 0, x = -40; f < kFrames && !err; ++f, x += 7) {
    SetGWorld(gw, nil);
    DrawFrame(x, f);
    SetGWorld(oldPort, oldDevice);
    HLock(data);
    step = "CompressImage";
    err = CompressImage(pm, &r, codecNormalQuality, kAnimationCodec, desc, *data);
    HUnlock(data);
    /* Read the size first: AddMediaSample clears it in the description. */
    long size = (**desc).dataSize;
    total += size;
    if (!err) {
      step = "AddMediaSample";
      err = AddMediaSample(media, data, 0, size, 60, (SampleDescriptionHandle)desc, 1, 0,
                           nil);
    }
  }
  if (!err) {
    step = "EndMediaEdits";
    err = EndMediaEdits(media);
  }
  if (!err) {
    step = "InsertMediaIntoTrack";
    err = InsertMediaIntoTrack(track, 0, 0, GetMediaDuration(media), 1L << 16);
  }
  short resId = 0;
  if (!err) {
    step = "AddMovieResource";
    err = AddMovieResource(movie, resRef, &resId, nil);
  }
  CloseMovieFile(resRef);
  if (data)
    DisposeHandle(data);
  if (desc)
    DisposeHandle((Handle)desc);
  DisposeGWorld(gw);
  DisposeMovie(movie);
  /* Open the file again, as a player would. */
  if (!err) {
    step = "OpenMovieFile";
    err = OpenMovieFile(&spec, &resRef, fsRdPerm);
  }
  if (!err) {
    step = "NewMovieFromFile";
    resId = 0;
    err = NewMovieFromFile(&movie, resRef, &resId, nil, newMovieActive, nil);
    CloseMovieFile(resRef);
  }
  if (err) {
    Error(p, step, err);
    return nil;
  }
  p = Put(p, "Wrote \"clang-dos movie\": ");
  p = Dec(p, kFrames);
  p = Put(p, " frames, ");
  p = Dec(p, total);
  p = Put(p, " bytes of Animation data");
  return movie;
}

static void Draw(WindowRef w, MovieController mc) {
  EraseRect(&w->portRect);
  if (mc)
    MCDraw(mc, w);
  TextFont(0);
  TextSize(12);
  MoveTo(12, 20);
  DrawString(TARGET_CPU_68K ? "\pQuickTime from 68k code" : "\pQuickTime from PowerPC code");
  TextFont(1);
  TextSize(9);
  for (int i = 0; i < gLines; ++i) {
    Str255 s;
    int n = 0;
    while (gLine[i][n]) { s[n + 1] = gLine[i][n]; ++n; }
    s[0] = n;
    MoveTo(12, 186 + 13 * i);
    DrawString(s);
  }
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

  long qtVersion = 0, icmVersion = 0;
  Movie movie = nil;
  MovieController mc = nil;
  char *p = Put(NextLine(), "QuickTime ");
  if (Gestalt(gestaltQuickTime, &qtVersion) != noErr) {
    Put(p, "is not installed");
  } else {
    p = Hex(p, (unsigned long)qtVersion >> 24, 1);
    *p++ = '.';
    p = Hex(p, (qtVersion >> 20) & 15, 1);
    *p++ = '.';
    p = Hex(p, (qtVersion >> 16) & 15, 1);
    if (EnterMovies() != noErr) {
      Put(p, ", EnterMovies failed");
    } else {
      CodecManagerVersion(&icmVersion);
      p = Put(p, ", Image Compression Manager version ");
      Dec(p, icmVersion);
      ListCodecs();
      movie = MakeMovie();
    }
  }

  Rect r;
  SetRect(&r, 40, 50, 480, 360);
  WindowRef w = NewCWindow(nil, &r, "\pclang-dos SDK: QuickTime", true, noGrowDocProc,
                           (WindowRef)-1L, true, 0);
  SetPort(w);
  if (movie) {
    Rect box;
    SetMovieGWorld(movie, (CGrafPtr)w, nil);
    GetMovieBox(movie, &box);
    OffsetRect(&box, 12 - box.left, 32 - box.top);
    SetMovieBox(movie, &box);
    mc = NewMovieController(movie, &box, mcTopLeftMovie);
    if (mc) {
      MCDoAction(mc, mcActionSetLooping, (void *)1);
      MCDoAction(mc, mcActionPlay, (void *)(1L << 16));
    }
  }
  for (;;) {
    EventRecord e;
    WaitNextEvent(everyEvent, &e, 0, nil);
    if (e.what == updateEvt) {
      BeginUpdate(w);
      Draw(w, mc);
      EndUpdate(w);
    } else if (mc && MCIsPlayerEvent(mc, &e)) {
      continue;
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
  if (mc)
    DisposeMovieController(mc);
  if (movie)
    DisposeMovie(movie);
  return 0;
}
