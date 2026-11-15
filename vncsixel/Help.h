/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_HELP_H
#define VNCSIXEL_HELP_H
#include <algorithm>
#include <string>
#include <vector>

namespace sixelvnc {
struct HelpPage {
	std::string output;
	size_t pages;
};
inline HelpPage localHelp(int columns, int rows, size_t page, bool viewOnly)
{
	/* Leave the last column unused to avoid pending terminal autowrap. */
	size_t width = std::max(1, columns - 1);
	HelpPage result = {"\033[H\033[2J", 1};
	if (rows < 3) {
		result.output += std::string("Esc/Enter back").substr(0, width);
		return result;
	}
	std::vector<std::string> lines;
	const char* content[] = {
	    "Press Ctrl+] and then the command key:",
	    "h  Open this help",
	    "q  Quit the viewer",
	    "r  Redraw the remote image",
	    "u  Cancel pending paste and release held input",
	    "c/a/s  Toggle Control/Alt/Shift latch",
	    "Ctrl+] again  Send a literal Ctrl+]",
	    "",
	    "Mouse: move, left/middle/right buttons, vertical wheel",
	    "Paste: paced text; does not use latched modifiers",
	    "Focus loss, resize and suspend cancel pending input",
	    "Physical key releases cannot be reproduced by terminal input",
	    "",
	    "Options: -MaxFPS, -PasteRate, -EscapeTimeout",
	    "-HideLocalCursor=0 keeps the native X11 pointer",
	    "See vncsixel --help and README.txt for full details"
	};
	lines.push_back(viewOnly ? "ViewOnly: remote input is disabled" :
	    "Interactive: keyboard and mouse control the remote desktop");
	for (const char* text : content) {
		std::string line(text);
		if (line.empty()) lines.emplace_back();
		for (size_t offset = 0; offset < line.size(); offset += width)
			lines.push_back(line.substr(offset, width));
	}
	size_t body = rows - 2;
	result.pages = (lines.size() + body - 1) / body;
	page = std::min(page, result.pages - 1);
	std::string heading = "vncsixel help " + std::to_string(page + 1) +
	    "/" + std::to_string(result.pages);
	result.output += heading.substr(0, width);
	for (size_t i = 0; i < body && page * body + i < lines.size(); i++)
		result.output += "\033[" + std::to_string(i + 2) + ";1H" + lines[page * body + i];
	result.output += "\033[" + std::to_string(rows) + ";1H" +
	    std::string("Esc/Enter back | Space/n next | p previous").substr(0, width);
	return result;
}
}
#endif
