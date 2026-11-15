/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "HostCursor.h"
#include <core/Configuration.h>
#ifdef HAVE_HOST_XFIXES
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>
#include <cerrno>
#include <cstdlib>
#include <dlfcn.h>
#endif

using namespace sixelvnc;
namespace {
core::BoolParameter hideLocalCursor("HideLocalCursor",
    "Hide the local X11 pointer over the remote image", true);
}
#ifdef HAVE_HOST_XFIXES
namespace {
template<class T> bool symbol(void* library, const char* name, T& target)
{
	target = reinterpret_cast<T>(dlsym(library, name));
	return target != nullptr;
}
int ignoreError(Display*, XErrorEvent*) { return 0; }
}
struct HostCursor::Impl {
	void* x11 = nullptr;
	void* fixes = nullptr;
	Display* display = nullptr;
	Window window = None, eventsWindow = None;
	XErrorHandler previousHandler = nullptr;
	bool hidden = false, enabled = false, focused = false;
	int width = 0, height = 0, textWidth = 0, textHeight = 0;
	int originX = 0, originY = 0, px = -1, py = -1;
	int vtX = 0, vtY = 0;
#define FN(name) decltype(&::name) name = nullptr
	FN(XOpenDisplay); FN(XCloseDisplay); FN(XGetWindowAttributes);
	FN(XSetErrorHandler); FN(XSync); FN(XSelectInput); FN(XQueryPointer);
	FN(XPending); FN(XNextEvent); FN(XFlush); FN(XGetInputFocus);
	FN(XQueryTree); FN(XFree);
	FN(XFixesQueryVersion); FN(XFixesHideCursor); FN(XFixesShowCursor);
#undef FN
	Impl()
	{
		if (!hideLocalCursor) return;
		const char* id = getenv("WINDOWID");
		const char* address = getenv("DISPLAY");
		if (!id || !address || !*address) return;
		char* end;
		errno = 0;
		unsigned long value = strtoul(id, &end, 0);
		if (errno || end == id || *end || !value || *id == '-') return;
		x11 = dlopen("libX11.so.6", RTLD_NOW | RTLD_LOCAL);
		fixes = dlopen("libXfixes.so.3", RTLD_NOW | RTLD_LOCAL);
		if (!x11 || !fixes) return;
#define LOAD(library, name) if (!symbol(library, #name, name)) return
		LOAD(x11, XOpenDisplay); LOAD(x11, XCloseDisplay);
		LOAD(x11, XGetWindowAttributes); LOAD(x11, XSetErrorHandler);
		LOAD(x11, XSync); LOAD(x11, XSelectInput); LOAD(x11, XQueryPointer);
		LOAD(x11, XPending); LOAD(x11, XNextEvent); LOAD(x11, XFlush);
		LOAD(x11, XGetInputFocus); LOAD(x11, XQueryTree); LOAD(x11, XFree);
		LOAD(fixes, XFixesQueryVersion); LOAD(fixes, XFixesHideCursor);
		LOAD(fixes, XFixesShowCursor);
#undef LOAD
		display = XOpenDisplay(address);
		if (!display) return;
		previousHandler = XSetErrorHandler(ignoreError);
		int major = 4, minor = 0;
		XWindowAttributes attributes;
		if (!XFixesQueryVersion(display, &major, &minor) || major < 4 ||
		    !XGetWindowAttributes(display, value, &attributes)) return;
		window = value;
		XSelectInput(display, window, EnterWindowMask | LeaveWindowMask |
		    PointerMotionMask | FocusChangeMask | StructureNotifyMask);
		XFlush(display);
	}
	~Impl()
	{
		if (display) {
			setHidden(false);
			XCloseDisplay(display);
			XSetErrorHandler(previousHandler);
		}
		if (fixes) dlclose(fixes);
		if (x11) dlclose(x11);
	}
	void setHidden(bool value)
	{
		if (!window || value == hidden) return;
		if (value) XFixesHideCursor(display, window);
		else XFixesShowCursor(display, window);
		hidden = value;
		XFlush(display);
	}
	bool ownsFocus(Window focus)
	{
		if (focus == PointerRoot) return true;
		for (int depth = 0; focus && depth < 16; depth++) {
			if (focus == window) return true;
			Window root, parent, *children = nullptr;
			unsigned count = 0;
			if (!XQueryTree(display, focus, &root, &parent, &children, &count))
				return false;
			if (children) XFree(children);
			if (focus == parent) break;
			focus = parent;
		}
		return false;
	}
	void position()
	{
		Window root, child, focus;
		int rx, ry, revert;
		unsigned mask;
		if (!XQueryPointer(display, window, &root, &child, &rx, &ry,
		    &px, &py, &mask)) px = py = -1;
		XGetInputFocus(display, &focus, &revert);
		focused = ownsFocus(focus);
	}
	void geometry()
	{
		Window vt = window, root, parent, *children = nullptr;
		unsigned count = 0;
		XWindowAttributes attributes;
		originX = originY = 0;
		if (!XGetWindowAttributes(display, window, &attributes)) return;
		/* WINDOWID names xterm's shell; its large child is the VT widget. */
		if (XQueryTree(display, window, &root, &parent, &children, &count)) {
			for (unsigned i = 0; i < count; i++) {
				XWindowAttributes candidate;
				if (XGetWindowAttributes(display, children[i], &candidate) &&
				    candidate.width >= textWidth && candidate.height >= textHeight) {
					vt = children[i];
					attributes = candidate;
					originX = candidate.x;
					originY = candidate.y;
					break;
				}
			}
			if (children) XFree(children);
		}
		vtX = originX;
		vtY = originY;
		if (vt != window && vt != eventsWindow) {
			XSelectInput(display, vt, EnterWindowMask | LeaveWindowMask |
			    PointerMotionMask | FocusChangeMask | StructureNotifyMask);
			eventsWindow = vt;
			XFlush(display);
		}
		int border = (attributes.height - textHeight) / 2;
		if (border < 0 || border > 256) return;
		originX += border;
		originY += border;
		int extra = attributes.width - textWidth - 2 * border;
		children = nullptr;
		if (extra > 0 && XQueryTree(display, vt, &root, &parent, &children, &count)) {
			for (unsigned i = 0; i < count; i++) {
				XWindowAttributes bar;
				if (XGetWindowAttributes(display, children[i], &bar) &&
				    bar.x <= border && bar.width <= extra + 2 &&
				    bar.height >= textHeight) {
					originX += extra;
					break;
				}
			}
			if (children) XFree(children);
		}
	}
	void update(bool active, int w, int h, int tw, int th)
	{
		if (!window) return;
		bool changed = enabled != active || width != w || height != h ||
		    textWidth != tw || textHeight != th;
		enabled = active; width = w; height = h;
		textWidth = tw; textHeight = th;
		bool query = changed, layout = changed;
		while (XPending(display)) {
			XEvent event;
			XNextEvent(display, &event);
			if (event.type == DestroyNotify) {
				window = None;
				hidden = false;
				return;
			}
			if (event.type == MotionNotify) {
				px = event.xmotion.x + (event.xmotion.window == eventsWindow ? vtX : 0);
				py = event.xmotion.y + (event.xmotion.window == eventsWindow ? vtY : 0);
			} else if (event.type == EnterNotify || event.type == LeaveNotify ||
			    event.type == FocusIn || event.type == FocusOut) query = true;
			else if (event.type == ConfigureNotify) layout = query = true;
		}
		if (layout && tw > 0 && th > 0) geometry();
		if (query) position();
		setHidden(enabled && focused && px >= originX && py >= originY &&
		    px < originX + width && py < originY + height);
	}
};
#else
struct HostCursor::Impl {
	void update(bool, int, int, int, int) {}
	void setHidden(bool) {}
};
#endif
HostCursor::HostCursor() : impl(new Impl) {}
HostCursor::~HostCursor() = default;
void HostCursor::update(bool active, int w, int h, int tw, int th)
{
	impl->update(active, w, h, tw, th);
}
void HostCursor::show() { impl->setHidden(false); }
