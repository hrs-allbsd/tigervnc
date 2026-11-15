/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_INPUT_H
#define VNCSIXEL_INPUT_H
#include <cstdint>
#include <functional>
#include <string>
namespace sixelvnc {
struct InputEvent {
	enum Kind { Key, Mouse, FocusOut, Refresh, PasteBegin, PasteEnd } kind = Key;
	uint32_t key = 0;
	unsigned modifiers = 0;
	int x = 0, y = 0, button = 0;
	bool release = false, pasted = false;
};
class Input {
public:
	explicit Input(std::function<void(const InputEvent&)> cb) : callback(cb) {}
	void feed(const char*, size_t);
	void expire();
private:
	bool parse();
	void character(uint32_t, unsigned, bool);
	std::function<void(const InputEvent&)> callback;
	std::string buffer;
	bool paste = false;
};
}
#endif
