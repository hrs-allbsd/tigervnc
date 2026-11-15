/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "FrameClock.h"
#include <gtest/gtest.h>
using sixelvnc::FrameClock;
using namespace std::chrono;

TEST(FrameClock, IdleDoesNotPostponeNextFrame)
{
	FrameClock timer(10);
	FrameClock::Time start = {};
	timer.rendered(start);
	EXPECT_FALSE(timer.due(start + milliseconds(99)));
	EXPECT_TRUE(timer.due(start + milliseconds(100)));
	/* Unchanged/blocked frames do not call rendered(). */
	EXPECT_TRUE(timer.due(start + seconds(5)));
	EXPECT_EQ(20, timer.pollTimeout(start + seconds(5)));
}
TEST(FrameClock, PollWakesAtFrameDeadline)
{
	FrameClock timer(10);
	FrameClock::Time start = {};
	timer.rendered(start);
	EXPECT_EQ(20, timer.pollTimeout(start + milliseconds(10)));
	EXPECT_EQ(5, timer.pollTimeout(start + milliseconds(95)));
	EXPECT_EQ(1, timer.pollTimeout(start + microseconds(99999)));
}
TEST(FrameClock, RenderRate)
{
	FrameClock timer(30);
	FrameClock::Time start = {};
	timer.rendered(start);
	EXPECT_FALSE(timer.due(start + milliseconds(33)));
	EXPECT_TRUE(timer.due(start + milliseconds(34)));
	timer.rendered(start + seconds(1));
	EXPECT_FALSE(timer.due(start + seconds(1) + milliseconds(20)));
	EXPECT_TRUE(timer.due(start + seconds(1) + milliseconds(34)));
	EXPECT_THROW(FrameClock(0), std::invalid_argument);
	EXPECT_THROW(FrameClock(61), std::invalid_argument);
}
