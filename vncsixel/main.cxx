/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Terminal.h"
#include <cstdio>
#include <exception>
int main()
{
	try {
		sixelvnc::Terminal terminal;
		terminal.enter();
		fprintf(stderr, "SIXEL terminal: %dx%d, cells %dx%d, pixel mouse %s\n",
		    terminal.width, terminal.height, terminal.cellWidth,
		    terminal.cellHeight, terminal.pixelMouse ? "yes" : "no");
	} catch (const std::exception& e) {
		fprintf(stderr, "vncsixel: %s\n", e.what());
		return 1;
	}
	return 0;
}
