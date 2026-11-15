/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Connection.h"
#include <core/Configuration.h>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <exception>
#include <poll.h>
#include <unistd.h>

namespace {
volatile sig_atomic_t stopped = 0, resized = 0, suspended = 0;
void signalHandler(int number)
{
	if (number == SIGTSTP)
		suspended = 1;
	else if (number == SIGWINCH)
		resized = 1;
	else
		stopped = 1;
}
}
int main(int argc, char** argv)
{
	if (argc == 2 && (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0)) {
		puts("Usage: vncsixel [options] host[:display] | --terminal-check\n"
		    "-PasswordFile file (alias -passwd): vncpasswd-format file.\n"
		    "VNC_USERNAME and VNC_PASSWORD: same environment as vncviewer.\n"
		    "-ViewOnly: suppress remote input; -Shared=0: exclusive session.\n"
		    "-PerfLog file: numeric performance summary in JSON.\n"
		    "Run in xterm -ti vt340 with allowSendEvents:false.\n"
		    "Ctrl+] then q quits; c/a/s latch modifiers; u releases input.\n"
		    "See vncsixel/README.txt for build and terminal settings.");
		return 0;
	}
	const char* host = nullptr;
	for (int i = 1; i < argc;) {
		int used = core::Configuration::handleParamArg(argc, argv, i);
		if (used > 0) {
			i += used;
			continue;
		}
		if (host || (argv[i][0] == '-' &&
		    strcmp(argv[i], "--terminal-check") != 0)) {
			fprintf(stderr, "Invalid argument; see vncsixel --help\n");
			return 1;
		}
		host = argv[i++];
	}
	if (!host) {
		fprintf(stderr, "Usage: vncsixel [options] host[:display] | --terminal-check\n");
		return 1;
	}
	for (int number : {SIGINT, SIGTERM, SIGHUP, SIGQUIT, SIGWINCH, SIGTSTP}) {
		struct sigaction action = {};
		action.sa_handler = signalHandler;
		sigemptyset(&action.sa_mask);
		sigaction(number, &action, nullptr);
	}
	signal(SIGPIPE, SIG_IGN);
	try {
		sixelvnc::Terminal terminal;
		if (strcmp(host, "--terminal-check") == 0) {
			terminal.enter();
			fprintf(stderr, "SIXEL terminal: %dx%d, cells %dx%d, pixel mouse %s\n",
			    terminal.width, terminal.height, terminal.cellWidth,
			    terminal.cellHeight, terminal.pixelMouse ? "yes" : "no");
			return 0;
		}
		sixelvnc::Connection connection(host, terminal);
		bool entered = false;
		sixelvnc::Input input([&](const sixelvnc::InputEvent& e) {
			if (e.kind == sixelvnc::InputEvent::Refresh) resized = 1;
			else if (!connection.input(e)) stopped = 1;
		});
		auto lastInput = std::chrono::steady_clock::now();
		auto next = std::chrono::steady_clock::now();
		while (!stopped) {
			if (suspended && entered) {
				suspended = 0;
				connection.releaseInput();
				terminal.leave();
				raise(SIGSTOP);
				terminal.enter();
				terminal.enableInput();
				connection.redraw();
			}
			connection.process();
			if (connection.ready && !entered) {
				terminal.enter();
				terminal.enableInput();
				entered = true;
			}
			if (entered && resized && !terminal.pending()) {
				resized = 0;
				connection.releaseInput();
				terminal.geometry();
				connection.displayWidth = connection.displayHeight = 0;
				terminal.queue("\033[H\033[2J");
				connection.redraw();
			}
			std::string deferred = terminal.takeInput();
			if (entered && !deferred.empty()) input.feed(deferred.data(), deferred.size());
			auto now = std::chrono::steady_clock::now();
			if (now - lastInput > std::chrono::milliseconds(50)) input.expire();
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
				if (n > 0) {
					input.feed(bytes, n);
					lastInput = std::chrono::steady_clock::now();
				}
			}
			if (fds[1].revents & (POLLHUP | POLLERR))
				stopped = 1;
		}
		connection.releaseInput();
	} catch (const std::exception& e) {
		std::string message(e.what());
		for (char& c : message)
			if (static_cast<unsigned char>(c) < 32 || c == 127) c = '?';
		fprintf(stderr, "vncsixel: %s\n", message.c_str());
		return 1;
	}
	return 0;
}
