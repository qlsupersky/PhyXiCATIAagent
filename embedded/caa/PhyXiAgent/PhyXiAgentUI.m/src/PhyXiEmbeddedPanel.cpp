#include "PhyXiEmbeddedPanel.h"
#include "CATDlgWindows.h"
#include <string>
#include <vector>

namespace {
HMODULE host = NULL; // Pinned for asynchronous COM callbacks; never hot-unloaded.
typedef HRESULT (__stdcall *StartFn)(HWND,const wchar_t*,const wchar_t*,const wchar_t*,const wchar_t*,HWND*);
typedef HRESULT (__stdcall *WindowFn)(HWND);
std::wstring Read(const wchar_t* key) {
    wchar_t config[32768] = {}, buffer[32768] = {};
    DWORD count = GetEnvironmentVariableW(L"PHYXI_EMBEDDED_CONFIG",config,32768);
    if (!count || count >= 32768) return L"";
    GetPrivateProfileStringW(L"PhyXi",key,L"",buffer,32768,config);
    return buffer;
}
}
PhyXiEmbeddedPanel::PhyXiEmbeddedPanel(CATDialog* parent)
    : CATDlgDialog(parent,"PhyXiEmbeddedPanel",CATDlgWndChildMDI | CATDlgWndResizable), child_(NULL) {
    // ChildMDI is a native child INSIDE the frame, not a floating outer form.
    SetTitle("PhyXi - Native Modeling Workspace (Experimental)");
    AddAnalyseNotificationCB(this,GetWindSizeNotification(),(CATCommandMethod)&PhyXiEmbeddedPanel::OnSize,NULL);
    AddAnalyseNotificationCB(this,GetWindCloseNotification(),(CATCommandMethod)&PhyXiEmbeddedPanel::OnClose,NULL);
    AddAnalyseNotificationCB(this,GetMDICloseNotification(),(CATCommandMethod)&PhyXiEmbeddedPanel::OnClose,NULL);
}
PhyXiEmbeddedPanel::~PhyXiEmbeddedPanel() {
    if (host && child_) {
        WindowFn detach = (WindowFn)GetProcAddress(host,"PhyXiHostDetach");
        if (detach && IsWindow(child_)) detach(child_);
    }
}
void PhyXiEmbeddedPanel::Open() {
    if (!child_) SetRectDimensions(0,0,800,1200);
    SetVisibility(CATDlgShow);
    if (child_ && IsWindow(child_)) { OnSize(NULL,NULL,NULL); return; }
    const std::wstring dll = Read(L"host_dll"), python = Read(L"python"), root = Read(L"app_dir"), workspace = Read(L"workspace"), profile = Read(L"webview_profile");
    if (dll.empty() || python.empty() || root.empty() || workspace.empty() || profile.empty()) {
        SetTitle("PhyXi: missing private configuration; see embedded deployment instructions"); return;
    }
    if (!host) host = LoadLibraryExW(dll.c_str(),NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
    StartFn start = host ? (StartFn)GetProcAddress(host,"PhyXiHostStart") : NULL;
    const HWND parent = (HWND)GetWindowHandle();
    HRESULT hr = start ? start(parent,python.c_str(),root.c_str(),workspace.c_str(),profile.c_str(),&child_) : E_NOINTERFACE;
    if (FAILED(hr)) SetTitle("PhyXi: embedded initialization failed; no CAD command was dispatched");
}
void PhyXiEmbeddedPanel::OnSize(CATCommand*, CATNotification*, CATCommandClientData) {
    WindowFn resize = host ? (WindowFn)GetProcAddress(host,"PhyXiHostResize") : NULL;
    if (resize && child_ && IsWindow(child_)) resize(child_);
}
void PhyXiEmbeddedPanel::OnClose(CATCommand*, CATNotification*, CATCommandClientData) {
    WindowFn detach = host ? (WindowFn)GetProcAddress(host,"PhyXiHostDetach") : NULL;
    if (detach && child_ && IsWindow(child_)) detach(child_);
    child_ = NULL;
    SetVisibility(CATDlgHide);
}
