/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Damage.h"
#include <gtest/gtest.h>

TEST(Damage, InitialUnchangedAndForced)
{
	std::vector<uint8_t> image(120 * 156, 0), empty;
	auto r = sixelvnc::damage(empty, image, 120, 156, 6, 13, false);
	EXPECT_EQ(120, r.width);
	EXPECT_EQ(156, r.height);
	r = sixelvnc::damage(image, image, 120, 156, 6, 13, false);
	EXPECT_EQ(0, r.width);
	r = sixelvnc::damage(image, image, 120, 156, 6, 13, true);
	EXPECT_EQ(120, r.width);
}
TEST(Damage, AlignToCellsAndSixelBands)
{
	std::vector<uint8_t> old(120 * 156, 0), image = old;
	image[91 * 120 + 19] = 1;
	auto r = sixelvnc::damage(old, image, 120, 156, 6, 13, false);
	EXPECT_EQ(18, r.x);
	EXPECT_EQ(78, r.y);
	EXPECT_EQ(6, r.width);
	EXPECT_EQ(78, r.height);
}
TEST(Damage, ErasureAndDistantChanges)
{
	std::vector<uint8_t> old(120 * 156, 0), image = old;
	old[1] = 1;
	image[120 * 156 - 1] = 1;
	auto r = sixelvnc::damage(old, image, 120, 156, 6, 13, false);
	EXPECT_EQ(0, r.x);
	EXPECT_EQ(0, r.y);
	EXPECT_EQ(120, r.width);
	EXPECT_EQ(156, r.height);
}
TEST(Damage, PartialFinalBand)
{
	std::vector<uint8_t> old(119 * 151, 0), image = old;
	image.back() = 1;
	auto r = sixelvnc::damage(old, image, 119, 151, 6, 13, false);
	EXPECT_EQ(114, r.x);
	EXPECT_EQ(78, r.y);
	EXPECT_EQ(5, r.width);
	EXPECT_EQ(73, r.height);
}
TEST(Damage, InvalidImage)
{
	std::vector<uint8_t> image;
	EXPECT_THROW(sixelvnc::damage(image, image, 1, 1, 6, 13, false),
	    std::invalid_argument);
}
