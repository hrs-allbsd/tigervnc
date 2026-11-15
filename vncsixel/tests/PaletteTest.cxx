/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Palette.h"
#include <gtest/gtest.h>

TEST(Palette, ExactColors)
{
	for (int i = 0; i < 256; i++)
		EXPECT_EQ(i, sixelvnc::rgb332(((i >> 5) & 7) * 255 / 7,
		    ((i >> 2) & 7) * 255 / 7, (i & 3) * 255 / 3));
}
TEST(Palette, NearestLevels)
{
	for (int value = 0; value < 256; value++) {
		int r = sixelvnc::rgb332(value, 0, 0) >> 5;
		int g = (sixelvnc::rgb332(0, value, 0) >> 2) & 7;
		int b = sixelvnc::rgb332(0, 0, value) & 3;
		EXPECT_EQ(r, g);
		for (int i = 0; i < 8; i++)
			EXPECT_LE(std::abs(value - r * 255 / 7),
			    std::abs(value - i * 255 / 7));
		for (int i = 0; i < 4; i++)
			EXPECT_LE(std::abs(value - b * 255 / 3),
			    std::abs(value - i * 255 / 3));
	}
}
