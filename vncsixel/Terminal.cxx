/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Terminal.h"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <fcntl.h>
#include <poll.h>
#include <stdexcept>
#include <unistd.h>

using namespace sixelvnc;
using Clock = std::chrono::steady_clock;

Terminal::Terminal()
{
	tty = open("/dev/tty", O_RDWR | O_NONBLOCK | O_CLOEXEC);
	if (tty < 0)
		throw std::runtime_error("Cannot open /dev/tty");
	if (tcgetattr(tty, &saved) < 0) {
		close(tty);
		throw std::runtime_error("Cannot read termios");
	}
}
Terminal::~Terminal()
{
	leave();
	close(tty);
}
void Terminal::queue(const std::string& data)
{
	if (data.size() > 32 * 1024 * 1024 || output.size() + data.size() > 32 * 1024 * 1024)
		throw std::runtime_error("Terminal output exceeds 32 MiB");
	output += data;
	peakQueueBytes = std::max<uint64_t>(peakQueueBytes, output.size() - offset);
}
void Terminal::flush()
{
	while (pending()) {
		ssize_t n = write(tty, output.data() + offset, output.size() - offset);
		if (n > 0) {
			offset += n;
			writtenBytes += n;
		}
		else if (n < 0 && errno == EINTR)
			continue;
		else if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
			blockedWrites++;
			return;
		}
		else
			throw std::runtime_error("Terminal write failed");
	}
	output.clear();
	offset = 0;
}
std::string Terminal::query(const char* text)
{
	queue(text);
	std::string answer;
	auto end = Clock::now() + std::chrono::milliseconds(250);
	while (Clock::now() < end) {
		flush();
		pollfd p = {tty, static_cast<short>(POLLIN | (pending() ? POLLOUT : 0)), 0};
		if (poll(&p, 1, 10) < 0 && errno != EINTR)
			throw std::runtime_error("Terminal poll failed");
		char buffer[1024];
		ssize_t n = read(tty, buffer, sizeof(buffer));
		if (n > 0) {
			answer.append(buffer, n);
			if (answer.size() > 4096)
				throw std::runtime_error("Oversized terminal response");
		}
	}
	const char* prefix = "\033[?";
	char final = 'c';
	std::string request(text);
	if (request == "\033[14t") { prefix = "\033[4;"; final = 't'; }
	else if (request == "\033[16t") { prefix = "\033[6;"; final = 't'; }
	else if (request == "\033[?1016$p") { prefix = "\033[?1016;"; final = 'y'; }
	else if (request == "\033[?4m") { prefix = "\033[>4;"; final = 'm'; }
	size_t start = answer.find(prefix);
	size_t finish = start == std::string::npos ? start : answer.find(final, start);
	if (finish == std::string::npos) {
		deferred += answer;
		return {};
	}
	std::string result = answer.substr(start, finish - start + 1);
	deferred += answer.substr(0, start) + answer.substr(finish + 1);
	if (deferred.size() > 4096)
		throw std::runtime_error("Too much input during terminal negotiation");
	return result;
}
void Terminal::geometry()
{
	int w = 0, h = 0, cw = 0, ch = 0;
	std::string a = query("\033[14t");
	std::string b = query("\033[16t");
	if (sscanf(a.c_str(), "\033[4;%5d;%5dt", &h, &w) != 2 ||
	    sscanf(b.c_str(), "\033[6;%5d;%5dt", &ch, &cw) != 2 ||
	    w <= 0 || h <= 0 || cw <= 0 || ch <= 0 ||
	    w > 16384 || h > 16384 || cw > 256 || ch > 256 || h <= ch + 12)
		throw std::runtime_error("xterm must answer pixel and cell size queries");
	width = w;
	height = ((h - ch - 6) / 6) * 6;
	cellWidth = cw;
	cellHeight = ch;
}
void Terminal::enter()
{
	termios raw = saved;
	cfmakeraw(&raw);
	if (tcsetattr(tty, TCSANOW, &raw) < 0)
		throw std::runtime_error("Cannot enter raw mode");
	active = true;
	try {
		std::string da = query("\033[c");
		if (da.find(";4;") == std::string::npos && da.find(";4c") == std::string::npos)
			throw std::runtime_error("SIXEL capability missing; use xterm -ti vt340");
		geometry();
		std::string mouse = query("\033[?1016$p");
		pixelMouse = mouse.find(";2$y") != std::string::npos || mouse.find(";1$y") != std::string::npos;
		std::string keys = query("\033[?4m");
		sscanf(keys.c_str(), "\033[>4;%1dm", &otherKeys);
		queue("\033[?25;80;1003;1004;1006;1016;1070;2004s");
		modesSaved = true;
		queue("\033[?1049h\033[?25l\033[?80l\033[?1070h\033[H\033[2J");
		flush();
	} catch (...) {
		leave();
		throw;
	}
}
void Terminal::leave() noexcept
{
	if (!active)
		return;
	/* Cancel an unfinished DCS before restoring the terminal modes. */
	output.clear();
	offset = 0;
	try {
		queue("\030\033\\");
		if (modesSaved)
			queue("\033[?25;80;1003;1004;1006;1016;1070;2004r\033[?1049l");
		if (otherKeys >= 0)
			queue("\033[>4;" + std::to_string(otherKeys) + "m");
		auto end = Clock::now() + std::chrono::milliseconds(250);
		while (pending() && Clock::now() < end) {
			flush();
			pollfd p = {tty, POLLOUT, 0};
			poll(&p, 1, 10);
		}
	} catch (...) {}
	tcsetattr(tty, TCSANOW, &saved);
	active = modesSaved = false;
}

void Terminal::enableInput()
{
	queue("\033[?1003h\033[?1004h\033[?1006h\033[?2004h");
	if (pixelMouse)
		queue("\033[?1016h");
	if (otherKeys >= 0 && otherKeys <= 3)
		queue("\033[>4;2m");
}

std::string Terminal::takeInput()
{
	std::string result;
	result.swap(deferred);
	return result;
}
