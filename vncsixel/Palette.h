/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_PALETTE_H
#define VNCSIXEL_PALETTE_H
#include <array>
#include <cstdlib>
#include <cstdint>

namespace sixelvnc {
inline uint8_t rgb332(uint8_t r, uint8_t g, uint8_t b)
{
	/* Quantize to the exact integer levels used by the fixed palette. */
	static const std::array<uint8_t, 256> levels = [] {
		std::array<uint8_t, 256> result = {};
		for (int value = 0; value < 256; value++) {
			int distance = 256;
			for (int i = 0; i < 8; i++) {
				int d = std::abs(value - i * 255 / 7);
				if (d < distance) {
					result[value] = i;
					distance = d;
				}
			}
		}
		return result;
	}();
	return (levels[r] << 5) | (levels[g] << 2) | ((b * 3 + 127) / 255);
}
}
#endif
