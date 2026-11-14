/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Connection.h"
#include <rfb/PixelBuffer.h>
#include <rdr/FdInStream.h>
#include <rdr/FdOutStream.h>
#include <sixel.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <vector>
#include <unistd.h>

using namespace sixelvnc;

Connection::Connection(const char* name, Terminal& term) : terminal(term)
{
	std::string host;
	int port;
	network::getHostAndPort(name, &host, &port);
	socket.reset(new network::TcpSocket(host.c_str(), port));
	setServerName(host.c_str());
	setStreams(&socket->inStream(), &socket->outStream());
	supportsDesktopResize = true;
	initialiseProtocol();
}
Connection::~Connection()
{
	try { close(); } catch (...) {}
}
int Connection::fd() { return socket->getFd(); }
void Connection::process()
{
	/* Include data already buffered by a TLS stream. Bound work per turn. */
	for (int i = 0; i < 64 && getInStream()->hasData(1); i++)
		if (!processMsg())
			break;
	getOutStream()->flush();
	socket->outStream().flush();
}
void Connection::initDone()
{
	setPF(rfb::PixelFormat(32, 24, false, true, 255, 255, 255, 16, 8, 0));
	resizeFramebuffer();
	ready = true;
}
void Connection::resizeFramebuffer()
{
	int w = server.width(), h = server.height();
	if (w <= 0 || h <= 0 || static_cast<size_t>(w) * h > 16 * 1024 * 1024)
		throw std::runtime_error("Remote framebuffer exceeds 16M pixels");
	setFramebuffer(new rfb::ManagedPixelBuffer(
	    rfb::PixelFormat(32, 24, false, true, 255, 255, 255, 16, 8, 0), w, h));
	dirty = true;
}
void Connection::framebufferUpdateEnd()
{
	CConnection::framebufferUpdateEnd();
	dirty = true;
}
void Connection::getUserPasswd(std::string* user, std::string* password)
{
	/* getpass reads the controlling terminal without echo; before raw mode. */
	if (user) {
		char* value = getpass("VNC username: ");
		if (!value)
			throw std::runtime_error("Cannot read username");
		*user = value;
	}
	if (password) {
		char* value = getpass("VNC password: ");
		if (!value)
			throw std::runtime_error("Cannot read password");
		*password = value;
		std::fill(value, value + password->size(), '\0');
	}
}
bool Connection::verifyCertificate(unsigned status, const uint8_t*, size_t)
{
	return status == 0;
}
bool Connection::verifyHostKey(const uint8_t*, size_t, const char*)
{
	/* No trust store yet. Never silently accept an unknown host key. */
	return false;
}
namespace {
struct Encoded {
	std::string bytes;
	bool failed = false;
};
int appendSixel(char* data, int size, void* context)
{
	auto& out = *static_cast<Encoded*>(context);
	try {
		if (size < 0 || out.bytes.size() + size > 32 * 1024 * 1024)
			out.failed = true;
		else if (!out.failed)
			out.bytes.append(data, size);
	} catch (...) { out.failed = true; }
	return out.failed ? -1 : size;
}
}
void Connection::render()
{
	if (!ready || !dirty || terminal.pending())
		return;
	auto* fb = getFramebuffer();
	int rw = fb->width(), rh = fb->height();
	double scale = std::min(1.0, std::min(double(terminal.width) / rw,
	    double(terminal.height) / rh));
	displayWidth = std::max(1, int(rw * scale));
	displayHeight = std::max(1, int(rh * scale));
	std::vector<uint8_t> rgb(static_cast<size_t>(displayWidth) * displayHeight * 3);
	int stride;
	const uint8_t* pixels = fb->getBuffer(fb->getRect(), &stride);
	for (int y = 0; y < displayHeight; y++) {
		int sy = int(static_cast<int64_t>(y) * rh / displayHeight);
		for (int x = 0; x < displayWidth; x++) {
			int sx = int(static_cast<int64_t>(x) * rw / displayWidth);
			fb->getPF().rgbFromBuffer(&rgb[(static_cast<size_t>(y) * displayWidth + x) * 3],
			    pixels + (static_cast<size_t>(sy) * stride + sx) * 4, 1);
		}
	}
	sixel_output_t* output = nullptr;
	sixel_dither_t* dither = nullptr;
	Encoded encoded;
	if (SIXEL_FAILED(sixel_output_new(&output, appendSixel, &encoded, nullptr)))
		throw std::runtime_error("Cannot create SIXEL output");
	if (SIXEL_FAILED(sixel_dither_new(&dither, 256, nullptr))) {
		sixel_output_unref(output);
		throw std::runtime_error("Cannot create SIXEL palette");
	}
	unsigned char palette[256 * 3];
	for (int i = 0; i < 256; i++) {
		palette[i * 3] = ((i >> 5) & 7) * 255 / 7;
		palette[i * 3 + 1] = ((i >> 2) & 7) * 255 / 7;
		palette[i * 3 + 2] = (i & 3) * 255 / 3;
	}
	sixel_dither_set_palette(dither, palette);
	sixel_dither_set_pixelformat(dither, SIXEL_PIXELFORMAT_RGB888);
	sixel_dither_set_diffusion_type(dither, SIXEL_DIFFUSE_NONE);
	sixel_dither_set_body_only(dither, 0);
	SIXELSTATUS status = sixel_encode(rgb.data(), displayWidth, displayHeight, 3, dither, output);
	sixel_dither_unref(dither);
	sixel_output_unref(output);
	if (SIXEL_FAILED(status) || encoded.failed)
		throw std::runtime_error("SIXEL encoding failed or exceeded output limit");
	terminal.queue("\033[H" + encoded.bytes);
	dirty = false;
}
