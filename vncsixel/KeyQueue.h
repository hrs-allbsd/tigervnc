/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_KEYQUEUE_H
#define VNCSIXEL_KEYQUEUE_H
#include "Input.h"
#include <algorithm>
#include <chrono>
#include <deque>
#include <stdexcept>

namespace sixelvnc {
class KeyQueue {
public:
	using Clock = std::chrono::steady_clock;
	using Time = Clock::time_point;
	static constexpr size_t limit = 8192;
	explicit KeyQueue(int rate)
	{
		if (rate < 1 || rate > 10000)
			throw std::invalid_argument("PasteRate must be between 1 and 10000");
		interval = std::chrono::nanoseconds(1000000000 / rate);
	}
	bool push(const InputEvent& event)
	{
		if (keys.size() == limit) return false;
		keys.push_back(event);
		return true;
	}
	bool take(Time now, InputEvent& event)
	{
		if (keys.empty() || (keys.front().pasted && now < next))
			return false;
		event = keys.front();
		keys.pop_front();
		/* Do not accumulate credits while rendering or the server stalls. */
		if (event.pasted) next = now + interval;
		return true;
	}
	int timeout(Time now) const
	{
		if (keys.empty()) return 20;
		if (!keys.front().pasted || now >= next) return 1;
		auto us = std::chrono::duration_cast<std::chrono::microseconds>(next - now).count();
		return static_cast<int>(std::min<int64_t>(20, std::max<int64_t>(1, (us + 999) / 1000)));
	}
	void clear() { keys.clear(); next = {}; }
	size_t size() const { return keys.size(); }
private:
	std::deque<InputEvent> keys;
	Time next = {};
	std::chrono::nanoseconds interval;
};
}
#endif
