"""Screenshot of an Arena model's flowchart, so an agent (or its user) can see what was built.

The flowchart pane is zoomed tile by tile with IView.ZoomRegion; after each zoom the visible world extents are read
back (IView.Left/Top/Right/Bottom), so every tile is pasted at its exact place whatever zoom Arena actually chose.
Arena must be visible on screen and not covered by other windows: the tiles are grabbed from the screen.
"""
import ctypes
import math
import os
import time

import win32api
import win32con
import win32gui
from PIL import Image, ImageGrab

from .core import ArenaError, open_model, safe


def _dpi_aware():
    safe(lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2))  # real pixels on scaled displays


def client_rect(h):
    l, t, r, b = win32gui.GetClientRect(h)
    x0, y0 = win32gui.ClientToScreen(h, (l, t))
    x1, y1 = win32gui.ClientToScreen(h, (r, b))
    return x0, y0, x1, y1


def area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def model_window(model_name):
    """The flowchart pane of the model's MDI window (largest Afx:...:8: child that is not the spreadsheet)."""
    tops = []
    win32gui.EnumWindows(lambda h, _: tops.append(h) if win32gui.GetClassName(h) == "SMX:Arena"
                         and win32gui.IsWindowVisible(h) else None, None)
    for top in tops:
        kids = []
        win32gui.EnumChildWindows(top, lambda h, _: kids.append(h), None)
        for k in kids:
            if win32gui.GetClassName(k) == "SMX:Model" and win32gui.GetWindowText(k) == model_name:
                panes = []
                win32gui.EnumChildWindows(k, lambda h, _: panes.append(h), None)
                # the flowchart canvas is the "Afx:<module>:8:..." child; "AfxFrameOrView140" is the spreadsheet
                panes = [p for p in panes if win32gui.GetClassName(p).startswith("Afx:") and ":8:" in
                         win32gui.GetClassName(p) and win32gui.IsWindowVisible(p)]
                if panes:
                    return top, k, max(panes, key=lambda p: area(client_rect(p)))
    raise ArenaError(f"no visible Arena window for model {model_name!r}")


def modules_bbox(m):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for i in range(1, m.Modules.Count + 1):
        md = m.Modules.Item(i)
        if safe(lambda: md.Definition.DataModule, True):
            continue
        sh = safe(lambda: md.shape)
        if sh is None:
            continue
        xs0.append(sh.Left), ys0.append(sh.Top), xs1.append(sh.Right), ys1.append(sh.Bottom)
    if not xs0:
        raise ArenaError("the model has no flowchart modules to show")
    return min(xs0), min(min(ys0), min(ys1)), max(xs1), max(max(ys0), max(ys1))


def snapshot(a, model, out_path, region=None, ppu=None, max_tiles=64):
    """Write a PNG of the flowchart. region: [x0, y0, x1, y1] in model units (default: all flowchart modules).
    ppu: screen pixels per model unit; default fits the region into one screen (readable for small models)."""
    _dpi_aware()
    m = open_model(a, model)
    a.Visible = True
    m.Activate()
    v = m.ActiveView
    # SplitScreen must stay True (False collapses the flowchart pane to zero height); 99% gives the flowchart nearly
    # the whole window, with the spreadsheet squeezed below it
    for prop, val in (("SplitScreen", True), ("SplitScreenPercent", 99), ("Grid", False), ("ShowRulers", False),
                      ("ShowGuides", False), ("ShowPageBreaks", False)):
        safe(lambda: setattr(v, prop, val))
    top, child, pane = model_window(m.Name)
    win32gui.ShowWindow(top, win32con.SW_MAXIMIZE)
    win32gui.ShowWindow(child, win32con.SW_MAXIMIZE)
    safe(lambda: win32gui.SetForegroundWindow(top))
    safe(lambda: win32api.SetCursorPos((5, 5)))
    time.sleep(0.8)
    pr = client_rect(pane)
    pw, ph = pr[2] - pr[0], pr[3] - pr[1]
    if region:
        X0, Y0, X1, Y1 = (float(x) for x in region)
    else:
        X0, Y0, X1, Y1 = modules_bbox(m)
        mg = 400
        X0, Y0, X1, Y1 = X0 - mg, Y0 - mg, X1 + mg, Y1 + mg
    if not ppu:
        ppu = min(pw / (X1 - X0), ph / abs(Y1 - Y0)) * 0.9  # one tile
    tw, th = pw / ppu * 0.92, ph / ppu * 0.92  # tile step in world units (8% overlap)
    nx, ny = max(1, math.ceil((X1 - X0) / tw)), max(1, math.ceil(abs(Y1 - Y0) / th))
    if nx * ny > max_tiles:
        raise ArenaError(f"{nx * ny} tiles needed at ppu={ppu}; lower ppu or pick a smaller region")
    tiles = []
    for j in range(ny):
        for i in range(nx):
            x, y = X0 + i * tw, Y0 + j * th
            v.ZoomRegion(x, y, x + pw / ppu, y + ph / ppu)
            time.sleep(0.5)
            tiles.append((v.Left, v.Top, v.Right, v.Bottom, ImageGrab.grab(bbox=pr, all_screens=True)))
    L, T, R, B, _ = tiles[0]
    sx = pw / (R - L)
    sy = ph / (B - T)  # negative if world y grows upward on screen
    W = max(1, int(round((X1 - X0) * sx)))
    H = max(1, int(round(abs((Y1 - Y0) * sy))))
    canvas = Image.new("RGB", (W, H), "white")
    for L, T, R, B, img in tiles:
        px = int(round((L - X0) * sx))
        py = int(round((T - Y0) * sy)) if sy > 0 else int(round((Y1 - T) * -sy))
        canvas.paste(img, (px, py))
    out_path = os.path.abspath(out_path)
    canvas.save(out_path)
    return {"out": out_path, "size": [W, H], "tiles": len(tiles), "region": [X0, Y0, X1, Y1],
            "note": "grabbed from the screen: if it shows another window, bring Arena to the front and retry"}
