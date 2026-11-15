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
 * upscaling is not used by the viewer.
 */
inline void sampleBGRX(uint8_t* rgb, const uint8_t* pixels, int stride,
    int rw, int rh, int dw, int dh)
{
	assert(rw > 0 && rh > 0 && dw > 0 && dh > 0);
	assert(stride >= rw && dw <= rw && dh <= rh);
	std::vector<size_t> columns(dw);
	for (int x = 0; x < dw; x++)
		columns[x] = size_t(int64_t(x) * rw / dw) * 4;
	for (int y = 0; y < dh; y++) {
		const uint8_t* row = pixels + size_t(int64_t(y) * rh / dh) *
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
