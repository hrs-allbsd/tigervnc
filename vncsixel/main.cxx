/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Connection.h"
#include "FrameClock.h"
#include "HostCursor.h"
#include <core/Configuration.h>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <strings.h>
#include <exception>
#include <poll.h>
#include <unistd.h>

namespace {
core::IntParameter maxFPS("MaxFPS", "Maximum terminal redraw rate", 10, 1, 60);
core::IntParameter escapeTimeout("EscapeTimeout",
    "Milliseconds to wait for an Escape key sequence", 50, 1, 1000);
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
// Track explicit nonempty values, including values equal to the default.
bool explicitFile(const char* argument, const char* name, bool previous)
{
	while (*argument == '-')
		argument++;
	size_t length = strcspn(argument, "=");
	if (length != strlen(name) || strncasecmp(argument, name, length) != 0)
		return previous;
	return !core::Configuration::getParam(name)->getValueStr().empty();
}
}
int main(int argc, char** argv)
{
	if (argc == 2 && (strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0)) {
		puts("Usage: vncsixel [options] host[:display] | --terminal-check\n"
		    "-PasswordFile file (alias -passwd): vncpasswd-format file.\n"
		    "VNC_USERNAME and VNC_PASSWORD: same environment as vncviewer.\n"
		    "-KnownHosts file: RSA-AES keys; -StrictHostKeyChecking: reject unknown.\n"
		    "-X509CA file, -X509CRL file: require readable, nonempty PEM files.\n"
		    "Every explicitly supplied CRL must have current update dates.\n"
		    "-ViewOnly: suppress remote input; -Shared=0: exclusive session.\n"
		    "-CellSize WxH, -PixelSize WxH: override terminal geometry.\n"
		    "-SingleRect: use one bounding rectangle instead of sparse regions.\n"
		    "-FullFrame: disable partial updates for comparison or fallback.\n"
		    "-QualityLevel -1..9: Tight JPEG hint; -1 omits (default).\n"
		    "-CompressLevel -1..9: compression hint; -1 uses server default.\n"
		    "-NoJPEG: suppress JPEG capability and quality hints.\n"
		    "-PhotoPalette: adaptive palette with full-frame output (256 colors).\n"
		    "-HideLocalCursor=0: retain the local X11 pointer.\n"
		    "-MaxFPS 1..60: redraw rate limit (default 10).\n"
		    "-EscapeTimeout 1..1000: Escape sequence wait in ms (default 50).\n"
		    "-PasteRate 1..10000: pasted characters/s (default 200).\n"
		    "-PerfLog file: numeric performance summary in JSON.\n"
		    "Run in xterm -ti vt340 with allowSendEvents:false.\n"
		    "Ctrl+] then h shows help; q quits; c/a/s latch; u releases input.\n"
		    "See vncsixel/README.txt for build and terminal settings.");
		return 0;
	}
	const char* host = nullptr;
	bool requireCA = false, requireCRL = false;
	for (int i = 1; i < argc;) {
		int used = core::Configuration::handleParamArg(argc, argv, i);
		if (used > 0) {
			requireCA = explicitFile(argv[i], "X509CA", requireCA);
			requireCRL = explicitFile(argv[i], "X509CRL", requireCRL);
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
			fprintf(stderr, "SIXEL terminal: %dx%d, cells %dx%d, pixel mouse %s, colors %d\n",
			    terminal.width, terminal.height, terminal.cellWidth,
			    terminal.cellHeight, terminal.pixelMouse ? "yes" : "no",
			    terminal.paletteColors);
			return 0;
		}
		sixelvnc::Connection connection(host, terminal, requireCA, requireCRL);
		sixelvnc::HostCursor hostCursor;
		bool entered = false;
		sixelvnc::Input input([&](const sixelvnc::InputEvent& e) {
			if (!connection.input(e)) stopped = 1;
		});
		auto lastInput = std::chrono::steady_clock::now();
		sixelvnc::FrameClock frames(maxFPS);
		while (!stopped) {
			if (suspended && entered) {
				suspended = 0;
				connection.releaseInput();
				hostCursor.show();
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
			if (entered && !deferred.empty()) {
				input.feed(deferred.data(), deferred.size());
				lastInput = std::chrono::steady_clock::now();
			}
			auto now = std::chrono::steady_clock::now();
			if (now - lastInput > std::chrono::milliseconds(escapeTimeout)) input.expire();
			connection.drainInput();
			if (entered && frames.due(now) && connection.render())
				frames.rendered(now);
			hostCursor.update(entered && connection.hideLocalCursor(),
			    connection.displayWidth, connection.displayHeight,
			    terminal.textWidth, terminal.textHeight);
			terminal.flush();
			pollfd fds[] = {{connection.fd(), POLLIN, 0},
			    {terminal.fd(), static_cast<short>(POLLIN | (terminal.pending() ? POLLOUT : 0)), 0}};
			if (poll(fds, 2, std::min(connection.inputTimeout(),
			    frames.pollTimeout(std::chrono::steady_clock::now()))) < 0 && errno != EINTR)
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
