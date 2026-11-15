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

TEST(Damage, SeparateDistantRegions)
{
	std::vector<uint8_t> old(600 * 468);
	for (size_t i = 0; i < old.size(); i++) old[i] = i % 256;
	auto image = old;
	image[80 * 600 + 20] ^= 1;
	image[400 * 600 + 580] ^= 1;
	auto regions = sixelvnc::damageRegions(old, image, 600, 468, 6, 13,
	    false, false);
	ASSERT_EQ(2u, regions.size());
	uint64_t area = 0;
	for (const auto& r : regions) {
		EXPECT_EQ(0, r.x % 6);
		EXPECT_EQ(0, r.y % 78);
		area += r.width * r.height;
	}
	EXPECT_LT(area, 600u * 468 / 4);
	EXPECT_EQ(1u, sixelvnc::damageRegions(old, image, 600, 468, 6, 13,
	    false, true).size());
}
TEST(Damage, PreferBoundsForDenseOrSingleChanges)
{
	std::vector<uint8_t> old(600 * 468, 0), image(old.size(), 1);
	auto regions = sixelvnc::damageRegions(old, image, 600, 468, 6, 13,
	    false, false);
	ASSERT_EQ(1u, regions.size());
	EXPECT_EQ(600, regions[0].width);
	image = old;
	image.back() = 1;
	regions = sixelvnc::damageRegions(old, image, 600, 468, 6, 13,
	    false, false);
	ASSERT_EQ(1u, regions.size());
	EXPECT_EQ(6, regions[0].width);
	EXPECT_TRUE(sixelvnc::damageRegions(old, old, 600, 468, 6, 13,
	    false, false).empty());
}
TEST(Damage, SparseRegionsCoverChangesWithinImage)
{
	uint32_t seed = 12345;
	std::vector<uint8_t> old(599 * 431, 0);
	for (int attempt = 0; attempt < 20; attempt++) {
		auto image = old;
		std::vector<size_t> changed;
		for (int i = 0; i < 9; i++) {
			seed = seed * 1664525u + 1013904223u;
			size_t pixel = seed % image.size();
			image[pixel] = 1;
			changed.push_back(pixel);
		}
		auto regions = sixelvnc::damageRegions(old, image, 599, 431, 6, 13,
		    false, false);
		EXPECT_LE(regions.size(), 32u);
		for (const auto& r : regions) {
			EXPECT_GE(r.x, 0);
			EXPECT_GE(r.y, 0);
			EXPECT_LE(r.x + r.width, 599);
			EXPECT_LE(r.y + r.height, 431);
			EXPECT_EQ(0, r.x % 6);
			EXPECT_EQ(0, r.y % 78);
		}
		for (size_t pixel : changed) {
			int x = pixel % 599, y = pixel / 599;
			bool covered = false;
			for (const auto& r : regions)
				covered |= x >= r.x && x < r.x + r.width &&
				    y >= r.y && y < r.y + r.height;
			EXPECT_TRUE(covered);
		}
	}
}
TEST(Damage, FragmentationFallsBackToBounds)
{
	std::vector<uint8_t> old(1200 * 936, 0), image = old;
	for (int y = 0; y < 12; y++)
		for (int x = 0; x < 12; x++)
			if ((x + y) % 2 == 0)
				image[(y * 78) * 1200 + x * 96] = 1;
	EXPECT_EQ(1u, sixelvnc::damageRegions(old, image, 1200, 936, 6, 13,
	    false, false).size());
}

TEST(Damage, KeepCompressibleBlankAreaInOneRectangle)
{
	std::vector<uint8_t> old(600 * 468, 255), image = old;
	image[80 * 600 + 20] = 0;
	image[400 * 600 + 580] = 0;
	EXPECT_EQ(1u, sixelvnc::damageRegions(old, image, 600, 468, 6, 13,
	    false, false).size());
}
