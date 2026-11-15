/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Snapshot.h"
#include <rfb/PixelFormat.h>
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

static void
reference(const rfb::PixelFormat& pf, uint8_t* rgb, const uint8_t* pixels,
    int stride, int rw, int rh, int dw, int dh)
{
	for (int y = 0; y < dh; y++) {
		int sy = int64_t(y) * rh / dh;
		for (int x = 0; x < dw; x++) {
			int sx = int64_t(x) * rw / dw;
			pf.rgbFromBuffer(rgb + (size_t(y) * dw + x) * 3,
			    pixels + (size_t(sy) * stride + sx) * 4, 1);
		}
	}
}

int
main(int argc, char** argv)
{
	long samples = 9;
	if (argc == 2) {
		char* end;
		errno = 0;
		samples = strtol(argv[1], &end, 10);
		if (errno || !*argv[1] || *end)
			samples = 0;
	}
	if (argc > 2 || samples < 3 || samples > 31) {
		fprintf(stderr, "Usage: snapshot-benchmark [samples:3..31]\n");
		return 1;
	}
	const rfb::PixelFormat pf(32, 24, false, true, 255, 255, 255, 16, 8, 0);
	struct Dimensions { int rw, rh, dw, dh; };
	const Dimensions cases[] = {{599, 431, 599, 431},
	    {6016, 3384, 846, 476}, {5120, 4680, 846, 774},
	    {7680, 4320, 846, 475}};
	printf("{\"samples\":%ld,\"cases\":[", samples);
	bool first = true;
	for (const auto& d : cases) {
		int stride = d.rw + 7;
		std::vector<uint8_t> input(size_t(stride) * d.rh * 4);
		for (size_t i = 0; i < input.size(); i++)
			input[i] = (i * 37 + i / 7) & 255;
		std::vector<uint8_t> actual(size_t(d.dw) * d.dh * 3);
		std::vector<uint8_t> expected(actual.size());
		std::vector<double> timings[2];
		/* Warm both paths, then rotate timed order. */
		for (int sample = -1; sample < samples; sample++) {
			for (int offset = 0; offset < 2; offset++) {
				int mode = (sample + offset + 2) % 2;
				auto start = std::chrono::steady_clock::now();
				if (mode == 0)
					reference(pf, expected.data(), input.data(), stride,
					    d.rw, d.rh, d.dw, d.dh);
				else
					sixelvnc::sampleBGRX(actual.data(), input.data(), stride,
					    d.rw, d.rh, d.dw, d.dh);
				double elapsed = std::chrono::duration<double, std::milli>(
				    std::chrono::steady_clock::now() - start).count();
				if (sample >= 0)
					timings[mode].push_back(elapsed);
			}
			if (actual != expected) {
				fprintf(stderr, "Snapshot pixel mismatch\n");
				return 1;
			}
		}
		printf("%s{\"source_width\":%d,\"source_height\":%d,"
		    "\"display_width\":%d,\"display_height\":%d", first ? "" : ",",
		    d.rw, d.rh, d.dw, d.dh);
		first = false;
		for (int mode = 0; mode < 2; mode++) {
			printf(",\"%s\":{\"samples_ms\":[", mode ? "optimized" : "reference");
			for (size_t i = 0; i < timings[mode].size(); i++)
				printf("%s%.6f", i ? "," : "", timings[mode][i]);
			auto sorted = timings[mode];
			std::sort(sorted.begin(), sorted.end());
			size_t n = sorted.size();
			double median = (sorted[(n - 1) / 2] + sorted[n / 2]) / 2;
			printf("],\"median_ms\":%.6f}", median);
		}
		printf("}");
	}
	printf("],\"scope\":\"RGB sampling only; excludes source decoding, "
	    "output allocation, quantization, SIXEL encoding and terminal paint\"}\n");
	return 0;
}
