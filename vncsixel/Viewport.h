/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_VIEWPORT_H
#define VNCSIXEL_VIEWPORT_H
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <string>
#include <stdexcept>

namespace sixelvnc {
/* Origins are in virtual (scaled desktop) pixels, never framebuffer bytes. */
class Viewport {
public:
	int rw = 1, rh = 1, vw = 1, vh = 1, width = 1, height = 1;
	int x = 0, y = 0, percent = 0;
	bool follow = true;

	void configure(int remoteWidth, int remoteHeight, int tw, int th)
	{
		assert(remoteWidth > 0 && remoteHeight > 0 && tw > 0 && th > 0);
		if (remoteWidth == rw && remoteHeight == rh && tw == areaWidth &&
		    th == areaHeight && configuredPercent == percent)
			return;
		int cx = sourceX(width / 2), cy = sourceY(height / 2);
		rw = remoteWidth; rh = remoteHeight;
		areaWidth = tw; areaHeight = th; configuredPercent = percent;
		if (!percent) {
			double scale = std::min(1.0, std::min(double(tw) / rw,
			    double(th) / rh));
			vw = std::max(1, int(rw * scale));
			vh = std::max(1, int(rh * scale));
		} else {
			vw = std::max(1, int(int64_t(rw) * percent / 100));
			vh = std::max(1, int(int64_t(rh) * percent / 100));
		}
		width = std::min(tw, vw); height = std::min(th, vh);
		if (uint64_t(width) * height > 64ULL * 1024 * 1024)
			throw std::runtime_error("Visible viewport exceeds 64M pixels");
		center(cx, cy);
	}
	int sourceX(int dx) const { return int(int64_t(x + dx) * rw / vw); }
	int sourceY(int dy) const { return int(int64_t(y + dy) * rh / vh); }
	void center(int px, int py)
	{
		x = clamp(int64_t(px) * vw / rw - width / 2, vw - width);
		y = clamp(int64_t(py) * vh / rh - height / 2, vh - height);
	}
	void select(int value, int px, int py)
	{
		percent = value;
		configure(rw, rh, areaWidth, areaHeight);
		center(px, py);
	}
	void zoom(int direction, int px, int py)
	{
		const int steps[] = {25, 50, 75, 100, 150, 200, 300, 400};
		double current = percent ? percent : 100.0 * vw / rw;
		int next = percent;
		if (direction > 0) {
			for (int step : steps)
				if (step > current + .001) { next = step; break; }
		} else {
			for (int step : steps)
				if (step < current - .001) next = step;
		}
		if (next != percent) select(next, px, py);
	}
	void pan(int dx, int dy)
	{
		follow = false;
		x = clamp(int64_t(x) + dx * std::max(1, width / 4), vw - width);
		y = clamp(int64_t(y) + dy * std::max(1, height / 4), vh - height);
	}
	bool track(int px, int py)
	{
		if (!follow) return false;
		int oldX = x, oldY = y;
		int64_t dx = int64_t(px) * vw / rw - x;
		int64_t dy = int64_t(py) * vh / rh - y;
		/* Keep the middle 60% still; recenter only the crossed axis. */
		if (dx < width / 5 || dx >= width - width / 5)
			x = clamp(int64_t(px) * vw / rw - width / 2, vw - width);
		if (dy < height / 5 || dy >= height - height / 5)
			y = clamp(int64_t(py) * vh / rh - height / 2, vh - height);
		return x != oldX || y != oldY;
	}
	std::string label() const
	{
		return "Zoom " + (percent ? std::to_string(percent) + "%" :
		    "Fit (" + std::to_string(int(std::round(100.0 * vw / rw))) + "%)") +
		    " | Pan " + (follow ? "follow" : "fixed");
	}
private:
	static int clamp(int64_t value, int limit)
	{
		return int(std::max<int64_t>(0, std::min<int64_t>(limit, value)));
	}
	int areaWidth = 1, areaHeight = 1, configuredPercent = -1;
};
}
#endif
