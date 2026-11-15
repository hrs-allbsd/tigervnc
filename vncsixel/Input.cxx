/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Input.h"
#define XK_MISCELLANY
#include <rfb/keysymdef.h>
#include <cstdio>
#include <cstdlib>
#include <vector>

using namespace sixelvnc;
void Input::character(uint32_t cp, unsigned mods, bool literal)
{
	InputEvent e;
	e.modifiers = mods;
	if (cp == 0x7f) e.key = XK_BackSpace;
	else if (cp == 13 || cp == 10) e.key = XK_Return;
	else if (cp == 9) e.key = XK_Tab;
	else if (cp == 27) e.key = XK_Escape;
	else if (cp < 32 && !literal) {
		e.key = cp == 0 ? ' ' : (cp <= 26 ? cp + 0x60 : cp + 0x40);
		e.modifiers |= 4;
	} else if (cp < 32) return;
	else e.key = cp <= 255 ? cp : 0x01000000 | cp;
	callback(e);
}
void Input::feed(const char* data, size_t size)
{
	for (size_t i = 0; i < size; i++) {
		buffer += data[i];
		while (parse()) {}
		if (buffer.size() > 256)
			buffer.clear();
	}
}
void Input::expire()
{
	if (buffer == "\033" && !paste) {
		buffer.clear();
		character(27, 0, false);
	}
}
bool Input::parse()
{
	if (buffer.empty()) return false;
	if (paste && buffer[0] == 27) {
		const std::string end = "\033[201~";
		if (end.compare(0, buffer.size(), buffer) == 0) {
			if (buffer == end) { paste = false; buffer.clear(); return true; }
			return false;
		}
		buffer.erase(0, 1); /* Literal pasted ESC is never a command. */
		return true;
	}
	unsigned mods = 0;
	size_t offset = 0;
	if (!paste && buffer[0] == 27) {
		if (buffer.size() == 1) return false;
		if (buffer[1] == '[' || buffer[1] == 'O') {
			size_t end = 2;
			while (end < buffer.size() && !(buffer[end] >= '@' && buffer[end] <= '~')) end++;
			if (end == buffer.size()) return false;
			char final = buffer[end];
			std::string body = buffer.substr(2, end - 2);
			buffer.erase(0, end + 1);
			InputEvent e;
			int b, x, y, used = 0;
			if (!body.empty() && body[0] == '<' && (final == 'M' || final == 'm')) {
				if (sscanf(body.c_str(), "<%3d;%5d;%5d%n", &b, &x, &y, &used) == 3 &&
				    used == int(body.size()) && b >= 0 && b <= 255 && x > 0 && y > 0 && x <= 65536 && y <= 65536) {
					e.kind = InputEvent::Mouse; e.x = x - 1; e.y = y - 1;
					e.button = b; e.release = final == 'm';
					e.modifiers = ((b & 4) ? 1 : 0) | ((b & 8) ? 2 : 0) | ((b & 16) ? 4 : 0);
					callback(e);
				}
				return true;
			}
			if (body.empty() && final == 'O') { e.kind = InputEvent::FocusOut; callback(e); return true; }
			if (body.empty() && final == 'I') { e.kind = InputEvent::Refresh; callback(e); return true; }
			/* Consume device/window/mode replies, never forward as keys. */
			if (final == 'c' || final == 't' || final == 'y' || final == 'm' ||
			    (!body.empty() && (body[0] == '?' || body[0] == '>'))) return true;
			std::vector<unsigned> values;
			unsigned value = 0;
			for (char c : body) {
				if (c >= '0' && c <= '9') {
					if (value > 1000000) return true;
					value = value * 10 + c - '0';
				} else if (c == ';') { values.push_back(value); value = 0; }
				else return true;
			}
			values.push_back(value);
			if (final == '~' && values[0] == 200) { paste = true; return true; }
			if (final == '~' && values.size() == 3 && values[0] == 27 && values[1] >= 1 && values[1] <= 8) {
				uint32_t cp = values[2];
				if (cp <= 0x10ffff && !(cp >= 0xd800 && cp <= 0xdfff))
					character(cp, values[1] - 1, false);
				return true;
			}
			if (values.size() == 2 && values[1] >= 1 && values[1] <= 8) e.modifiers = values[1] - 1;
			switch (final) {
			case 'A': e.key = XK_Up; break; case 'B': e.key = XK_Down; break;
			case 'C': e.key = XK_Right; break; case 'D': e.key = XK_Left; break;
			case 'H': e.key = XK_Home; break; case 'F': e.key = XK_End; break;
			case 'P': e.key = XK_F1; break; case 'Q': e.key = XK_F2; break;
			case 'R': e.key = XK_F3; break; case 'S': e.key = XK_F4; break;
			case 'Z': e.key = XK_Tab; e.modifiers |= 1; break;
			case '~': {
				const unsigned codes[] = {1,2,3,4,5,6,7,8,11,12,13,14,15,17,18,19,20,21,23,24};
				const uint32_t keys[] = {XK_Home,XK_Insert,XK_Delete,XK_End,XK_Page_Up,XK_Page_Down,XK_Home,XK_End,
				    XK_F1,XK_F2,XK_F3,XK_F4,XK_F5,XK_F6,XK_F7,XK_F8,XK_F9,XK_F10,XK_F11,XK_F12};
				for (size_t i = 0; i < sizeof(codes)/sizeof(codes[0]); i++)
					if (values[0] == codes[i]) e.key = keys[i];
				break;
			}
			default: break;
			}
			if (e.key) callback(e);
			return true;
		}
		mods = 2; offset = 1;
	}
	unsigned char first = buffer[offset];
	size_t length = first < 0x80 ? 1 : (first >= 0xc2 && first <= 0xdf ? 2 :
	    (first >= 0xe0 && first <= 0xef ? 3 : (first >= 0xf0 && first <= 0xf4 ? 4 : 0)));
	if (!length) { buffer.erase(0, offset + 1); return true; }
	if (buffer.size() < offset + length) return false;
	uint32_t cp = first & (length == 1 ? 0x7f : (0x7f >> length));
	for (size_t i = 1; i < length; i++) {
		unsigned char c = buffer[offset + i];
		if ((c & 0xc0) != 0x80) { buffer.erase(0, offset + i); return true; }
		cp = (cp << 6) | (c & 63);
	}
	buffer.erase(0, offset + length);
	if ((length == 2 && cp < 0x80) || (length == 3 && cp < 0x800) ||
	    (length == 4 && cp < 0x10000) || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return true;
	character(cp, mods, paste);
	return true;
}
