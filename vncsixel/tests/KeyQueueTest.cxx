/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "KeyQueue.h"
#include <gtest/gtest.h>
using namespace sixelvnc;
using namespace std::chrono;
TEST(KeyQueue, RateAndOrder)
{
	KeyQueue queue(100);
	InputEvent a, b, out;
	a.key = 'a'; a.pasted = true;
	b.key = 'b'; b.pasted = true;
	queue.push(a); queue.push(b);
	a.pasted = false; a.key = 'x'; queue.push(a);
	auto now = KeyQueue::Time{};
	ASSERT_TRUE(queue.take(now, out)); EXPECT_EQ(out.key, 'a');
	EXPECT_FALSE(queue.take(now + milliseconds(9), out));
	ASSERT_TRUE(queue.take(now + milliseconds(10), out)); EXPECT_EQ(out.key, 'b');
	ASSERT_TRUE(queue.take(now + milliseconds(10), out)); EXPECT_EQ(out.key, 'x');
	EXPECT_FALSE(queue.take(now + milliseconds(10), out));
}
TEST(KeyQueue, NoCatchupBurst)
{
	KeyQueue queue(100);
	InputEvent e, out; e.pasted = true;
	queue.push(e); queue.push(e); queue.push(e);
	auto now = KeyQueue::Time{};
	ASSERT_TRUE(queue.take(now, out));
	ASSERT_TRUE(queue.take(now + seconds(5), out));
	EXPECT_FALSE(queue.take(now + seconds(5), out));
	EXPECT_EQ(queue.timeout(now + seconds(5)), 10);
}
TEST(KeyQueue, BoundedAndCancelled)
{
	KeyQueue queue(1);
	InputEvent e, out; e.pasted = true;
	for (size_t i = 0; i < KeyQueue::limit; i++) ASSERT_TRUE(queue.push(e));
	EXPECT_FALSE(queue.push(e)); EXPECT_EQ(queue.size(), KeyQueue::limit);
	queue.take(KeyQueue::Time{}, out);
	queue.clear(); EXPECT_EQ(queue.size(), 0u);
	ASSERT_TRUE(queue.push(e)); ASSERT_TRUE(queue.take(KeyQueue::Time{}, out));
}
