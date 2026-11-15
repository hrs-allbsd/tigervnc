/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_TERMINAL_H
#define VNCSIXEL_TERMINAL_H
#include <string>
#include <termios.h>

namespace sixelvnc {
class Terminal {
public:
	Terminal();
	~Terminal();
	Terminal(const Terminal&) = delete;
	Terminal& operator=(const Terminal&) = delete;
	void enter();
	void leave() noexcept;
	void geometry();
	void enableInput();
	std::string takeInput();
	void queue(const std::string&);
	void flush();
	bool pending() const { return offset < output.size(); }
	int fd() const { return tty; }
	int width = 0, height = 0, cellWidth = 0, cellHeight = 0;
	bool pixelMouse = false;
private:
	std::string query(const char*);
	int tty = -1;
	termios saved;
	bool active = false, modesSaved = false;
	int otherKeys = -1;
	std::string output, deferred;
	size_t offset = 0;
};
}
#endif
