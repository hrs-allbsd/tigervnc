/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_MEMORYLOG_H
#define VNCSIXEL_MEMORYLOG_H
#include <chrono>
#include <cstdint>
#include <cstdio>

namespace sixelvnc {
class MemoryLog {
public:
	MemoryLog();
	~MemoryLog();
	MemoryLog(const MemoryLog&) = delete;
	MemoryLog& operator=(const MemoryLog&) = delete;
	void sample(uint64_t, uint64_t, bool = false);
private:
	FILE* file = nullptr;
	std::chrono::steady_clock::time_point start, next;
};
}
#endif
