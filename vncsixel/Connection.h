/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_CONNECTION_H
#define VNCSIXEL_CONNECTION_H
#include "Terminal.h"
#include "Input.h"
#include "KeyQueue.h"
#include "Performance.h"
#include <rfb/CConnection.h>
#include <network/TcpSocket.h>
#include <memory>
#include <vector>

namespace sixelvnc {
class Connection : public rfb::CConnection {
public:
	Connection(const char*, Terminal&, bool, bool);
	~Connection();
	int fd();
	bool hideLocalCursor() const;
	void process();
	bool render();
	bool input(const InputEvent&);
	void releaseInput();
	void drainInput();
	int inputTimeout() const;
	void redraw() { dirty = forceFull = helpDirty = true; }
	int displayWidth = 0, displayHeight = 0;
	bool ready = false;
private:
	void bell() override {}
	void initDone() override;
	void setCursor(int, int, const core::Point&, const uint8_t*) override;
	void setCursorPos(const core::Point&) override;
	void modifiers(unsigned);
	void status();
	void toggleHelp();
	void resizeFramebuffer() override;
	void framebufferUpdateEnd() override;
	void framebufferUpdateStart() override;
	void getUserPasswd(std::string*, std::string*) override;
	void checkCertificateFiles(int, int) override;
	const char* getCertificatePurpose() override;
	bool requireCA, requireCRL;
	bool verifyCertificate(unsigned, const uint8_t*, size_t) override;
	bool verifyHostKey(const uint8_t*, size_t, const char*) override;
	std::string trustEndpoint;
	KeyQueue keys;
	bool discardPaste = false, receivingPaste = false;
	std::string inputNotice;
	Performance performance;
	std::unique_ptr<network::TcpSocket> socket;
	Terminal& terminal;
	bool dirty = false, updating = false;
	bool prefix = false, forceFull = true, cursorKnown = false;
	bool help = false, helpDirty = false;
	size_t helpPage = 0, helpPages = 1;
	std::vector<uint8_t> previousFrame;
	unsigned latched = 0, held = 0, mouseMods = 0;
	uint16_t buttons = 0;
	core::Point pointer = {0, 0};
};
}
#endif
