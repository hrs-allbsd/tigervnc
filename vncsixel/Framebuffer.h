/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_FRAMEBUFFER_H
#define VNCSIXEL_FRAMEBUFFER_H
#include <cstdint>
#include <stdexcept>
#include <string>

namespace sixelvnc {
inline void checkFramebufferSize(int w, int h)
{
	/* Bound the 32-bit pixel buffer to 256 MiB, including on resize. */
	if (w <= 0 || h <= 0 ||
	    static_cast<uint64_t>(w) * static_cast<uint64_t>(h) >
	    64ULL * 1024 * 1024)
		throw std::runtime_error("Remote framebuffer " +
		    std::to_string(w) + "x" + std::to_string(h) +
		    " exceeds 64M pixels (256 MiB per framebuffer)");
}
}
#endif
