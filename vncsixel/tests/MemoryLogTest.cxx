/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Performance.h"
#include <core/Configuration.h>
#include <gtest/gtest.h>
#include <fstream>
#include <string>
#include <thread>
#include <unistd.h>
using namespace sixelvnc;
class MemorySamples : public testing::Test {
protected:
	std::string path;
	void SetUp() override {
		char name[] = "/tmp/vncsixel-memory-XXXXXX";
		int fd = mkstemp(name); ASSERT_GE(fd, 0); close(fd);
		path = name;
		ASSERT_TRUE(core::Configuration::setParam("PerfLog", ""));
		ASSERT_TRUE(core::Configuration::setParam("MemoryLog", path.c_str()));
		ASSERT_TRUE(core::Configuration::setParam("MemoryLogInterval", "1"));
	}
	void TearDown() override {
		core::Configuration::setParam("MemoryLog", "");
		unlink(path.c_str());
	}
};
TEST_F(MemorySamples, PeriodicAndFinalWithoutPerformanceLog)
{
	{
		Performance p;
		p.updates = 7; p.frames = 3;
		p.sampleMemory();
		std::this_thread::sleep_for(std::chrono::milliseconds(1100));
		p.sampleMemory();
		p.updates = 9;
	}
	std::ifstream input(path);
	std::string line;
	unsigned count = 0;
	while (std::getline(input, line)) {
		EXPECT_EQ(line.front(), '{'); EXPECT_EQ(line.back(), '}');
#ifdef __FreeBSD__
		EXPECT_NE(line.find("\"allocator_error\":0"), std::string::npos);
		EXPECT_NE(line.find("\"allocated_bytes\":"), std::string::npos);
#else
		EXPECT_EQ(line.find("allocated_bytes"), std::string::npos);
#endif
		if (count == 1)
			EXPECT_NE(line.find("\"updates\":7"), std::string::npos);
		if (count == 2)
			EXPECT_NE(line.find("\"updates\":9"), std::string::npos);
		count++;
	}
	EXPECT_EQ(count, 3U);
}
TEST_F(MemorySamples, RejectUnwritableDestination)
{
	ASSERT_TRUE(core::Configuration::setParam("MemoryLog", "/dev/null/log"));
	EXPECT_THROW(Performance{}, std::runtime_error);
}
TEST_F(MemorySamples, DisabledLoggingDoesNotOpenFile)
{
	ASSERT_TRUE(core::Configuration::setParam("MemoryLog", ""));
	{ Performance p; p.sampleMemory(); }
	std::ifstream input(path);
	EXPECT_EQ(input.peek(), std::ifstream::traits_type::eof());
}
