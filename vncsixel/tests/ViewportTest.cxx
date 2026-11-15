/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Viewport.h"
#include "Snapshot.h"
#include <gtest/gtest.h>
#include <vector>
using namespace sixelvnc;

TEST(Viewport, FitNeverUpscalesAndPreservesSampling)
{
	Viewport v;
	v.configure(6016, 3384, 846, 774);
	EXPECT_EQ(v.width, 846); EXPECT_EQ(v.height, 475);
	EXPECT_EQ(v.x, 0); EXPECT_EQ(v.y, 0);
	EXPECT_EQ(v.sourceX(845), int(int64_t(845) * 6016 / 846));
	v.configure(32, 20, 846, 774);
	EXPECT_EQ(v.width, 32); EXPECT_EQ(v.height, 20);
}
TEST(Viewport, ZoomStepsAnchorAndClamp)
{
	Viewport v;
	v.configure(2000, 1000, 500, 250);
	v.zoom(1, 1000, 500);
	EXPECT_EQ(v.percent, 50);
	EXPECT_EQ(v.sourceX(250), 1000); EXPECT_EQ(v.sourceY(125), 500);
	v.select(100, 1999, 999);
	EXPECT_EQ(v.x, 1500); EXPECT_EQ(v.y, 750);
	for (int i = 0; i < 20; i++) v.zoom(1, 0, 0);
	EXPECT_EQ(v.percent, 400); EXPECT_EQ(v.x, 0); EXPECT_EQ(v.y, 0);
	for (int i = 0; i < 20; i++) v.zoom(-1, 0, 0);
	EXPECT_EQ(v.percent, 25);
	v.select(0, 0, 0);
	EXPECT_EQ(v.x, 0); EXPECT_EQ(v.width, 500);
	v.configure(10000, 10000, 100, 100);
	v.zoom(-1, 0, 0);
	EXPECT_EQ(v.percent, 0); /* Fit below the smallest fixed step. */
}
TEST(Viewport, ManualPanDisablesFollowAndResizeClamps)
{
	Viewport v;
	v.configure(2000, 1000, 500, 250);
	v.select(100, 0, 0);
	v.pan(1, 1);
	EXPECT_FALSE(v.follow); EXPECT_EQ(v.x, 125); EXPECT_EQ(v.y, 62);
	EXPECT_FALSE(v.track(1999, 999)); EXPECT_EQ(v.x, 125);
	v.follow = true;
	EXPECT_TRUE(v.track(1999, 999));
	EXPECT_EQ(v.x, 1500); EXPECT_EQ(v.y, 750);
	EXPECT_FALSE(v.track(1750, 875));
	v.configure(100, 50, 500, 250);
	EXPECT_EQ(v.x, 0); EXPECT_EQ(v.y, 0);
	EXPECT_EQ(v.width, 100); EXPECT_EQ(v.height, 50);
}
TEST(Viewport, SnapshotAndMouseUseSameSourcePixels)
{
	const int rw = 17, rh = 13, stride = 19;
	std::vector<uint8_t> pixels(stride * rh * 4);
	for (int y = 0; y < rh; y++)
		for (int x = 0; x < rw; x++) {
			pixels[(y * stride + x) * 4] = x;
			pixels[(y * stride + x) * 4 + 1] = y;
			pixels[(y * stride + x) * 4 + 2] = x + y;
		}
	for (int percent : {0, 25, 50, 75, 100, 150, 200, 300, 400}) {
		Viewport v;
		v.configure(rw, rh, 11, 9);
		v.select(percent, 12, 9);
		v.pan(1, 1);
		std::vector<uint8_t> rgb(v.width * v.height * 3 + 2, 0xa5);
		sampleBGRX(rgb.data() + 1, pixels.data(), stride, rw, rh,
		    v.width, v.height, v.x, v.y, v.vw, v.vh);
		for (int y = 0; y < v.height; y++)
			for (int x = 0; x < v.width; x++) {
				int sx = v.sourceX(x), sy = v.sourceY(y);
				ASSERT_GE(sx, 0); ASSERT_LT(sx, rw);
				ASSERT_GE(sy, 0); ASSERT_LT(sy, rh);
				EXPECT_EQ(rgb[1 + (y * v.width + x) * 3], sx + sy);
				EXPECT_EQ(rgb[2 + (y * v.width + x) * 3], sy);
				EXPECT_EQ(rgb[3 + (y * v.width + x) * 3], sx);
			}
		EXPECT_EQ(rgb.front(), 0xa5); EXPECT_EQ(rgb.back(), 0xa5);
	}
}

TEST(Viewport, LargeVirtualDesktopDoesNotAllocateItsFullArea)
{
	Viewport v;
	v.configure(65535, 1024, 8192, 4096);
	v.select(400, 65534, 1023);
	EXPECT_EQ(v.vw, 262140);
	EXPECT_EQ(v.width, 8192); EXPECT_EQ(v.height, 4096);
	EXPECT_EQ(v.sourceX(v.width - 1), 65534);
	v.select(0, 0, 0);
	v.configure(8192, 8192, 16384, 16384);
	EXPECT_THROW(v.select(400, 0, 0), std::runtime_error);
}
