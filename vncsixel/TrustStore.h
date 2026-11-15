/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_TRUSTSTORE_H
#define VNCSIXEL_TRUSTSTORE_H
#include <string>

namespace sixelvnc {
class TrustStore {
public:
	enum State { Unknown, Match, Changed };
	explicit TrustStore(const std::string& filename) : path(filename) {}
	State check(const std::string&, const std::string&) const;
	void remember(const std::string&, const std::string&) const;
	static std::string hex(const void*, size_t);
private:
	State read(int, const std::string&, const std::string&) const;
	std::string path;
};
}
#endif
