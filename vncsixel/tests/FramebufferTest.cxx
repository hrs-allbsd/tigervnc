/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Framebuffer.h"
#include <gtest/gtest.h>
#include <climits>

TEST(Framebuffer, RetinaAnd8K)
{
	EXPECT_NO_THROW(sixelvnc::checkFramebufferSize(6016, 3384));
	EXPECT_NO_THROW(sixelvnc::checkFramebufferSize(7680, 4320));
}
TEST(Framebuffer, Limit)
{
	EXPECT_NO_THROW(sixelvnc::checkFramebufferSize(8192, 8192));
	EXPECT_THROW(sixelvnc::checkFramebufferSize(8192, 8193),
	    std::runtime_error);
}
TEST(Framebuffer, InvalidDimensions)
{
	for (int w : {0, -1, INT_MAX})
		EXPECT_THROW(sixelvnc::checkFramebufferSize(w, INT_MAX),
		    std::runtime_error);
	EXPECT_THROW(sixelvnc::checkFramebufferSize(1, 0),
	    std::runtime_error);
	EXPECT_THROW(sixelvnc::checkFramebufferSize(1, -1),
	    std::runtime_error);
}
TEST(Framebuffer, ErrorDimensions)
{
	try {
		sixelvnc::checkFramebufferSize(16384, 8192);
		FAIL() << "oversize framebuffer accepted";
	} catch (const std::runtime_error& e) {
		EXPECT_NE(std::string(e.what()).find("16384x8192"),
		    std::string::npos);
	}
}
