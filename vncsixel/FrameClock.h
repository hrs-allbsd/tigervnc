/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_FRAMECLOCK_H
#define VNCSIXEL_FRAMECLOCK_H
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <stdexcept>

namespace sixelvnc {
class FrameClock {
public:
	using Clock = std::chrono::steady_clock;
	using Time = Clock::time_point;
	explicit FrameClock(int fps)
	{
		if (fps < 1 || fps > 60)
			throw std::invalid_argument("MaxFPS must be between 1 and 60");
		interval = std::chrono::nanoseconds(1000000000 / fps);
	}
	bool due(Time now) const { return now >= next; }
	void rendered(Time start) { next = start + interval; }
	int pollTimeout(Time now) const
	{
		/* An expired deadline with no dirty image must not busy-poll. */
		if (due(now)) return 20;
		auto us = std::chrono::duration_cast<std::chrono::microseconds>(next - now).count();
		return static_cast<int>(std::min<int64_t>(20, std::max<int64_t>(1, (us + 999) / 1000)));
	}
private:
	Time next = {};
	std::chrono::nanoseconds interval;
};
}
#endif
