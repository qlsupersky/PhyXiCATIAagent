#define PHYXI_HOST_BUILD
#include "PhyXiWebHost.h"
#include <objbase.h>
#include <WebView2.h>
#include <atomic>
#include <functional>
#include <memory>
#include <string>
#include <vector>
#include <thread>
#include <mutex>
#include <regex>

namespace {
const wchar_t* kClass = L"PhyXi.Catia.WebView2.Child.v1";
HMODULE module;
const UINT kBackendReady = WM_APP + 117;
// Module is pinned once used: WebView2 may hold COM callback vtables after close.
struct State {
    HWND hwnd = nullptr;
    std::atomic<bool> closed{false};
    bool ready = false;
    HRESULT error = S_OK;
    ICoreWebView2Controller* controller = nullptr;
    ICoreWebView2* web = nullptr;
    std::wstring url, origin, profile;
    std::mutex backendMutex;
    std::wstring pendingUrl;
    HRESULT pendingError = S_OK;
    HANDLE backendInput = nullptr;
    ~State() { if (web) web->Release(); if (controller) controller->Release(); }
    void Close() {
        closed = true; ready = false;
        if (controller) controller->Close();
        std::lock_guard<std::mutex> lock(backendMutex);
        // EOF stops only the local observer. It does not terminate CAD/OpenCode.
        if (backendInput) { CloseHandle(backendInput); backendInput = nullptr; }
    }
};
using Shared = std::shared_ptr<State>;
template<class Interface, class... Args> class Callback final : public Interface {
    std::atomic<ULONG> refs{1};
    IID iid{};
    std::function<HRESULT(Args...)> fn;
public:
    Callback(const wchar_t* id, std::function<HRESULT(Args...)> f) : fn(f) { IIDFromString(id, &iid); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (IsEqualIID(id, IID_IUnknown) || IsEqualIID(id, iid)) { *out = this; AddRef(); return S_OK; }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { ULONG n = --refs; if (!n) delete this; return n; }
    HRESULT STDMETHODCALLTYPE Invoke(Args... args) override {
        // Never allow a C++ exception to cross the CATIA/COM boundary.
        try { return fn(args...); } catch (...) { return E_FAIL; }
    }
};
template<class I, class... A, class F> Callback<I,A...>* callback(const wchar_t* id, F fn) {
    return new Callback<I,A...>(id, fn);
}
bool SameOrigin(const std::wstring& url, const std::wstring& origin) {
    if (url.compare(0, origin.size(), origin)) return false;
    return url.size() == origin.size() || url[origin.size()] == L'/' || url[origin.size()] == L'#' || url[origin.size()] == L'?';
}
bool LocalUrl(const std::wstring& url, std::wstring& origin) {
    const std::wstring prefix = L"http://127.0.0.1:";
    if (url.compare(0, prefix.size(), prefix)) return false;
    size_t end = url.find_first_not_of(L"0123456789", prefix.size());
    if (end == std::wstring::npos) end = url.size();
    const auto digits = url.substr(prefix.size(), end-prefix.size());
    if (digits.empty() || digits.size() > 5) return false;
    const auto port = std::stoul(digits);
    if (!port || port > 65535) return false;
    origin = url.substr(0, end);
    return SameOrigin(url, origin);
}
void Failure(Shared s, HRESULT hr) { s->error = hr; s->ready = false; if (IsWindow(s->hwnd)) InvalidateRect(s->hwnd, nullptr, TRUE); }
HRESULT Resize(Shared s) {
    if (s->closed || !IsWindow(s->hwnd)) return E_HANDLE;
    RECT r{}; GetClientRect(GetParent(s->hwnd), &r);
    SetWindowPos(s->hwnd, nullptr, 0, 0, r.right, r.bottom, SWP_NOZORDER | SWP_NOACTIVATE);
    GetClientRect(s->hwnd, &r);
    return s->controller ? s->controller->put_Bounds(r) : S_OK;
}
void Configure(Shared s, ICoreWebView2Controller* controller) {
    controller->AddRef(); s->controller = controller;
    HRESULT hr = controller->get_CoreWebView2(&s->web);
    if (FAILED(hr)) { Failure(s,hr); return; }
    ICoreWebView2Settings* settings = nullptr;
    if (SUCCEEDED(s->web->get_Settings(&settings))) {
        settings->put_AreDevToolsEnabled(FALSE);
        settings->put_IsStatusBarEnabled(FALSE);
        settings->put_AreDefaultContextMenusEnabled(FALSE);
        settings->put_IsScriptEnabled(TRUE);
        settings->Release();
    }
    EventRegistrationToken event{};
    const std::weak_ptr<State> weak = s;
    auto nav = callback<ICoreWebView2NavigationStartingEventHandler,ICoreWebView2*,ICoreWebView2NavigationStartingEventArgs*>(
        L"{9adbe429-f36d-432b-9ddc-f8881fbd76e3}", [weak](ICoreWebView2*, ICoreWebView2NavigationStartingEventArgs* a) {
        auto s = weak.lock(); if (!s || s->closed) return a->put_Cancel(TRUE);
        LPWSTR uri = nullptr; if (FAILED(a->get_Uri(&uri))) return E_FAIL;
        bool allow = SameOrigin(uri ? uri : L"", s->origin); CoTaskMemFree(uri);
        return a->put_Cancel(allow ? FALSE : TRUE);
    });
    hr = s->web->add_NavigationStarting(nav,&event); nav->Release();
    if (FAILED(hr)) { Failure(s,hr); return; }
    auto popup = callback<ICoreWebView2NewWindowRequestedEventHandler,ICoreWebView2*,ICoreWebView2NewWindowRequestedEventArgs*>(
        L"{d4c185fe-c81c-4989-97af-2d3fa7ab5651}", [](ICoreWebView2*, ICoreWebView2NewWindowRequestedEventArgs* a) { return a->put_Handled(TRUE); });
    hr = s->web->add_NewWindowRequested(popup,&event); popup->Release();
    if (FAILED(hr)) { Failure(s,hr); return; }
    auto permission = callback<ICoreWebView2PermissionRequestedEventHandler,ICoreWebView2*,ICoreWebView2PermissionRequestedEventArgs*>(
        L"{15e1c6a3-c72a-4df3-91d7-d097fbec6bfd}", [weak](ICoreWebView2*, ICoreWebView2PermissionRequestedEventArgs* a) {
        auto s = weak.lock(); if (!s || s->closed) return a->put_State(COREWEBVIEW2_PERMISSION_STATE_DENY);
        COREWEBVIEW2_PERMISSION_KIND kind; BOOL user = FALSE; LPWSTR uri = nullptr;
        if (FAILED(a->get_PermissionKind(&kind)) || FAILED(a->get_IsUserInitiated(&user)) || FAILED(a->get_Uri(&uri))) return E_FAIL;
        bool allow = user && kind == COREWEBVIEW2_PERMISSION_KIND_CLIPBOARD_READ && SameOrigin(uri ? uri : L"",s->origin);
        CoTaskMemFree(uri);
        return a->put_State(allow ? COREWEBVIEW2_PERMISSION_STATE_ALLOW : COREWEBVIEW2_PERMISSION_STATE_DENY);
    });
    hr = s->web->add_PermissionRequested(permission,&event); permission->Release();
    if (FAILED(hr)) { Failure(s,hr); return; }
    Resize(s); controller->put_IsVisible(TRUE);
    hr = s->web->Navigate(s->url.c_str());
    if (FAILED(hr)) { Failure(s,hr); return; }
    s->ready = true;
    // Do not retain the bearer fragment in the host's status data.
    s->url.clear();
}
void Init(Shared s) {
    std::vector<wchar_t> file(32768); GetModuleFileNameW(module, file.data(), static_cast<DWORD>(file.size()));
    std::wstring path(file.data()); path = path.substr(0,path.find_last_of(L"\\/")+1)+L"WebView2Loader.dll";
    HMODULE loader = LoadLibraryExW(path.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!loader) { Failure(s,HRESULT_FROM_WIN32(GetLastError())); return; }
    // Loader remains loaded while asynchronous callbacks exist.
    auto create = reinterpret_cast<decltype(&CreateCoreWebView2EnvironmentWithOptions)>(GetProcAddress(loader,"CreateCoreWebView2EnvironmentWithOptions"));
    if (!create) { Failure(s,E_NOINTERFACE); return; }
    auto env = callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler,HRESULT,ICoreWebView2Environment*>(
        L"{4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d}", [s](HRESULT hr, ICoreWebView2Environment* e) {
        if (s->closed) return S_OK;
        if (FAILED(hr) || !e) { Failure(s,FAILED(hr)?hr:E_FAIL); return S_OK; }
        auto view = callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler,HRESULT,ICoreWebView2Controller*>(
            L"{6c4819f3-c9b7-4260-8127-c9f5bde7f68c}", [s](HRESULT result, ICoreWebView2Controller* c) {
            if (s->closed) { if (c) c->Close(); return S_OK; }
            if (FAILED(result) || !c) { Failure(s,FAILED(result)?result:E_FAIL); return S_OK; }
            Configure(s,c); return S_OK;
        });
        HRESULT result = e->CreateCoreWebView2Controller(s->hwnd,view); view->Release();
        if (FAILED(result)) Failure(s,result);
        return S_OK;
    });
    HRESULT hr = create(nullptr,s->profile.c_str(),nullptr,env); env->Release();
    if (FAILED(hr)) Failure(s,hr);
}
Shared Get(HWND hwnd) {
    wchar_t name[80]{};
    if (!IsWindow(hwnd) || !GetClassNameW(hwnd,name,80) || wcscmp(name,kClass)) return {};
    if (GetWindowThreadProcessId(hwnd,nullptr) != GetCurrentThreadId()) return {};
    auto ptr = reinterpret_cast<Shared*>(GetWindowLongPtrW(hwnd,GWLP_USERDATA));
    return ptr ? *ptr : Shared{};
}
std::wstring Quote(const std::wstring& value) {
    // CommandLineToArgvW quoting; CreateProcess uses an explicit executable.
    std::wstring result = L"\""; size_t slashes = 0;
    for (auto ch : value) {
        if (ch == L'\\') { ++slashes; continue; }
        if (ch == L'\"') result.append(slashes * 2 + 1, L'\\');
        else result.append(slashes, L'\\');
        slashes = 0; result += ch;
    }
    result.append(slashes * 2, L'\\'); result += L'\"'; return result;
}
void StartBackend(Shared s, std::wstring python, std::wstring root, std::wstring workspace) {
    // The lifetime worker never calls COM or changes window controls.
    std::thread([s,python,root,workspace]() {
        HANDLE read = nullptr, childOut = nullptr, input = nullptr, childIn = nullptr;
        PROCESS_INFORMATION process{};
        HRESULT error = E_FAIL;
        auto finish = [&] {
            { std::lock_guard<std::mutex> lock(s->backendMutex); if (s->backendInput) { CloseHandle(s->backendInput); s->backendInput = nullptr; } }
            if (read) CloseHandle(read);
            if (childOut) CloseHandle(childOut);
            if (childIn) CloseHandle(childIn);
            if (input) CloseHandle(input);
            if (process.hThread) CloseHandle(process.hThread);
            if (process.hProcess) CloseHandle(process.hProcess);
        };
        auto publish = [&](HRESULT hr, const std::wstring& url) {
            { std::lock_guard<std::mutex> lock(s->backendMutex); s->pendingError = hr; s->pendingUrl = url; }
            if (!s->closed) PostMessageW(s->hwnd,kBackendReady,0,0);
        };
        try {
            SECURITY_ATTRIBUTES sa{sizeof(sa),nullptr,TRUE};
            if (!CreatePipe(&read,&childOut,&sa,0) || !CreatePipe(&childIn,&input,&sa,0)) { publish(HRESULT_FROM_WIN32(GetLastError()),L""); finish(); return; }
            SetHandleInformation(read,HANDLE_FLAG_INHERIT,0); SetHandleInformation(input,HANDLE_FLAG_INHERIT,0);
            // Explicit handle list: do not leak CATIA document/license handles.
            SIZE_T bytes = 0; InitializeProcThreadAttributeList(nullptr,1,0,&bytes);
            std::vector<unsigned char> attributes(bytes);
            auto list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes.data());
            if (!InitializeProcThreadAttributeList(list,1,0,&bytes)) { publish(HRESULT_FROM_WIN32(GetLastError()),L""); finish(); return; }
            HANDLE handles[]{childIn,childOut};
            if (!UpdateProcThreadAttribute(list,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles,sizeof(handles),nullptr,nullptr)) {
                error = HRESULT_FROM_WIN32(GetLastError()); DeleteProcThreadAttributeList(list); publish(error,L""); finish(); return;
            }
            STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup);
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
            startup.StartupInfo.wShowWindow = SW_HIDE;
            startup.StartupInfo.hStdInput = childIn; startup.StartupInfo.hStdOutput = childOut;
            startup.StartupInfo.hStdError = childOut; startup.lpAttributeList = list;
            std::wstring command = Quote(python)+L" -u "+Quote(root+L"\\web_server.py")+L" --descriptor-stdout --workspace "+Quote(workspace);
            BOOL created = CreateProcessW(python.c_str(),&command[0],nullptr,nullptr,TRUE,
                CREATE_NO_WINDOW|EXTENDED_STARTUPINFO_PRESENT,nullptr,root.c_str(),&startup.StartupInfo,&process);
            error = created ? S_OK : HRESULT_FROM_WIN32(GetLastError());
            DeleteProcThreadAttributeList(list);
            CloseHandle(childOut); childOut = nullptr; CloseHandle(childIn); childIn = nullptr;
            if (!created) { publish(error,L""); finish(); return; }
            { std::lock_guard<std::mutex> lock(s->backendMutex); if (!s->closed) { s->backendInput = input; input = nullptr; } }
            std::string text;
            const auto deadline = GetTickCount64()+20000;
            bool sent = false;
            while (!s->closed && GetTickCount64() < deadline) {
                DWORD available = 0;
                if (!PeekNamedPipe(read,nullptr,0,nullptr,&available,nullptr)) break;
                if (available) {
                    char data[4096]; DWORD count = 0;
                    if (!ReadFile(read,data,(std::min)(available,static_cast<DWORD>(sizeof(data))),&count,nullptr)) break;
                    text.append(data,count);
                    // Never log or expose the pipe, including possible provider text.
                    if (text.size() > 16384) break;
                    auto nl = text.find('\n');
                    if (nl != std::string::npos) {
                        std::regex descriptor(R"REGEX(^\{"url":\s*"(http://127\.0\.0\.1:[0-9]{1,5})",\s*"token":\s*"([A-Za-z0-9_-]{32,128})"\}\r?$)REGEX");
                        std::smatch match; auto line = text.substr(0,nl);
                        if (!std::regex_match(line,match,descriptor)) break;
                        auto url = match[1].str()+"/#token="+match[2].str();
                        publish(S_OK,std::wstring(url.begin(),url.end())); sent = true; break;
                    }
                }
                if (WaitForSingleObject(process.hProcess,40) == WAIT_OBJECT_0) break;
            }
            if (!sent && !s->closed) publish(HRESULT_FROM_WIN32(ERROR_TIMEOUT),L"");
            // Preserve stdin until detach. No overall lifetime limit or CAD retry.
            while (sent && !s->closed && WaitForSingleObject(process.hProcess,100) == WAIT_TIMEOUT) {}
            if (sent && !s->closed) publish(HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE),L"");
            { std::lock_guard<std::mutex> lock(s->backendMutex); if (s->backendInput) { CloseHandle(s->backendInput); s->backendInput = nullptr; } }
            if (process.hProcess) WaitForSingleObject(process.hProcess,5000); // no forced termination
        } catch (...) { if (!s->closed) publish(E_FAIL,L""); }
        finish();
    }).detach();
}
LRESULT CALLBACK Proc(HWND hwnd, UINT msg, WPARAM w, LPARAM l) {
    if (msg == WM_NCCREATE) {
        auto source = static_cast<Shared*>(reinterpret_cast<CREATESTRUCTW*>(l)->lpCreateParams);
        auto ptr = new Shared(*source);
        SetWindowLongPtrW(hwnd,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(ptr)); (*ptr)->hwnd = hwnd;
    }
    auto s = Get(hwnd);
    if (s) {
        if (msg == kBackendReady) {
            std::lock_guard<std::mutex> lock(s->backendMutex);
            if (FAILED(s->pendingError)) Failure(s,s->pendingError);
            else {
                s->url.swap(s->pendingUrl);
                if (!LocalUrl(s->url,s->origin)) Failure(s,E_INVALIDARG); else Init(s);
            }
            return 0;
        }
        if (msg == WM_SIZE && s->controller) { RECT r{}; GetClientRect(hwnd,&r); s->controller->put_Bounds(r); }
        if (msg == WM_SETFOCUS && s->controller) s->controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
        if (msg == WM_PAINT) {
            PAINTSTRUCT p; HDC dc = BeginPaint(hwnd,&p); RECT r{}; GetClientRect(hwnd,&r);
            FillRect(dc,&r,GetSysColorBrush(COLOR_WINDOW));
            const wchar_t* text = FAILED(s->error) ? L"PhyXi embedded view failed. Reconcile previously dispatched work in the same session before sending again." : L"Loading PhyXi embedded workspace...";
            DrawTextW(dc,text,-1,&r,DT_CENTER|DT_VCENTER|DT_WORDBREAK); EndPaint(hwnd,&p); return 0;
        }
        if (msg == WM_NCDESTROY) {
            s->Close(); auto ptr = reinterpret_cast<Shared*>(GetWindowLongPtrW(hwnd,GWLP_USERDATA));
            SetWindowLongPtrW(hwnd,GWLP_USERDATA,0); delete ptr;
        }
    }
    return DefWindowProcW(hwnd,msg,w,l);
}
}
HRESULT __stdcall PhyXiHostAttach(HWND parent, const wchar_t* url, const wchar_t* profile, HWND* out) {
    try {
        if (!out) return E_POINTER; *out = nullptr;
        DWORD pid = 0; DWORD thread = GetWindowThreadProcessId(parent,&pid);
        if (!IsWindow(parent) || pid != GetCurrentProcessId() || thread != GetCurrentThreadId()) return E_ACCESSDENIED;
        if (!url || !profile || !*profile) return E_INVALIDARG;
        APTTYPE apt; APTTYPEQUALIFIER qualifier;
        auto getApartment = reinterpret_cast<HRESULT (WINAPI*)(APTTYPE*,APTTYPEQUALIFIER*)>(
            GetProcAddress(GetModuleHandleW(L"ole32.dll"),"CoGetApartmentType"));
        if (!getApartment || FAILED(getApartment(&apt,&qualifier)) || (apt != APTTYPE_STA && apt != APTTYPE_MAINSTA)) return RPC_E_WRONG_THREAD;
        auto s = std::make_shared<State>(); s->url = url; s->profile = profile;
        if (*url && !LocalUrl(s->url,s->origin)) return E_INVALIDARG;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,reinterpret_cast<LPCWSTR>(&PhyXiHostAttach),&module);
        WNDCLASSW cls{}; cls.lpfnWndProc = Proc; cls.hInstance = module; cls.lpszClassName = kClass; cls.hCursor = LoadCursor(nullptr,IDC_ARROW);
        if (!RegisterClassW(&cls) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return HRESULT_FROM_WIN32(GetLastError());
        HWND hwnd = CreateWindowExW(0,kClass,L"PhyXi embedded workspace",WS_CHILD|WS_VISIBLE|WS_CLIPCHILDREN|WS_CLIPSIBLINGS,0,0,1,1,parent,nullptr,module,&s);
        if (!hwnd) return HRESULT_FROM_WIN32(GetLastError());
        *out = hwnd; Resize(s); if (*url) Init(s); return S_OK;
    } catch (...) { return E_FAIL; }
}
HRESULT __stdcall PhyXiHostStart(HWND parent, const wchar_t* python, const wchar_t* root, const wchar_t* workspace, const wchar_t* profile, HWND* out) {
    try {
        if (!python || !root || !workspace || !*workspace || GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES ||
            GetFileAttributesW((std::wstring(root)+L"\\web_server.py").c_str()) == INVALID_FILE_ATTRIBUTES) return E_INVALIDARG;
        HRESULT hr = PhyXiHostAttach(parent,L"",profile,out);
        if (FAILED(hr)) return hr;
        auto s = Get(*out); StartBackend(s,python,root,workspace); return S_OK;
    } catch (...) { if (out && *out) PhyXiHostDetach(*out); return E_FAIL; }
}
HRESULT __stdcall PhyXiHostResize(HWND hwnd) { try { auto s = Get(hwnd); return s ? Resize(s) : E_HANDLE; } catch (...) { return E_FAIL; } }
HRESULT __stdcall PhyXiHostDetach(HWND hwnd) { auto s = Get(hwnd); if (!s) return E_HANDLE; return DestroyWindow(hwnd) ? S_OK : HRESULT_FROM_WIN32(GetLastError()); }
HRESULT __stdcall PhyXiHostStatus(HWND hwnd, wchar_t* json, unsigned cap) {
    auto s = Get(hwnd); if (!s) return E_HANDLE;
    if (!json || cap < 192) return E_INVALIDARG;
    swprintf(json,cap,L"{\"ready\":%ls,\"closed\":%ls,\"hresult\":%ld,\"parent_pid\":%lu,\"ui_thread\":%lu,\"is_child\":%ls}",
        s->ready?L"true":L"false",s->closed?L"true":L"false",static_cast<long>(s->error),GetCurrentProcessId(),GetCurrentThreadId(),
        (GetWindowLongPtrW(hwnd,GWL_STYLE)&WS_CHILD)?L"true":L"false");
    return S_OK;
}
BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) { return TRUE; }
