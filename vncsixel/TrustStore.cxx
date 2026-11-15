/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "TrustStore.h"
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <sstream>
#include <stdexcept>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

using namespace sixelvnc;
namespace {
struct File {
	int fd;
	explicit File(int value) : fd(value) {}
	~File() { if (fd >= 0) close(fd); }
};
bool validHex(const std::string& text)
{
	if (text.empty() || text.size() % 2) return false;
	return text.find_first_not_of("0123456789abcdef") == std::string::npos;
}
}
std::string TrustStore::hex(const void* data, size_t length)
{
	const auto* bytes = static_cast<const unsigned char*>(data);
	std::string result;
	for (size_t i = 0; i < length; i++) {
		result += "0123456789abcdef"[bytes[i] >> 4];
		result += "0123456789abcdef"[bytes[i] & 15];
	}
	return result;
}
TrustStore::State TrustStore::read(int fd, const std::string& host,
    const std::string& key) const
{
	struct stat st;
	if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
	    (st.st_mode & 022) || st.st_size > 1024 * 1024)
		throw std::runtime_error("Unsafe RSA known-hosts file type, owner, permissions or size");
	if (lseek(fd, 0, SEEK_SET) < 0)
		throw std::runtime_error("Cannot seek RSA known-hosts file");
	std::string text;
	char buffer[4096];
	for (;;) {
		ssize_t n = ::read(fd, buffer, sizeof(buffer));
		if (n < 0 && errno == EINTR) continue;
		if (n < 0) throw std::runtime_error("Cannot read RSA known-hosts file");
		if (!n) break;
		text.append(buffer, n);
		if (text.size() > 1024 * 1024)
			throw std::runtime_error("RSA known-hosts file exceeds 1 MiB");
	}
	State result = Unknown;
	std::istringstream input(text);
	std::string line;
	while (std::getline(input, line)) {
		if (line.empty() || line[0] == '#') continue;
		std::istringstream record(line);
		std::string version, endpoint, value, extra;
		if (!(record >> version >> endpoint >> value) || record >> extra ||
		    version != "v1" || !validHex(endpoint) || !validHex(value))
			throw std::runtime_error("Malformed RSA known-hosts file");
		if (endpoint == hex(host.data(), host.size())) {
			if (result != Unknown)
				throw std::runtime_error("Duplicate RSA known-hosts entry");
			result = value == hex(key.data(), key.size()) ? Match : Changed;
		}
	}
	if (!text.empty() && text.back() != '\n')
		throw std::runtime_error("Incomplete RSA known-hosts record");
	return result;
}
TrustStore::State TrustStore::check(const std::string& host,
    const std::string& key) const
{
	File file(open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK));
	if (file.fd < 0) {
		if (errno == ENOENT) return Unknown;
		throw std::runtime_error("Cannot open RSA known-hosts file");
	}
	if (flock(file.fd, LOCK_SH) < 0)
		throw std::runtime_error("Cannot lock RSA known-hosts file");
	return read(file.fd, host, key);
}
void TrustStore::remember(const std::string& host, const std::string& key) const
{
	if (host.empty() || host.size() > 1024 || key.empty() || key.size() > 4096)
		throw std::runtime_error("Invalid RSA known-hosts record size");
	File file(open(path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600));
	if (file.fd < 0 || flock(file.fd, LOCK_EX) < 0)
		throw std::runtime_error("Cannot create or lock RSA known-hosts file");
	State state = read(file.fd, host, key);
	if (state == Match) return;
	if (state == Changed)
		throw std::runtime_error("RSA host key changed while confirming; connection rejected");
	std::string record = "v1 " + hex(host.data(), host.size()) + " " +
	    hex(key.data(), key.size()) + "\n";
	off_t end = lseek(file.fd, 0, SEEK_END);
	if (end < 0 || static_cast<uint64_t>(end) + record.size() > 1024 * 1024)
		throw std::runtime_error("Cannot append RSA known-hosts file (seek or size limit)");
	for (size_t offset = 0; offset < record.size();) {
		ssize_t n = write(file.fd, record.data() + offset, record.size() - offset);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) throw std::runtime_error("Cannot save RSA host key; connection rejected");
		offset += n;
	}
	if (fsync(file.fd) < 0)
		throw std::runtime_error("Cannot sync RSA host key; connection rejected");
}
