/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Snapshot.h"
#include <rfb/PixelFormat.h>
#include <gtest/gtest.h>
#include <array>

TEST(Snapshot, MatchesPixelFormatWithPaddingAndOddScales)
{
	rfb::PixelFormat pf(32, 24, false, true, 255, 255, 255, 16, 8, 0);
	/* All small dimensions, including single-pixel axes and no resize. */
	for (int rw = 1; rw <= 13; rw++) {
		for (int rh = 1; rh <= 11; rh++) {
			int stride = rw + 3;
			std::vector<uint8_t> input(size_t(stride) * rh * 4);
			for (size_t i = 0; i < input.size(); i++)
				input[i] = (i * 37 + i / 7) & 255;
			for (int dw = 1; dw <= rw; dw++) {
				for (int dh = 1; dh <= rh; dh++) {
					std::vector<uint8_t> actual(size_t(dw) * dh * 3);
					std::vector<uint8_t> expected(actual.size());
					/* Use the old generic conversion as an oracle. */
					for (int y = 0; y < dh; y++) {
						for (int x = 0; x < dw; x++) {
							int sx = x * rw / dw, sy = y * rh / dh;
							pf.rgbFromBuffer(expected.data() +
							    (size_t(y) * dw + x) * 3,
							    input.data() + (size_t(sy) * stride + sx) * 4, 1);
						}
					}
					sixelvnc::sampleBGRX(actual.data(), input.data(), stride,
					    rw, rh, dw, dh);
					ASSERT_EQ(actual, expected) << rw << 'x' << rh << " -> "
					    << dw << 'x' << dh;
				}
			}
		}
	}
}
TEST(Snapshot, KnownCoordinatesAndUnusedByte)
{
	std::vector<uint8_t> input(9 * 5 * 4, 0xee);
	for (int y = 0; y < 5; y++) {
		for (int x = 0; x < 7; x++) {
			size_t i = (y * 9 + x) * 4;
			input[i] = x + y; input[i + 1] = y;
			input[i + 2] = x; input[i + 3] = 0xff;
		}
	}
	std::array<uint8_t, 20> output;
	output.fill(0xcc);
	sixelvnc::sampleBGRX(output.data() + 1, input.data(), 9, 7, 5, 3, 2);
	std::array<uint8_t, 20> expected = {0xcc,
	    0, 0, 0, 2, 0, 2, 4, 0, 4, 0, 2, 2, 2, 2, 4, 4, 2, 6, 0xcc};
	EXPECT_EQ(output, expected);
}
