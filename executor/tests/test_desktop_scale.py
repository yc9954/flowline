"""Coordinate scaling: model view (≤1280 wide) ↔ display, Retina pixels ↔ points."""
import io

from PIL import Image

from desktop import Screenshot, ViewScale, _xdo_key, scale_png


def test_viewscale_1920_to_1280():
    v = ViewScale.fit(1920, 1080, 1280)
    assert (v.view_w, v.view_h) == (1280, 720)
    assert v.factor == 1.5
    assert v.to_display(640, 360) == (960, 540)
    assert v.to_view(960, 540) == (640, 360)
    assert v.to_display(1238 / 1.5, 514 / 1.5) == (1238, 514)


def test_viewscale_small_display_unchanged():
    v = ViewScale.fit(1024, 768, 1280)
    assert v.factor == 1.0
    assert v.to_display(10, 20) == (10, 20)


def test_retina_screenshot_scale_and_resize():
    # a 3024x1964 PNG for a 1512x982 logical display → scale 2.0
    png = io.BytesIO()
    Image.new("RGB", (3024, 1964), "white").save(png, format="PNG")
    shot = Screenshot(png.getvalue(), 3024, 1964, 1512, 982)
    assert shot.scale == 2.0
    v = ViewScale.fit(1512, 982, 1280)
    assert (v.view_w, v.view_h) == (1280, 831)
    out = Image.open(io.BytesIO(scale_png(shot.png, shot, v)))
    assert out.size == (1280, 831)
    # a click the model makes at the view centre lands at the display centre (points)
    assert v.to_display(640, 415) == (756, 490)


def test_xdo_key_names():
    assert _xdo_key("ctrl+shift+s") == "ctrl+shift+s"
    assert _xdo_key("Return") == "Return"
    assert _xdo_key("enter") == "Return"
    assert _xdo_key("cmd+a") == "super+a"
    assert _xdo_key("Page_Down") == "Next"
    assert _xdo_key("f5") == "F5"
