/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_CURSOR_H
#define VNCSIXEL_CURSOR_H
#include <algorithm>
#include <cstdint>

namespace sixelvnc {
/* Composite straight RGBA after nearest-neighbor framebuffer sampling. */
inline uint64_t compositeCursor(uint8_t* rgb, int dw, int dh, int rw, int rh,
    const uint8_t* rgba, int cw, int ch, int hx, int hy, int px, int py)
{
	if (dw <= 0 || dh <= 0 || rw <= 0 || rh <= 0 || cw <= 0 || ch <= 0)
		return 0;
	int64_t ox = int64_t(px) - hx, oy = int64_t(py) - hy;
	int64_t left = std::max<int64_t>(0, ox);
	int64_t top = std::max<int64_t>(0, oy);
	int64_t right = std::min<int64_t>(rw, ox + cw);
	int64_t bottom = std::min<int64_t>(rh, oy + ch);
	if (left >= right || top >= bottom)
		return 0;
	/* Invert source sampling floor(x * rw / dw) with ceiling bounds. */
	int x0 = (left * dw + rw - 1) / rw;
	int y0 = (top * dh + rh - 1) / rh;
	int x1 = (right * dw + rw - 1) / rw;
	int y1 = (bottom * dh + rh - 1) / rh;
	for (int y = y0; y < y1; y++) {
		int64_t cy = int64_t(y) * rh / dh - oy;
		for (int x = x0; x < x1; x++) {
			int64_t cx = int64_t(x) * rw / dw - ox;
			const uint8_t* fg = rgba + (cy * cw + cx) * 4;
			if (!fg[3])
				continue;
			uint8_t* bg = rgb + (int64_t(y) * dw + x) * 3;
			for (int c = 0; c < 3; c++)
				bg[c] = (unsigned(bg[c]) * (255 - fg[3]) +
				    unsigned(fg[c]) * fg[3]) / 255;
		}
	}
	return uint64_t(x1 - x0) * (y1 - y0);
}
}
#endif
