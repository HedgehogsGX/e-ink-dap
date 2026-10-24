// Host tests for lib/ui_nav: pio test -e native
#include <unity.h>

#include "ui_nav.h"

void setUp() {}
void tearDown() {}

static void test_apps_resume_where_they_were_left() {
  Navigator nav;
  TEST_ASSERT_EQUAL(Screen::Home, nav.current());
  nav.openApp(App::Reader);
  TEST_ASSERT_EQUAL(Screen::Shelf, nav.current());
  nav.push(Screen::Page);
  nav.goHome();
  nav.openApp(App::Music);
  TEST_ASSERT_EQUAL(Screen::Library, nav.current());
  nav.push(Screen::NowPlaying);
  nav.goHome();
  nav.openApp(App::Reader);
  TEST_ASSERT_EQUAL(Screen::Page, nav.current());  // still in the book
  nav.openApp(App::Music);
  TEST_ASSERT_EQUAL(Screen::NowPlaying, nav.current());
}

static void test_back_ends_at_home() {
  Navigator nav;
  TEST_ASSERT_FALSE(nav.back());
  nav.openApp(App::Settings);
  nav.push(Screen::SettingsPage);
  TEST_ASSERT_TRUE(nav.back());
  TEST_ASSERT_EQUAL(Screen::SettingsList, nav.current());
  TEST_ASSERT_TRUE(nav.back());
  TEST_ASSERT_EQUAL(Screen::Home, nav.current());
  nav.openApp(App::Settings);
  TEST_ASSERT_EQUAL(Screen::SettingsList, nav.current());
}

static void test_back_to_the_page_from_contents() {
  Navigator nav;
  nav.openApp(App::Reader);
  nav.push(Screen::Page);
  nav.push(Screen::ReaderMenu);
  nav.push(Screen::Contents);
  TEST_ASSERT_TRUE(nav.backTo(Screen::Page));
  TEST_ASSERT_EQUAL(Screen::Page, nav.current());
  TEST_ASSERT_EQUAL(2, nav.depth(App::Reader));
  TEST_ASSERT_FALSE(nav.backTo(Screen::Contents));  // not open any more
}

static void test_screens_of_other_apps_are_not_pushed() {
  Navigator nav;
  nav.push(Screen::Page);  // on home
  TEST_ASSERT_EQUAL(Screen::Home, nav.current());
  nav.openApp(App::Music);
  nav.push(Screen::Page);
  TEST_ASSERT_EQUAL(Screen::Library, nav.current());
  nav.push(Screen::Library);  // already on top
  TEST_ASSERT_EQUAL(1, nav.depth(App::Music));
  for (int k = 0; k < 10; k++) nav.push(k % 2 ? Screen::NowPlaying : Screen::Lyrics);
  TEST_ASSERT_EQUAL(Navigator::kMaxDepth, nav.depth(App::Music));
  nav.resetApp(App::Music);
  TEST_ASSERT_EQUAL(Screen::Library, nav.current());
}

static void test_keys() {
  InputContext ctx;
  ctx.screen = Screen::NowPlaying;
  TEST_ASSERT_EQUAL(Command::PlayPause, routeKey(Key::Play, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::NextTrack, routeKey(Key::Play, KeyPress::Long, ctx));
  TEST_ASSERT_EQUAL(Command::VolumeUp, routeKey(Key::VolUp, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::PrevTrack, routeKey(Key::VolDown, KeyPress::Long, ctx));
  TEST_ASSERT_EQUAL(Command::Lock, routeKey(Key::Power, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::PowerOff, routeKey(Key::Power, KeyPress::Long, ctx));
  ctx.screen = Screen::Home;
  TEST_ASSERT_EQUAL(Command::PowerOff, routeKey(Key::Power, KeyPress::Long, ctx));
}

static void test_volume_keys_turn_pages_only_when_asked_and_only_on_a_page() {
  InputContext ctx;
  ctx.screen = Screen::Page;
  TEST_ASSERT_EQUAL(Command::VolumeDown, routeKey(Key::VolDown, KeyPress::Short, ctx));
  ctx.volumeKeysTurnPages = true;
  TEST_ASSERT_EQUAL(Command::NextPage, routeKey(Key::VolDown, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::PrevPage, routeKey(Key::VolUp, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::VolumeUp, routeKey(Key::VolUp, KeyPress::Long, ctx));  // holding: volume
  ctx.screen = Screen::Shelf;
  TEST_ASSERT_EQUAL(Command::VolumeDown, routeKey(Key::VolDown, KeyPress::Short, ctx));
}

static void test_locked_ignores_everything_but_power() {
  InputContext ctx;
  ctx.screen = Screen::Page;
  ctx.locked = true;
  TEST_ASSERT_EQUAL(Command::None, routeKey(Key::Play, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::None, routeKey(Key::VolUp, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::None, routeKey(Key::VolDown, KeyPress::Long, ctx));
  TEST_ASSERT_EQUAL(Command::Unlock, routeKey(Key::Power, KeyPress::Short, ctx));
  TEST_ASSERT_EQUAL(Command::PowerOff, routeKey(Key::Power, KeyPress::Long, ctx));  // no unlock needed
  TEST_ASSERT_EQUAL(Command::None, routeTap(120, 200, ctx));
}

static void test_taps() {
  InputContext ctx;
  ctx.screen = Screen::Page;
  TEST_ASSERT_EQUAL(Command::PrevPage, routeTap(10, 200, ctx));
  TEST_ASSERT_EQUAL(Command::Menu, routeTap(120, 200, ctx));
  TEST_ASSERT_EQUAL(Command::Menu, routeTap(120, 5, ctx));  // no status bar on a page
  TEST_ASSERT_EQUAL(Command::NextPage, routeTap(200, 200, ctx));
  ctx.screen = Screen::Shelf;
  TEST_ASSERT_EQUAL(Command::Home, routeTap(120, 5, ctx));
  TEST_ASSERT_EQUAL(Command::None, routeTap(120, 100, ctx));  // the shelf's own rows
  ctx.screen = Screen::Home;
  TEST_ASSERT_EQUAL(Command::None, routeTap(120, 5, ctx));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_apps_resume_where_they_were_left);
  RUN_TEST(test_back_ends_at_home);
  RUN_TEST(test_back_to_the_page_from_contents);
  RUN_TEST(test_screens_of_other_apps_are_not_pushed);
  RUN_TEST(test_keys);
  RUN_TEST(test_volume_keys_turn_pages_only_when_asked_and_only_on_a_page);
  RUN_TEST(test_locked_ignores_everything_but_power);
  RUN_TEST(test_taps);
  return UNITY_END();
}
