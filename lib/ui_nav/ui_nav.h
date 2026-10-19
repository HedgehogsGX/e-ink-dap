// Moving between the home screen and the apps (Music, Reader, Settings), and what the
// buttons and taps do on each screen. Plain C++17, no Arduino dependency.
//
// Each app keeps its own stack of screens, so going home and back to an app returns to
// the screen you left: the page of your book, the song playing. From any screen, holding
// Lock or tapping the status bar goes home; screens without a status bar (a book page)
// have their menu instead.
#pragma once
#include <cstdint>

enum class App : uint8_t { Home, Music, Reader, Settings };

enum class Screen : uint8_t {
  Home,
  Library, NowPlaying, Lyrics,       // Music; the library is its first screen
  Shelf, Page, ReaderMenu, Contents,  // Reader; Contents has the bookmarks too
  SettingsList, SettingsPage,         // Settings
};

class Navigator {
 public:
  static constexpr int kMaxDepth = 6;

  static App appOf(Screen s);
  static Screen rootOf(App a);

  App app() const { return app_; }
  Screen current() const;

  void goHome() { app_ = App::Home; }
  // Opens an app where it was left (its first screen the first time).
  void openApp(App a);
  // Shows a screen of the current app on top of the current one. Ignored if it belongs
  // to another app; when the stack is full, it replaces the top screen.
  void push(Screen s);
  // One screen back; from an app's first screen, home. False if already home.
  bool back();
  // Back to `s` if it is open in the current app (e.g. from Contents to the page), else
  // nothing. True if it is now on top.
  bool backTo(Screen s);
  // Forgets where an app was: next time it opens on its first screen.
  void resetApp(App a);
  int depth(App a) const { return a == App::Home ? 0 : depth_[(int)a]; }

 private:
  App app_ = App::Home;
  Screen stack_[4][kMaxDepth] = {};
  uint8_t depth_[4] = {};
};

enum class Key : uint8_t { Play, VolUp, VolDown, Lock };
enum class KeyPress : uint8_t { Short, Long };

enum class Command : uint8_t {
  None, PlayPause, NextTrack, PrevTrack, VolumeUp, VolumeDown, Lock, Unlock, Home, NextPage, PrevPage, Menu,
};

struct InputContext {
  Screen screen = Screen::Home;
  bool locked = false;
  bool volumeKeysTurnPages = false;  // Settings::volumeKeysTurnPages
};

// The four buttons. Play: short = play/pause, hold = next song. Vol+/Vol-: short = volume,
// hold = next/previous song; on a book page with "volume keys turn pages", short turns
// the page (Vol- forward) and hold changes the volume. Lock: short = lock/unlock, hold =
// home. While locked, only a short Lock press does anything.
Command routeKey(Key key, KeyPress press, const InputContext& ctx);

// A tap before the screen's own buttons see it: on a book page, the left third turns
// back, the right third forward and the middle opens the menu; elsewhere the status bar
// (top `statusBar` px) goes home. Command::None means the screen handles the tap.
Command routeTap(int x, int y, const InputContext& ctx, int width = 240, int statusBar = 20);
