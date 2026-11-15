/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Input.h"
#include <gtest/gtest.h>
#define XK_MISCELLANY
#include <rfb/keysymdef.h>
#include <vector>
using namespace sixelvnc;
class Parser : public testing::Test {
protected:
	std::vector<InputEvent> events;
	Input input{[this](const InputEvent& e) { events.push_back(e); }};
	void feed(const std::string& s) { input.feed(s.data(), s.size()); }
};
TEST_F(Parser, FragmentedUTF8)
{
	feed("\xe3"); feed("\x81"); EXPECT_TRUE(events.empty());
	feed("\x82"); ASSERT_EQ(events.size(), 1u); EXPECT_EQ(events[0].key, 0x01003042u);
}
TEST_F(Parser, MouseAndRelease)
{
	feed("\033[<0;1;"); EXPECT_TRUE(events.empty()); feed("17M\033[<0;1;17m");
	ASSERT_EQ(events.size(), 2u); EXPECT_EQ(events[0].kind, InputEvent::Mouse);
	EXPECT_EQ(events[0].x, 0); EXPECT_EQ(events[0].y, 16);
	EXPECT_FALSE(events[0].release); EXPECT_TRUE(events[1].release);
}
TEST_F(Parser, ControlPrefix)
{
	feed("\x1d"); ASSERT_EQ(events.size(), 1u);
	EXPECT_EQ(events[0].key, ']'); EXPECT_EQ(events[0].modifiers, 4u);
}
TEST_F(Parser, ModifiedKeys)
{
	feed("\033[27;7;97~\033[1;5A"); ASSERT_EQ(events.size(), 2u);
	EXPECT_EQ(events[0].key, 'a'); EXPECT_EQ(events[0].modifiers, 6u);
	EXPECT_EQ(events[1].key, XK_Up); EXPECT_EQ(events[1].modifiers, 4u);
}
TEST_F(Parser, PasteCannotInvokeLocalPrefix)
{
	feed("\033[200~a\x1d\033[201~b"); ASSERT_EQ(events.size(), 2u);
	EXPECT_EQ(events[0].key, 'a'); EXPECT_EQ(events[1].key, 'b');
}
TEST_F(Parser, DeviceRepliesAreNotKeys)
{
	feed("\033[?63;4c\033[4;468;600t\033[?1016;2$y\033[>4;2m");
	EXPECT_TRUE(events.empty());
}
TEST_F(Parser, RejectMalformedInput)
{
	feed("\xc0\x80\xed\xa0\x80\033[<99999999999999;1;2M\033[27;5;99999999999999999~");
	EXPECT_TRUE(events.empty()); feed("x"); ASSERT_EQ(events.size(), 1u);
}
TEST_F(Parser, EscapeTimeout)
{
	feed("\033"); EXPECT_TRUE(events.empty()); input.expire();
	ASSERT_EQ(events.size(), 1u); EXPECT_EQ(events[0].key, XK_Escape);
}
TEST_F(Parser, AltAndFocus)
{
	feed("\033x\033[O"); ASSERT_EQ(events.size(), 2u);
	EXPECT_EQ(events[0].key, 'x'); EXPECT_EQ(events[0].modifiers, 2u);
	EXPECT_EQ(events[1].kind, InputEvent::FocusOut);
}

TEST_F(Parser, CSIuModifiedCharacter)
{
	feed("\033[97;3u"); ASSERT_EQ(events.size(), 1u);
	EXPECT_EQ(events[0].key, 'a'); EXPECT_EQ(events[0].modifiers, 2u);
}
