/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Cursor.h"
#include <gtest/gtest.h>
#include <array>
#include <climits>
#include <vector>

/* Full-image reference intentionally does not compute a clipped cursor box. */
static void compare(int rw, int rh, int dw, int dh, int px, int py,
    int hx, int hy, int vx = 0, int vy = 0, int vw = 0, int vh = 0)
{
	if (!vw) vw = dw;
	if (!vh) vh = dh;
	constexpr int cw = 15, ch = 11;
	std::vector<uint8_t> cursor(cw * ch * 4);
	std::vector<uint8_t> actual(dw * dh * 3 + 32, 0xa5);
	for (size_t i = 0; i < cursor.size(); i++)
		cursor[i] = (i * 67) & 255;
	for (int i = 0; i < dw * dh * 3; i++)
		actual[16 + i] = (i * 37) & 255;
	auto expected = actual;
	uint64_t samples = 0;
	for (int y = 0; y < dh; y++) {
		for (int x = 0; x < dw; x++) {
			int64_t cx = int64_t(x + vx) * rw / vw - int64_t(px) + hx;
			int64_t cy = int64_t(y + vy) * rh / vh - int64_t(py) + hy;
			if (cx < 0 || cy < 0 || cx >= cw || cy >= ch)
				continue;
			samples++;
			const uint8_t* fg = cursor.data() + (cy * cw + cx) * 4;
			uint8_t* bg = expected.data() + 16 + (y * dw + x) * 3;
			for (int c = 0; c < 3; c++)
				bg[c] = (unsigned(bg[c]) * (255 - fg[3]) +
				    unsigned(fg[c]) * fg[3]) / 255;
		}
	}
	EXPECT_EQ(samples, sixelvnc::compositeCursor(actual.data() + 16,
	    dw, dh, rw, rh, cursor.data(), cw, ch, hx, hy, px, py, vx, vy, vw, vh));
	EXPECT_TRUE(actual == expected); /* Includes both buffer guards. */
}

TEST(Cursor, SamplingAndClippingMatchFullScan)
{
	for (auto size : {std::array<int, 4>{599, 431, 599, 431},
	    {6016, 3384, 846, 475}, {101, 73, 17, 13}, {7, 5, 13, 11}}) {
		for (auto position : {std::array<int, 2>{0, 0}, {1, 1},
		    {size[0] / 2, size[1] / 2}, {size[0] - 1, size[1] - 1},
		    {-20, -20}, {size[0] + 20, size[1] + 20},
		    {INT_MIN, INT_MAX}, {INT_MAX, INT_MIN}}) {
			for (auto hotspot : {std::array<int, 2>{0, 0}, {7, 5}, {14, 10}}) {
				SCOPED_TRACE(::testing::Message() << size[0] << 'x' << size[1]
				    << " position " << position[0] << ',' << position[1]
				    << " hotspot " << hotspot[0] << ',' << hotspot[1]);
				compare(size[0], size[1], size[2], size[3],
				    position[0], position[1], hotspot[0], hotspot[1]);
			}
		}
	}
}
TEST(Cursor, InvisibleBetweenSamples)
{
	std::vector<uint8_t> rgb(3 * 3 * 3, 19), original = rgb;
	uint8_t cursor[] = {255, 0, 0, 255};
	EXPECT_EQ(0U, sixelvnc::compositeCursor(rgb.data(), 3, 3, 101, 101,
	    cursor, 1, 1, 0, 0, 50, 50));
	EXPECT_EQ(original, rgb);
}
TEST(Cursor, TransparentSamplesLeaveBackground)
{
	uint8_t rgb[] = {11, 77, 199}, cursor[] = {255, 255, 255, 0};
	EXPECT_EQ(1U, sixelvnc::compositeCursor(rgb, 1, 1, 1, 1,
	    cursor, 1, 1, 0, 0, 0, 0));
	EXPECT_EQ(11, rgb[0]);
	EXPECT_EQ(77, rgb[1]);
	EXPECT_EQ(199, rgb[2]);
}
TEST(Cursor, SmallShapeLimitsWork)
{
	std::vector<uint8_t> rgb(846 * 774 * 3), cursor(15 * 11 * 4, 255);
	EXPECT_EQ(165U, sixelvnc::compositeCursor(rgb.data(), 846, 774,
	    846, 774, cursor.data(), 15, 11, 7, 5, 400, 300));
}

TEST(Cursor, ViewportCropAndMagnificationMatchFullScan)
{
	for (int scale : {1, 2, 4})
		for (int vx : {0, 25, 70})
			for (int vy : {0, 17, 40})
				for (int px : {-10, 0, 35, 90, 110})
					compare(101, 73, 29, 23, px, 35, 7, 5,
					    vx, vy, 101 * scale, 73 * scale);
}
