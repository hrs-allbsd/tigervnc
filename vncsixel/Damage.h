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
inline std::vector<DamageRect> damageRegions(const std::vector<uint8_t>& previous,
    const std::vector<uint8_t>& current, int width, int height,
    int cellWidth, int cellHeight, bool force, bool single, int paletteColors = 256)
{
	DamageRect bounds = damage(previous, current, width, height,
	    cellWidth, cellHeight, force);
	if (!bounds.width) return {};
	if (force || single || previous.size() != current.size()) return {bounds};
	int a = cellHeight, b = 6;
	while (b) {
		int remainder = a % b;
		a = b;
		b = remainder;
	}
	int tileWidth = cellWidth * 16, tileHeight = cellHeight / a * 6;
	std::vector<DamageRect> result;
	for (int y = bounds.y; y < bounds.y + bounds.height; y += tileHeight) {
		int h = std::min(tileHeight, height - y);
		int run = -1, end = bounds.x;
		auto finish = [&] {
			if (run < 0) return;
			for (auto& r : result) {
				if (r.x == run && r.width == end - run &&
				    r.y + r.height == y) {
					r.height += h;
					run = -1;
					return;
				}
			}
			result.push_back({run, y, end - run, h});
			run = -1;
		};
		for (int x = bounds.x; x < bounds.x + bounds.width; x += tileWidth) {
			int w = std::min(tileWidth, width - x);
			bool changed = false;
			for (int row = y; row < y + h && !changed; row++) {
				size_t i = static_cast<size_t>(row) * width + x;
				changed = !std::equal(current.begin() + i,
				    current.begin() + i + w, previous.begin() + i);
			}
			if (changed) {
				if (run < 0) run = x;
				end = x + w;
			} else {
				finish();
			}
		}
		finish();
		if (result.size() > 32) return {bounds};
	}
	uint64_t pixels = 0;
	for (const auto& r : result)
		pixels += static_cast<uint64_t>(r.width) * r.height;
	/* Avoid fragmentation when additional palette definitions outweigh
	 * the saved area.  This conservative estimate is not a byte count. */
	if (pixels + (result.size() - 1) * 4096 >=
	    static_cast<uint64_t>(bounds.width) * bounds.height)
		return {bounds};
	/* Long single-color runs compress well.  Estimate row/color transitions
	 * and per-DCS palette cost rather than preferring fewer pixels alone. */
	auto cost = [&](const DamageRect& r) {
		uint64_t value = paletteColors * 16 + 128;
		for (int y = r.y; y < r.y + r.height; y++) {
			value += 2;
			size_t row = static_cast<size_t>(y) * width;
			for (int x = r.x + 1; x < r.x + r.width; x++)
				value += current[row + x] != current[row + x - 1];
		}
		return value;
	};
	uint64_t separateCost = 0;
	for (const auto& r : result) separateCost += cost(r);
	if (separateCost >= cost(bounds)) return {bounds};
	return result;
}

}
#endif
