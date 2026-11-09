"""Cover the desktop (icons, widgets, other windows) with a flat backdrop during the Mac takes.
Runs until killed: `uv run --project ../executor python backdrop.py &` then `pkill -f backdrop.py`.
The window sits just above the desktop level so app windows and the Flowline notch stay on top.
"""
import AppKit, Quartz
from PyObjCTools import AppHelper

app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
screen = AppKit.NSScreen.mainScreen()
frame = screen.frame()
win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
    frame, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False)
win.setLevel_(Quartz.kCGNormalWindowLevel - 1)  # above desktop icons and widgets, below every app window
win.setOpaque_(True)
win.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.878, 0.894, 0.902, 1.0))  # #e0e4e6, like Main.dc.html
win.setIgnoresMouseEvents_(True)
win.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | AppKit.NSWindowCollectionBehaviorStationary)
win.orderFrontRegardless()
AppHelper.runEventLoop()
