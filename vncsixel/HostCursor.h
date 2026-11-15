/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef VNCSIXEL_HOSTCURSOR_H
#define VNCSIXEL_HOSTCURSOR_H
#include <memory>

namespace sixelvnc {
class HostCursor {
public:
	HostCursor();
	~HostCursor();
	void update(bool, int, int, int, int);
	void show();
private:
	struct Impl;
	std::unique_ptr<Impl> impl;
};
}
#endif
