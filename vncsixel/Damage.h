/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_DAMAGE_H
#define VNCSIXEL_DAMAGE_H
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace sixelvnc {
struct DamageRect {
	int x, y, width, height;
};
inline DamageRect damage(const std::vector<uint8_t>& previous,
    const std::vector<uint8_t>& current, int width, int height,
    int cellWidth, int cellHeight, bool force)
{
	if (width <= 0 || height <= 0 || cellWidth <= 0 || cellHeight <= 0 ||
	    current.size() != static_cast<size_t>(width) * height)
		throw std::invalid_argument("Invalid damage image dimensions");
	if (force || previous.size() != current.size())
		return {0, 0, width, height};
	if (previous == current)
		return {0, 0, 0, 0};
	int left = width, top = height, right = 0, bottom = 0;
	for (int y = 0; y < height; y++) {
		for (int x = 0; x < width; x++) {
			size_t i = static_cast<size_t>(y) * width + x;
			if (previous[i] == current[i]) continue;
			left = std::min(left, x);
			top = std::min(top, y);
			right = std::max(right, x + 1);
			bottom = std::max(bottom, y + 1);
		}
	}
	/* CUP positions require cell boundaries; SIXEL bands require six. */
	int a = cellHeight, b = 6;
	while (b) {
		int remainder = a % b;
		a = b;
		b = remainder;
	}
	int band = cellHeight / a * 6;
	left = left / cellWidth * cellWidth;
	top = top / band * band;
	right = std::min(width, ((right - 1) / cellWidth + 1) * cellWidth);
	bottom = std::min(height, ((bottom - 1) / band + 1) * band);
	return {left, top, right - left, bottom - top};
}
}
#endif
