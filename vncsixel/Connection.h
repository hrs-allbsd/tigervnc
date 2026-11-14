/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_CONNECTION_H
#define VNCSIXEL_CONNECTION_H
#include "Terminal.h"
#include <rfb/CConnection.h>
#include <network/TcpSocket.h>
#include <memory>

namespace sixelvnc {
class Connection : public rfb::CConnection {
public:
	Connection(const char*, Terminal&);
	~Connection();
	int fd();
	void process();
	void render();
	void redraw() { dirty = true; }
	int displayWidth = 0, displayHeight = 0;
	bool ready = false;
private:
	void bell() override {}
	void initDone() override;
	void resizeFramebuffer() override;
	void framebufferUpdateEnd() override;
	void getUserPasswd(std::string*, std::string*) override;
	bool verifyCertificate(unsigned, const uint8_t*, size_t) override;
	bool verifyHostKey(const uint8_t*, size_t, const char*) override;
	std::unique_ptr<network::TcpSocket> socket;
	Terminal& terminal;
	bool dirty = false;
};
}
#endif
