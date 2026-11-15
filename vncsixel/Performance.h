/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_PERFORMANCE_H
#define VNCSIXEL_PERFORMANCE_H
#include <chrono>
#include <cstdint>
#include <cstdio>

namespace sixelvnc {
class Performance {
public:
	Performance();
	~Performance();
	uint64_t updates = 0, frames = 0, encodedBytes = 0, skipped = 0;
	uint64_t fullFrames = 0, partialFrames = 0, encodedPixels = 0;
	uint64_t ttyBytes = 0, peakQueueBytes = 0, blockedWrites = 0;
	double snapshotMs = 0, encodeMs = 0, maxEncodeMs = 0;
	int remoteWidth = 0, remoteHeight = 0, width = 0, height = 0;
private:
	FILE* file = nullptr;
	std::chrono::steady_clock::time_point start;
	double initialCpu = 0;
};
}
#endif
