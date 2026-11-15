/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Help.h"
#include <gtest/gtest.h>
using namespace sixelvnc;
TEST(Help, PagingAndMode)
{
	auto page = localHelp(80, 24, 0, false);
	EXPECT_EQ(page.pages, 1u);
	EXPECT_NE(page.output.find("Interactive:"), std::string::npos);
	EXPECT_NE(page.output.find("h  Open this help"), std::string::npos);
	EXPECT_NE(localHelp(80, 24, 0, true).output.find("ViewOnly:"), std::string::npos);
}
TEST(Help, SmallWindowsRetainAllText)
{
	auto first = localHelp(20, 6, 0, false);
	ASSERT_GT(first.pages, 1u);
	std::string text;
	for (size_t i = 0; i < first.pages; i++) text += localHelp(20, 6, i, false).output;
	EXPECT_NE(text.find("README.txt"), std::string::npos);
	EXPECT_NE(localHelp(20, 6, first.pages + 1, false).output.find(
	    "vncsixel help " + std::to_string(first.pages)), std::string::npos);
	EXPECT_EQ(localHelp(1, 2, 0, false).output, "\033[H\033[2JE");
}
