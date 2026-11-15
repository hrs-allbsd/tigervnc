/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "TrustStore.h"
#include <gtest/gtest.h>
#include <fstream>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
using namespace sixelvnc;
class KnownHosts : public testing::Test {
protected:
	std::string path;
	void SetUp() override {
		char name[] = "/tmp/vncsixel-trust-XXXXXX";
		int fd = mkstemp(name); ASSERT_GE(fd, 0); close(fd);
		path = name; unlink(path.c_str());
	}
	void TearDown() override { unlink(path.c_str()); }
};
TEST_F(KnownHosts, MatchChangeAndPortIsolation)
{
	TrustStore store(path);
	EXPECT_EQ(store.check("[host]:5900", "key"), TrustStore::Unknown);
	store.remember("[host]:5900", "key");
	EXPECT_EQ(store.check("[host]:5900", "key"), TrustStore::Match);
	EXPECT_EQ(store.check("[host]:5900", "other"), TrustStore::Changed);
	EXPECT_EQ(store.check("[host]:5901", "key"), TrustStore::Unknown);
	EXPECT_THROW(store.remember("[host]:5900", "other"), std::runtime_error);
	store.remember("[host]:5900", "key");
	store.remember("[host]:5901", "other");
	EXPECT_EQ(store.check("[host]:5900", "key"), TrustStore::Match);
	struct stat st; ASSERT_EQ(stat(path.c_str(), &st), 0);
	EXPECT_EQ(st.st_mode & 0777, 0600);
}
TEST_F(KnownHosts, RejectUnsafeAndMalformedFiles)
{
	{ std::ofstream file(path); file << "v1 00 11\nv1 00 11\n"; }
	TrustStore store(path);
	EXPECT_THROW(store.check(std::string(1, '\0'), std::string(1, '\x11')), std::runtime_error);
	{ std::ofstream file(path); file << "v1 00 zz\n"; }
	EXPECT_THROW(store.check("host", "key"), std::runtime_error);
	{ std::ofstream file(path); file << "v1 00 11"; }
	EXPECT_THROW(store.check("host", "key"), std::runtime_error);
	chmod(path.c_str(), 0666);
	EXPECT_THROW(store.check("host", "key"), std::runtime_error);
	unlink(path.c_str()); ASSERT_EQ(symlink("/dev/null", path.c_str()), 0);
	EXPECT_THROW(store.check("host", "key"), std::runtime_error);
	EXPECT_THROW(store.remember("host", "key"), std::runtime_error);
	unlink(path.c_str()); ASSERT_EQ(mkfifo(path.c_str(), 0600), 0);
	EXPECT_THROW(store.check("host", "key"), std::runtime_error);
}
TEST_F(KnownHosts, ConcurrentDifferentKeysCannotReplaceEachOther)
{
	pid_t children[2];
	for (int i = 0; i < 2; i++) {
		children[i] = fork(); ASSERT_GE(children[i], 0);
		if (!children[i]) {
			try { TrustStore(path).remember("host", i ? "b" : "a"); }
			catch (...) { _exit(1); }
			_exit(0);
		}
	}
	int success = 0;
	for (pid_t child : children) {
		int status; ASSERT_EQ(waitpid(child, &status, 0), child);
		ASSERT_TRUE(WIFEXITED(status));
		success += WEXITSTATUS(status) == 0;
	}
	EXPECT_EQ(success, 1);
	EXPECT_NE(TrustStore(path).check("host", "a"), TrustStore::Unknown);
}
TEST_F(KnownHosts, SizeLimitPreventsAppend)
{
	std::string comment = "#" + std::string(1024 * 1024 - 2, 'x') + "\n";
	{ std::ofstream file(path); file << comment; }
	EXPECT_THROW(TrustStore(path).remember("host", "key"), std::runtime_error);
	struct stat st; ASSERT_EQ(stat(path.c_str(), &st), 0);
	EXPECT_EQ(st.st_size, 1024 * 1024);
}
