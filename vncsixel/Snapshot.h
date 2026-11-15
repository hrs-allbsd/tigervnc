/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_SNAPSHOT_H
#define VNCSIXEL_SNAPSHOT_H
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace sixelvnc {
/*
 * Sample the frontend's fixed little-endian 32bpp, RGB888 framebuffer.
 * Memory bytes are B,G,R,X regardless of host byte order.  Stride is in
 * pixels.  The caller supplies valid storage and positive dimensions;
 * optional origins and virtual dimensions select a scaled viewport.
 */
inline void sampleBGRX(uint8_t* rgb, const uint8_t* pixels, int stride,
    int rw, int rh, int dw, int dh, int ox = 0, int oy = 0,
    int vw = 0, int vh = 0)
{
	assert(rw > 0 && rh > 0 && dw > 0 && dh > 0);
	if (!vw) vw = dw;
	if (!vh) vh = dh;
	assert(stride >= rw && ox >= 0 && oy >= 0);
	assert(ox + dw <= vw && oy + dh <= vh);
	std::vector<size_t> columns(dw);
	for (int x = 0; x < dw; x++)
		columns[x] = size_t(int64_t(x + ox) * rw / vw) * 4;
	for (int y = 0; y < dh; y++) {
		const uint8_t* row = pixels + size_t(int64_t(y + oy) * rh / vh) *
		    stride * 4;
		for (int x = 0; x < dw; x++) {
			const uint8_t* pixel = row + columns[x];
			*rgb++ = pixel[2];
			*rgb++ = pixel[1];
			*rgb++ = pixel[0];
		}
	}
}
}
#endif
