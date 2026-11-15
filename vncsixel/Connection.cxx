/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "Connection.h"
#include "Framebuffer.h"
#include "Palette.h"
#include "Damage.h"
#include "Help.h"
#include "TrustStore.h"
#include <core/xdgdirs.h>
#ifdef HAVE_CONFIG_H
#include <config.h>
#endif
#ifdef HAVE_NETTLE
#include <nettle/sha2.h>
#include <nettle/version.h>
#endif
#include <rfb/PixelBuffer.h>
#include <rfb/obfuscate.h>
#include <core/Configuration.h>
#include <rfb/Cursor.h>
#define XK_MISCELLANY
#include <rfb/keysymdef.h>
#include <rdr/FdInStream.h>
#include <rdr/FdOutStream.h>
#include <sixel.h>
#include <algorithm>
#include <cerrno>
#include <sys/stat.h>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <vector>
#include <unistd.h>

using namespace sixelvnc;

namespace {
core::StringParameter knownHosts("KnownHosts", "RSA-AES known-hosts file", "");
core::BoolParameter strictHostKeyChecking("StrictHostKeyChecking",
    "Reject unknown RSA-AES host keys without prompting", false);
core::IntParameter jpegQuality("QualityLevel",
    "Tight JPEG quality hint; -1 omits hint, 0 low to 9 high", -1, -1, 9);
core::IntParameter compressionLevel("CompressLevel",
    "Compression hint; -1 leaves server default, 0 low to 9 high", -1, -1, 9);
core::IntParameter pasteRate("PasteRate",
    "Maximum pasted characters per second", 200, 1, 10000);
core::StringParameter passwordFile("PasswordFile",
    "Password file for VNC authentication", "");
core::AliasParameter passwd("passwd", &passwordFile);
core::BoolParameter photoPalette("PhotoPalette",
    "Use an adaptive full-frame palette with 256-color terminals", false);
core::BoolParameter singleRect("SingleRect", "Use one changed rectangle per frame", false);
core::BoolParameter fullFrame("FullFrame", "Disable partial screen updates", false);
core::BoolParameter sharedSession("Shared", "Request a shared VNC session", true);
core::BoolParameter viewOnly("ViewOnly", "Do not send remote input", false);
}

Connection::Connection(const char* name, Terminal& term, bool ca, bool crl) :
    requireCA(ca), requireCRL(crl), keys(pasteRate), terminal(term)
{
	std::string host;
	int port;
	network::getHostAndPort(name, &host, &port);
	trustEndpoint = "[" + host + "]:" + std::to_string(port);
	socket.reset(new network::TcpSocket(host.c_str(), port));
	setServerName(host.c_str());
	setStreams(&socket->inStream(), &socket->outStream());
	setShared(sharedSession);
	setQualityLevel(jpegQuality);
	setCompressLevel(compressionLevel);
	supportsDesktopResize = true;
	supportsLocalCursor = true;
	supportsCursorPosition = true;
	initialiseProtocol();
}
Connection::~Connection()
{
	try { releaseInput(); getOutStream()->flush(); } catch (...) {}
	close();
	performance.ttyBytes = terminal.writtenBytes;
	performance.peakQueueBytes = terminal.peakQueueBytes;
	performance.blockedWrites = terminal.blockedWrites;
}
int Connection::fd() { return socket->getFd(); }
bool Connection::hideLocalCursor() const { return ready && cursorKnown && !viewOnly && !help; }
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
	if (ready) releaseInput();
	checkFramebufferSize(w, h);
	auto* fb = new rfb::ManagedPixelBuffer(
	    rfb::PixelFormat(32, 24, false, true, 255, 255, 255, 16, 8, 0), w, h);
	uint32_t black = 0;
	fb->fillRect(fb->getRect(), &black);
	setFramebuffer(fb);
	forceFull = true;
	dirty = true;
}
void Connection::framebufferUpdateStart()
{
	updating = true;
	CConnection::framebufferUpdateStart();
}
void Connection::framebufferUpdateEnd()
{
	CConnection::framebufferUpdateEnd();
	performance.updates++;
	updating = false;
	dirty = true;
}
void Connection::getUserPasswd(std::string* user, std::string* password)
{
	/* Match vncviewer/CConn.cxx: environment precedes password files. */
	const char* envUser = getenv("VNC_USERNAME");
	const char* envPassword = getenv("VNC_PASSWORD");
	if (password && envPassword && (!user || envUser)) {
		if (user) *user = envUser;
		*password = envPassword;
		return;
	}
	const char* path = passwordFile;
	if (!user && password && path[0]) {
		std::unique_ptr<FILE, decltype(&fclose)> file(
		    fopen(path, "rb"), fclose);
		if (!file)
			throw std::runtime_error("Cannot open VNC password file");
		uint8_t bytes[8];
		size_t count = fread(bytes, 1, sizeof(bytes), file.get());
		if (ferror(file.get()))
			throw std::runtime_error("Cannot read VNC password file");
		*password = rfb::deobfuscate(bytes, count);
		std::fill(bytes, bytes + sizeof(bytes), 0);
		return;
	}
	/* Authentication prompts run before entering terminal raw mode. */
	if (user) {
		std::unique_ptr<FILE, decltype(&fclose)> tty(
		    fopen("/dev/tty", "r+"), fclose);
		if (!tty || fputs("VNC username: ", tty.get()) == EOF ||
		    fflush(tty.get()) == EOF)
			throw std::runtime_error("Cannot prompt for username");
		user->clear();
		int c;
		while ((c = fgetc(tty.get())) != '\n') {
			if (c == EOF)
				throw std::runtime_error("Cannot read username");
			if (user->size() >= 4096)
				throw std::runtime_error("Username exceeds 4096 bytes");
			user->push_back(static_cast<char>(c));
		}
	}
	if (password) {
		char* value = getpass("VNC password: ");
		if (!value)
			throw std::runtime_error("Cannot read password");
		*password = value;
		std::fill(value, value + password->size(), '\0');
	}
}
void Connection::checkCertificateFiles(int caStatus, int crlStatus)
{
	if (requireCA && caStatus < 1)
		throw std::runtime_error("Cannot load specified X509CA file");
	if (requireCRL && crlStatus < 1)
		throw std::runtime_error("Cannot load specified X509CRL file");
}
const char* Connection::getCertificatePurpose()
{
	/* id-kp-serverAuth, also used by GNUTLS_KP_TLS_WWW_SERVER. */
	return "1.3.6.1.5.5.7.3.1";
}
bool Connection::verifyCertificate(unsigned status, const uint8_t*, size_t)
{
	return status == 0;
}
bool Connection::verifyHostKey(const uint8_t* key, size_t length, const char*)
{
#ifndef HAVE_NETTLE
	(void)key; (void)length;
	return false;
#else
	std::string path = static_cast<const char*>(knownHosts);
	bool defaultPath = path.empty();
	if (defaultPath) {
		const char* directory = core::getvncdatadir();
		if (!directory) throw std::runtime_error("Cannot determine RSA known-hosts directory");
		path = std::string(directory) + "/vncsixel_rsa_known_hosts";
	}
	TrustStore store(path);
	std::string value(reinterpret_cast<const char*>(key), length);
	auto state = store.check(trustEndpoint, value);
	if (state == TrustStore::Match) return true;
	if (state == TrustStore::Changed)
		throw std::runtime_error("RSA host key changed; connection rejected (check KnownHosts)");
	if (strictHostKeyChecking) return false;
	uint8_t digest[SHA256_DIGEST_SIZE];
	sha256_ctx context;
	sha256_init(&context);
	sha256_update(&context, length, key);
#if NETTLE_VERSION_MAJOR >= 4
	sha256_digest(&context, digest);
#else
	sha256_digest(&context, sizeof(digest), digest);
#endif
	std::string fingerprint = TrustStore::hex(digest, sizeof(digest));
	std::string endpoint = trustEndpoint;
	for (char& c : endpoint) if (c < 32 || c > 126) c = '?';
	std::unique_ptr<FILE, decltype(&fclose)> tty(fopen("/dev/tty", "r+"), fclose);
	if (!tty) return false;
	if (fprintf(tty.get(), "Unknown RSA-AES host: %s\nSHA256:%s\n"
	    "Verify the fingerprint through a trusted channel.\n"
	    "Type yes to save, once for this connection, or no [no]: ",
	    endpoint.c_str(), fingerprint.c_str()) < 0 || fflush(tty.get()) == EOF)
		return false;
	std::string answer;
	bool oversized = false;
	int c;
	while ((c = fgetc(tty.get())) != '\n') {
		if (c == EOF) return false;
		if (answer.size() < 16) answer += static_cast<char>(c);
		else oversized = true;
	}
	if (oversized) return false;
	if (answer == "once") return true;
	if (answer != "yes") return false;
	if (defaultPath) {
		std::string directory = path.substr(0, path.find_last_of('/'));
		if (core::mkdir_p(directory.c_str(), 0700) < 0 && errno != EEXIST)
			throw std::runtime_error("Cannot create RSA known-hosts directory");
		struct stat st;
		if (stat(directory.c_str(), &st) < 0 || !S_ISDIR(st.st_mode))
			throw std::runtime_error("Invalid RSA known-hosts directory");
	}
	store.remember(trustEndpoint, value);
	return true;
#endif
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
bool Connection::render()
{
	if (help) {
		if (!helpDirty || terminal.pending()) return false;
		auto page = localHelp(terminal.textWidth / terminal.cellWidth,
		    terminal.textHeight / terminal.cellHeight, helpPage, viewOnly);
		helpPages = page.pages;
		helpPage = std::min(helpPage, helpPages - 1);
		terminal.queue(page.output);
		helpDirty = false;
		return false;
	}
	if (!ready || updating || !dirty || terminal.pending())
		return false;
	auto snapshotStart = std::chrono::steady_clock::now();
	auto* fb = getFramebuffer();
	int rw = fb->width(), rh = fb->height();
	double scale = std::min(1.0, std::min(double(terminal.width) / rw,
	    double(terminal.height) / rh));
	int oldWidth = displayWidth, oldHeight = displayHeight;
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
			const auto& cursor = server.cursor();
			int cx = sx - pointer.x + cursor.hotspot().x;
			int cy = sy - pointer.y + cursor.hotspot().y;
			if (cx >= 0 && cy >= 0 && cx < cursor.width() && cy < cursor.height()) {
				const uint8_t* fg = cursor.getBuffer() + (static_cast<size_t>(cy) * cursor.width() + cx) * 4;
				uint8_t* bg = &rgb[(static_cast<size_t>(y) * displayWidth + x) * 3];
				for (int c = 0; c < 3; c++)
					bg[c] = (unsigned(bg[c]) * (255 - fg[3]) + unsigned(fg[c]) * fg[3]) / 255;
			}
		}
	}
	bool photo = photoPalette && terminal.paletteColors == 256;
	std::vector<uint8_t> indexed;
	std::vector<DamageRect> regions;
	bool force = fullFrame || forceFull || displayWidth != oldWidth ||
	    displayHeight != oldHeight;
	if (photo) {
		/* Palette indices from different frames cannot be compared. */
		if (force || previousFrame != rgb)
			regions.push_back({0, 0, displayWidth, displayHeight});
	} else {
		indexed.resize(static_cast<size_t>(displayWidth) * displayHeight);
		for (size_t i = 0; i < indexed.size(); i++)
			indexed[i] = terminal.paletteColors == 256 ?
			    rgb332(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]) :
			    ((rgb[i * 3] >= 128 ? 4 : 0) |
			    (rgb[i * 3 + 1] >= 128 ? 2 : 0) |
			    (rgb[i * 3 + 2] >= 128 ? 1 : 0));
		regions = damageRegions(previousFrame, indexed, displayWidth,
		    displayHeight, terminal.cellWidth, terminal.cellHeight,
		    force, singleRect, terminal.paletteColors);
	}
	if (regions.empty()) {
		performance.snapshotMs += std::chrono::duration<double, std::milli>(
		    std::chrono::steady_clock::now() - snapshotStart).count();
		performance.skipped++;
		dirty = false;
		return false;
	}
	performance.remoteWidth = rw;
	performance.remoteHeight = rh;
	performance.width = displayWidth;
	performance.height = displayHeight;
	auto encodeStart = std::chrono::steady_clock::now();
	performance.snapshotMs += std::chrono::duration<double, std::milli>(
	    encodeStart - snapshotStart).count();
	std::string frame;
	uint64_t bytes = 0, pixelsEncoded = 0;
	double cropMs = 0;
	for (const auto& rect : regions) {
		auto cropStart = std::chrono::steady_clock::now();
		int channels = photo ? 3 : 1;
		const auto& source = photo ? rgb : indexed;
		std::vector<uint8_t> region(static_cast<size_t>(rect.width) * rect.height * channels);
		for (int y = 0; y < rect.height; y++)
			std::copy_n(source.data() + (static_cast<size_t>(rect.y + y) *
			    displayWidth + rect.x) * channels, rect.width * channels,
			    region.data() + static_cast<size_t>(y) * rect.width * channels);
		cropMs += std::chrono::duration<double, std::milli>(
		    std::chrono::steady_clock::now() - cropStart).count();
		sixel_output_t* output = nullptr;
		sixel_dither_t* dither = nullptr;
		Encoded encoded;
		if (SIXEL_FAILED(sixel_output_new(&output, appendSixel, &encoded, nullptr)))
			throw std::runtime_error("Cannot create SIXEL output");
		if (SIXEL_FAILED(sixel_dither_new(&dither, terminal.paletteColors, nullptr))) {
			sixel_output_unref(output);
			throw std::runtime_error("Cannot create SIXEL palette");
		}
		unsigned char palette[256 * 3];
		for (int i = 0; i < terminal.paletteColors; i++) {
			if (terminal.paletteColors == 8) {
				palette[i * 3] = i & 4 ? 255 : 0;
				palette[i * 3 + 1] = i & 2 ? 255 : 0;
				palette[i * 3 + 2] = i & 1 ? 255 : 0;
				continue;
			}
			palette[i * 3] = ((i >> 5) & 7) * 255 / 7;
			palette[i * 3 + 1] = ((i >> 2) & 7) * 255 / 7;
			palette[i * 3 + 2] = (i & 3) * 255 / 3;
		}
		if (photo) {
			auto start = std::chrono::steady_clock::now();
			SIXELSTATUS result = sixel_dither_initialize(dither, region.data(),
			    rect.width, rect.height, SIXEL_PIXELFORMAT_RGB888,
			    SIXEL_LARGE_NORM, SIXEL_REP_AVERAGE_PIXELS, SIXEL_QUALITY_HIGH);
			performance.paletteMs += std::chrono::duration<double, std::milli>(
			    std::chrono::steady_clock::now() - start).count();
			if (SIXEL_FAILED(result)) {
				sixel_dither_unref(dither);
				sixel_output_unref(output);
				throw std::runtime_error("Cannot create adaptive SIXEL palette");
			}
			sixel_dither_set_pixelformat(dither, SIXEL_PIXELFORMAT_RGB888);
		} else {
			sixel_dither_set_palette(dither, palette);
			sixel_dither_set_pixelformat(dither, SIXEL_PIXELFORMAT_PAL8);
		}
		sixel_dither_set_diffusion_type(dither, SIXEL_DIFFUSE_NONE);
		sixel_dither_set_body_only(dither, 0);
		SIXELSTATUS result = sixel_encode(region.data(), rect.width, rect.height, channels, dither, output);
		sixel_dither_unref(dither);
		sixel_output_unref(output);
		if (SIXEL_FAILED(result) || encoded.failed)
			throw std::runtime_error("SIXEL encoding failed or exceeded output limit");
		std::string cup = "\033[" + std::to_string(rect.y / terminal.cellHeight + 1) +
		    ";" + std::to_string(rect.x / terminal.cellWidth + 1) + "H";
		if (frame.size() + cup.size() + encoded.bytes.size() > 32 * 1024 * 1024)
			throw std::runtime_error("SIXEL frame exceeds 32 MiB");
		frame += cup;
		frame += encoded.bytes;
		bytes += encoded.bytes.size();
		pixelsEncoded += static_cast<uint64_t>(rect.width) * rect.height;
	}
	double encodeMs = std::chrono::duration<double, std::milli>(
	    std::chrono::steady_clock::now() - encodeStart).count() - cropMs;
	performance.snapshotMs += cropMs;
	performance.encodeMs += encodeMs;
	performance.maxEncodeMs = std::max(performance.maxEncodeMs, encodeMs);
	performance.frames++;
	performance.encodedBytes += bytes;
	performance.regions += regions.size();
	if (displayWidth != oldWidth || displayHeight != oldHeight)
		terminal.queue("\033[H\033[2J");
	terminal.queue(frame);
	if (photo) previousFrame.swap(rgb);
	else previousFrame.swap(indexed);
	forceFull = false;
	performance.encodedPixels += pixelsEncoded;
	if (regions.size() == 1 && regions[0].width == displayWidth &&
	    regions[0].height == displayHeight)
		performance.fullFrames++;
	else
		performance.partialFrames++;
	status();
	dirty = false;
	return true;
}

void Connection::setCursor(int w, int h, const core::Point& hotspot, const uint8_t* data)
{
	CConnection::setCursor(w, h, hotspot, data);
	cursorKnown = true;
	dirty = true;
}
void Connection::setCursorPos(const core::Point& pos)
{
	pointer = pos;
	dirty = true;
}
void Connection::modifiers(unsigned wanted)
{
	const uint32_t keys[] = {XK_Shift_L, XK_Alt_L, XK_Control_L};
	for (unsigned i = 0; i < 3; i++) {
		unsigned bit = 1u << i;
		if ((held & bit) && !(wanted & bit)) sendKeyRelease(keys[i]);
		if (!(held & bit) && (wanted & bit)) sendKeyPress(keys[i], 0, keys[i]);
	}
	held = wanted;
}
int Connection::inputTimeout() const
{
	return keys.timeout(KeyQueue::Clock::now());
}
void Connection::drainInput()
{
	InputEvent e;
	for (int i = 0; i < 64 && keys.take(KeyQueue::Clock::now(), e); i++) {
		modifiers(e.modifiers);
		sendKeyPress(e.key, 0, e.key);
		sendKeyRelease(e.key);
		modifiers(latched | mouseMods);
	}
}
void Connection::releaseInput()
{
	if (keys.size() || receivingPaste) inputNotice = "Pending input cancelled";
	keys.clear();
	if (receivingPaste) discardPaste = true;
	if (!ready || viewOnly) return;
	sendPointerEvent(pointer, 0);
	releaseAllKeys();
	latched = held = mouseMods = 0;
	buttons = 0;
	prefix = false;
}
void Connection::toggleHelp()
{
	releaseInput();
	prefix = false;
	help = !help;
	helpPage = 0;
	displayWidth = displayHeight = 0;
	redraw();
}
void Connection::status()
{
	if (help) return;
	terminal.queue("\033[" + std::to_string(terminal.height / terminal.cellHeight + 2) +
	    ";1H\033[2KCtrl+] h help, q quit, r redraw, c/a/s latch, u release  [" +
	    ((latched & 4) ? "Ctrl " : "") + ((latched & 2) ? "Alt " : "") +
	    ((latched & 1) ? "Shift" : "") + "] " + inputNotice);
}
bool Connection::input(const InputEvent& e)
{
	if (!ready) return true;
	if (e.kind == InputEvent::PasteBegin) {
		receivingPaste = true;
		discardPaste = false;
		prefix = false;
		return true;
	}
	if (e.kind == InputEvent::PasteEnd) {
		receivingPaste = discardPaste = false;
		return true;
	}
	if (e.pasted) {
		prefix = false;
		if (discardPaste || viewOnly) return true;
	}
	if (e.kind == InputEvent::Refresh) { redraw(); return true; }
	if (help) {
		if (e.kind == InputEvent::FocusOut) releaseInput();
		if (e.kind != InputEvent::Key || e.pasted) return true;
		if (prefix) {
			prefix = false;
			if (e.key == 'q') return false;
			if (e.key == 'h' || e.key == '?') toggleHelp();
		} else if (e.key == ']' && (e.modifiers & 4)) prefix = true;
		else if (e.key == XK_Escape || e.key == XK_Return) toggleHelp();
		else if (e.key == ' ' || e.key == 'n') {
			helpPage = (helpPage + 1) % helpPages;
			helpDirty = true;
		} else if (e.key == 'p') {
			helpPage = (helpPage + helpPages - 1) % helpPages;
			helpDirty = true;
		}
		return true;
	}
	if (!e.pasted && e.kind == InputEvent::Key && prefix &&
	    (e.key == 'h' || e.key == '?')) {
		toggleHelp();
		return true;
	}
	if (viewOnly) {
		if (e.kind == InputEvent::Key && prefix) {
			prefix = false;
			if (e.key == 'q') return false;
			if (e.key == 'r') redraw();
		} else if (e.kind == InputEvent::Key && e.key == ']' &&
		    (e.modifiers & 4)) prefix = true;
		return true;
	}
	if (e.kind == InputEvent::FocusOut) { releaseInput(); status(); return true; }
	if (e.kind == InputEvent::Key) {
		if (!e.pasted && prefix) {
			prefix = false;
			if (e.key == 'q') return false;
			if (e.key == 'r') { redraw(); return true; }
			if (e.key == 'u') { releaseInput(); inputNotice = "Pending paste cancelled"; }
			else if (e.key == 'c') latched ^= 4;
			else if (e.key == 'a') latched ^= 2;
			else if (e.key == 's') latched ^= 1;
			else if (e.key == ']' && (e.modifiers & 4)) {
				modifiers(latched | mouseMods | e.modifiers);
				sendKeyPress(e.key, 0, e.key); sendKeyRelease(e.key);
			}
			modifiers(latched | mouseMods); status(); return true;
		}
		if (!e.pasted && e.key == ']' && (e.modifiers & 4)) { prefix = true; return true; }
		InputEvent queued = e;
		if (!e.pasted) queued.modifiers |= latched | mouseMods;
		if (!keys.push(queued)) {
			keys.clear();
			discardPaste = e.pasted;
			inputNotice = "Input cancelled: 8192-key queue limit";
			status();
		} else if (!e.pasted && keys.size() == 1)
			drainInput();
		return true;
	}
	if (e.button & 128) return true; /* Extra buttons are not mapped yet. */
	int x = e.x, y = e.y;
	if (!terminal.pixelMouse) {
		x = x * terminal.cellWidth + terminal.cellWidth / 2;
		y = y * terminal.cellHeight + terminal.cellHeight / 2;
	}
	if (displayWidth == 0 || displayHeight == 0) return true;
	if ((x >= displayWidth || y >= displayHeight) && !buttons && !e.release) return true;
	x = std::max(0, std::min(displayWidth - 1, x));
	y = std::max(0, std::min(displayHeight - 1, y));
	pointer = {int(int64_t(x) * server.width() / displayWidth),
	    int(int64_t(y) * server.height() / displayHeight)};
	unsigned button = e.button & 3;
	mouseMods = e.modifiers;
	modifiers(latched | mouseMods);
	if (e.button & 64) {
		if (button < 2 && !e.release)
			sendPointerEvent(pointer, buttons | (1u << (3 + button)));
	} else if (!(e.button & 32)) {
		if (button < 3) {
			if (e.release) buttons &= ~(1u << button);
			else buttons |= 1u << button;
		}
	}
	sendPointerEvent(pointer, buttons);
	if (!buttons) mouseMods = 0;
	modifiers(latched | mouseMods);
	dirty = true;
	return true;
}
