"""Interactive native-host developer harness, explicitly NOT a CATIA test.

Requires Windows, pywin32 and a separately built x64 PhyXiWebHost.dll.
Runs the real production DLL in its own STA, never attaches to CNEXT.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
import threading
import pythoncom
import win32con
import win32gui


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dll', type=Path, required=True)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--debug-port', type=int)
    args = p.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.debug_port:
        # Developer harness only. The production CAA entry never enables CDP.
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--remote-debugging-address=127.0.0.1 --remote-debugging-port=' + str(args.debug_port)
    pythoncom.OleInitialize()
    dll = ctypes.WinDLL(str(args.dll.resolve()))
    dll.PhyXiHostStart.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(wintypes.HWND)]
    dll.PhyXiHostStart.restype = ctypes.c_long
    dll.PhyXiHostAttach.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(wintypes.HWND)]
    dll.PhyXiHostAttach.restype = ctypes.c_long
    dll.PhyXiHostResize.argtypes = [wintypes.HWND]
    dll.PhyXiHostResize.restype = ctypes.c_long
    dll.PhyXiHostDetach.argtypes = [wintypes.HWND]
    dll.PhyXiHostDetach.restype = ctypes.c_long
    dll.PhyXiHostStatus.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_uint]
    dll.PhyXiHostStatus.restype = ctypes.c_long
    child = wintypes.HWND()
    destroyed = False

    def proc(hwnd, message, wp, lp):
        nonlocal destroyed
        if message == win32con.WM_SIZE and child.value:
            dll.PhyXiHostResize(child)
        if message == win32con.WM_CLOSE:
            if child.value:
                dll.PhyXiHostDetach(child)
                child.value = None
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == win32con.WM_DESTROY:
            destroyed = True
            return 0
        return win32gui.DefWindowProc(hwnd, message, wp, lp)

    cls = win32gui.WNDCLASS()
    cls.lpszClassName = 'PhyXi.Developer.EmbeddedHost.Smoke'
    cls.lpfnWndProc = proc
    atom = win32gui.RegisterClass(cls)
    hwnd = win32gui.CreateWindow(atom, 'PhyXi native embedding development harness — NOT CATIA',
                                 win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                 60, 60, 1400, 940, 0, 0, 0, None)
    profile = str((args.work / 'webview2-profile').resolve())
    invalid = wintypes.HWND()
    # Refuse remote parent handles and non-loopback navigation before creation.
    remote = dll.PhyXiHostAttach(win32gui.GetDesktopWindow(), 'http://127.0.0.1:1/', profile, ctypes.byref(invalid))
    assert remote == -2147024891 and not invalid.value, hex(remote & 0xffffffff)
    for url in ['https://example.com/', 'http://127.0.0.1:2.evil/', 'http://127.0.0.1:0/', 'http://127.0.0.1:65536/']:
        result = dll.PhyXiHostAttach(hwnd, url, profile, ctypes.byref(invalid))
        assert result == -2147024809 and not invalid.value, (url, result)
    other_thread = []
    def cross_thread():
        out = wintypes.HWND()
        other_thread.append(dll.PhyXiHostAttach(hwnd, 'http://127.0.0.1:1/', profile, ctypes.byref(out)))
    worker = threading.Thread(target=cross_thread); worker.start(); worker.join(5)
    assert other_thread == [-2147024891], other_thread
    # Destruction before asynchronous controller creation must remain harmless.
    for index in range(3):
        early = wintypes.HWND()
        assert dll.PhyXiHostAttach(hwnd, 'http://127.0.0.1:1/', profile + '-early-' + str(index), ctypes.byref(early)) == 0
        assert dll.PhyXiHostDetach(early) == 0
        buffer = ctypes.create_unicode_buffer(1024)
        assert dll.PhyXiHostStatus(early, buffer, len(buffer)) == -2147024890
    (args.work / 'harness-window.json').write_text(json.dumps({'pid': os.getpid(), 'hwnd': hwnd, 'not_catia': True}), encoding='utf-8')
    hr = dll.PhyXiHostStart(hwnd, sys.executable, str(args.app.resolve()), str((args.work / 'workspace').resolve()), profile, ctypes.byref(child))
    assert hr == 0 and child.value, hex(hr & 0xffffffff)
    start = time.monotonic()
    latest = {}
    while not destroyed and time.monotonic() - start < 180:
        pythoncom.PumpWaitingMessages()
        raw = ctypes.create_unicode_buffer(1024)
        if child.value and dll.PhyXiHostStatus(child, raw, len(raw)) == 0:
            latest = json.loads(raw.value)
            if latest.get('ready'):
                assert latest['parent_pid'] == os.getpid() and latest['is_child']
                target = args.work / 'native-host-ready.json'
                if not target.exists(): target.write_text(json.dumps(latest, indent=2), encoding='utf-8')
        if not destroyed and win32gui.IsWindow(hwnd) and (args.work / 'close-harness').exists():
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(.02)
    if not destroyed:
        win32gui.SendMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    for _ in range(100):
        pythoncom.PumpWaitingMessages()
        time.sleep(.02)
    (args.work / 'native-host-result.json').write_text(json.dumps({'last_status': latest,
        'parent_rejection': 'PASS', 'thread_rejection': 'PASS', 'early_close_cycles': 3,
        'url_rejections': 4, 'normal_close': destroyed,
        'host_window_destroyed': not win32gui.IsWindow(hwnd), 'not_catia': True}, indent=2), encoding='utf-8')
    ctypes.OleDLL('ole32').OleUninitialize()
    print('NATIVE_HOST_HARNESS_CLOSED')


if __name__ == '__main__': main()
