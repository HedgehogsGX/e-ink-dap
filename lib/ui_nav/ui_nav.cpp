#include "ui_nav.h"

App Navigator::appOf(Screen s) {
  switch (s) {
    case Screen::Library:
    case Screen::NowPlaying:
    case Screen::Lyrics: return App::Music;
    case Screen::Shelf:
    case Screen::Page:
    case Screen::ReaderMenu:
    case Screen::Contents: return App::Reader;
    case Screen::SettingsList:
    case Screen::SettingsPage: return App::Settings;
    default: return App::Home;
  }
}

Screen Navigator::rootOf(App a) {
  switch (a) {
    case App::Music: return Screen::Library;
    case App::Reader: return Screen::Shelf;
    case App::Settings: return Screen::SettingsList;
    default: return Screen::Home;
  }
}

Screen Navigator::current() const {
  if (app_ == App::Home) return Screen::Home;
  int a = (int)app_;
  return depth_[a] ? stack_[a][depth_[a] - 1] : rootOf(app_);
}

void Navigator::openApp(App a) {
  app_ = a;
  if (a != App::Home && depth_[(int)a] == 0) {
    stack_[(int)a][0] = rootOf(a);
    depth_[(int)a] = 1;
  }
}

void Navigator::push(Screen s) {
  if (app_ == App::Home || appOf(s) != app_ || s == current()) return;
  int a = (int)app_;
  if (depth_[a] == kMaxDepth) depth_[a]--;
  stack_[a][depth_[a]++] = s;
}

bool Navigator::back() {
  if (app_ == App::Home) return false;
  int a = (int)app_;
  if (depth_[a] > 1) depth_[a]--;
  else goHome();
  return true;
}

bool Navigator::backTo(Screen s) {
  if (app_ == App::Home || appOf(s) != app_) return false;
  int a = (int)app_;
  for (int d = depth_[a]; d > 0; d--) {
    if (stack_[a][d - 1] == s) {
      depth_[a] = (uint8_t)d;
      return true;
    }
  }
  return false;
}

void Navigator::resetApp(App a) {
  if (a == App::Home) return;
  depth_[(int)a] = 0;
  if (app_ == a) openApp(a);
}

Command routeKey(Key key, KeyPress press, const InputContext& ctx) {
  bool hold = press == KeyPress::Long;
  if (key == Key::Power) return hold ? Command::PowerOff : ctx.locked ? Command::Unlock : Command::Lock;
  if (ctx.locked) return Command::None;
  bool pages = ctx.screen == Screen::Page && ctx.volumeKeysTurnPages;
  switch (key) {
    case Key::Play: return hold ? Command::NextTrack : Command::PlayPause;
    case Key::VolUp:
      if (pages) return hold ? Command::VolumeUp : Command::PrevPage;
      return hold ? Command::NextTrack : Command::VolumeUp;
    case Key::VolDown:
      if (pages) return hold ? Command::VolumeDown : Command::NextPage;
      return hold ? Command::PrevTrack : Command::VolumeDown;
    case Key::Power: break;  // handled above
  }
  return Command::None;
}

Command routeTap(int x, int y, const InputContext& ctx, int width, int statusBar) {
  if (ctx.locked) return Command::None;
  if (ctx.screen == Screen::Page) {
    if (x < width / 3) return Command::PrevPage;
    if (x >= width - width / 3) return Command::NextPage;
    return Command::Menu;
  }
  if (ctx.screen != Screen::Home && y < statusBar) return Command::Home;
  return Command::None;
}
