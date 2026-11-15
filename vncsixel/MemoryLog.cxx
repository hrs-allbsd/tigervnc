/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "MemoryLog.h"
#include <core/Configuration.h>
#include <cerrno>
#include <stdexcept>
#ifdef __FreeBSD__
#include <malloc_np.h>
#endif

namespace {
core::StringParameter memoryLogPath("MemoryLog",
    "Write numeric allocator samples as JSON lines", "");
core::IntParameter memoryLogInterval("MemoryLogInterval",
    "Seconds between allocator samples", 5, 1, 3600);
}
using namespace sixelvnc;
MemoryLog::MemoryLog() : start(std::chrono::steady_clock::now()), next(start)
{
	const char* path = memoryLogPath;
	if (!*path)
		return;
	file = fopen(path, "w");
	if (!file)
		throw std::runtime_error("Cannot open memory log");
	sample(0, 0, true);
}
MemoryLog::~MemoryLog()
{
	if (file)
		fclose(file);
}
bool MemoryLog::due() const
{
	return file && std::chrono::steady_clock::now() >= next;
}
void MemoryLog::sample(uint64_t updates, uint64_t frames, bool force,
    uint64_t decoderBytes)
{
	if (!file)
		return;
	auto now = std::chrono::steady_clock::now();
	if (!force && now < next)
		return;
	next = now + std::chrono::seconds(memoryLogInterval);
	int error = ENOTSUP;
	size_t values[5] = {};
#ifdef __FreeBSD__
	uint64_t epoch = 1;
	size_t size = sizeof(epoch);
	error = mallctl("epoch", &epoch, &size, &epoch, sizeof(epoch));
	const char* names[] = {"stats.allocated", "stats.active",
	    "stats.resident", "stats.mapped", "stats.retained"};
	for (int i = 0; !error && i < 5; i++) {
		size = sizeof(values[i]);
		error = mallctl(names[i], &values[i], &size, nullptr, 0);
	}
#endif
	double seconds = std::chrono::duration<double>(now - start).count();
	fprintf(file, "{\"seconds\":%.6f,\"updates\":%llu,\"frames\":%llu,"
	    "\"allocator_error\":%d", seconds, (unsigned long long)updates,
	    (unsigned long long)frames, error);
	if (!error)
		fprintf(file, ",\"allocated_bytes\":%zu,\"active_bytes\":%zu,"
		    "\"resident_bytes\":%zu,\"mapped_bytes\":%zu,"
		    "\"retained_bytes\":%zu", values[0], values[1], values[2],
		    values[3], values[4]);
	fprintf(file, ",\"decoder_buffer_bytes\":%llu}\n",
	    (unsigned long long)decoderBytes);
	fflush(file);
}
