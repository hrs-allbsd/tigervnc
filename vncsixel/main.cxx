/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Connection.h"
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <exception>
#include <poll.h>
#include <unistd.h>

namespace {
volatile sig_atomic_t stopped = 0, resized = 0;
void signalHandler(int number)
{
	if (number == SIGWINCH)
		resized = 1;
	else
		stopped = 1;
}
}
int main(int argc, char** argv)
{
	if (argc != 2) {
		fprintf(stderr, "Usage: vncsixel host[:display] | --terminal-check\n");
		return 1;
	}
	for (int number : {SIGINT, SIGTERM, SIGHUP, SIGWINCH}) {
		struct sigaction action = {};
		action.sa_handler = signalHandler;
		sigemptyset(&action.sa_mask);
		sigaction(number, &action, nullptr);
	}
	signal(SIGPIPE, SIG_IGN);
	try {
		sixelvnc::Terminal terminal;
		if (strcmp(argv[1], "--terminal-check") == 0) {
			terminal.enter();
			fprintf(stderr, "SIXEL terminal: %dx%d, cells %dx%d, pixel mouse %s\n",
			    terminal.width, terminal.height, terminal.cellWidth,
			    terminal.cellHeight, terminal.pixelMouse ? "yes" : "no");
			return 0;
		}
		sixelvnc::Connection connection(argv[1], terminal);
		bool entered = false;
		auto next = std::chrono::steady_clock::now();
		while (!stopped) {
			connection.process();
			if (connection.ready && !entered) {
				terminal.enter();
				entered = true;
			}
			if (entered && resized && !terminal.pending()) {
				resized = 0;
				terminal.geometry();
				terminal.queue("\033[H\033[2J");
				connection.redraw();
			}
			auto now = std::chrono::steady_clock::now();
			if (entered && now >= next) {
				connection.render();
				next = now + std::chrono::milliseconds(100);
			}
			terminal.flush();
			pollfd fds[] = {{connection.fd(), POLLIN, 0},
			    {terminal.fd(), static_cast<short>(POLLIN | (terminal.pending() ? POLLOUT : 0)), 0}};
			if (poll(fds, 2, 20) < 0 && errno != EINTR)
				throw std::runtime_error("poll failed");
			if (fds[1].revents & POLLIN) {
				char bytes[1024];
				ssize_t n = read(terminal.fd(), bytes, sizeof(bytes));
				for (ssize_t i = 0; i < n; i++)
					if (bytes[i] == 0x1d)
						stopped = 1;
			}
			if (fds[1].revents & (POLLHUP | POLLERR))
				stopped = 1;
		}
	} catch (const std::exception& e) {
		fprintf(stderr, "vncsixel: %s\n", e.what());
		return 1;
	}
	return 0;
}
