/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Performance.h"
#include <core/Configuration.h>
#include <stdexcept>
#include <sys/resource.h>

namespace {
core::StringParameter perfLog("PerfLog",
    "Write numeric performance summary as JSON on exit", "");
double cpu(const rusage& usage)
{
	return usage.ru_utime.tv_sec + usage.ru_utime.tv_usec / 1e6 +
	    usage.ru_stime.tv_sec + usage.ru_stime.tv_usec / 1e6;
}
}
using namespace sixelvnc;
Performance::Performance() : start(std::chrono::steady_clock::now())
{
	rusage usage = {};
	getrusage(RUSAGE_SELF, &usage);
	initialCpu = cpu(usage);
	const char* path = perfLog;
	if (*path) {
		file = fopen(path, "w");
		if (!file)
			throw std::runtime_error("Cannot open performance log");
	}
}
Performance::~Performance()
{
	memory.sample(updates, frames, true);
	if (!file) return;
	rusage usage = {};
	getrusage(RUSAGE_SELF, &usage);
	double seconds = std::chrono::duration<double>(
	    std::chrono::steady_clock::now() - start).count();
	fprintf(file, "{\"seconds\":%.6f,\"cpu_seconds\":%.6f,"
	    "\"max_rss_kib\":%ld,\"updates\":%llu,\"frames\":%llu,"
	    "\"encoded_bytes\":%llu,\"skipped_frames\":%llu,"
	    "\"regions\":%llu,\"full_frames\":%llu,\"partial_frames\":%llu,\"encoded_pixels\":%llu,"
	    "\"tty_bytes\":%llu,\"peak_queue_bytes\":%llu,\"blocked_writes\":%llu,"
	    "\"cursor_samples\":%llu,"
	    "\"snapshot_ms\":%.6f,\"encode_ms\":%.6f,\"max_encode_ms\":%.6f,\"palette_ms\":%.6f,"
	    "\"remote_width\":%d,\"remote_height\":%d,\"width\":%d,\"height\":%d}\n",
	    seconds, cpu(usage) - initialCpu, usage.ru_maxrss,
	    (unsigned long long)updates, (unsigned long long)frames,
	    (unsigned long long)encodedBytes, (unsigned long long)skipped,
	    (unsigned long long)regions, (unsigned long long)fullFrames, (unsigned long long)partialFrames,
	    (unsigned long long)encodedPixels,
	    (unsigned long long)ttyBytes, (unsigned long long)peakQueueBytes,
	    (unsigned long long)blockedWrites,
	    (unsigned long long)cursorSamples,
	    snapshotMs, encodeMs, maxEncodeMs, paletteMs, remoteWidth, remoteHeight,
	    width, height);
	fclose(file);
}
