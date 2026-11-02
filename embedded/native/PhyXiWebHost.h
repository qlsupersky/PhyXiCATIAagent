#pragma once
#include <windows.h>
#ifdef PHYXI_HOST_BUILD
#define PHYXI_API extern "C" __declspec(dllexport)
#else
#define PHYXI_API extern "C" __declspec(dllimport)
#endif
// These calls MUST run on the owning UI STA in the SAME process as parent.
// No remote SetParent, injection, macro, shell or top-level UI is used.
PHYXI_API HRESULT __stdcall PhyXiHostAttach(HWND parent, const wchar_t* url,
    const wchar_t* userDataDirectory, HWND* child);
// Starts only the headless local backend. URL/token travel over private pipes.
PHYXI_API HRESULT __stdcall PhyXiHostStart(HWND parent, const wchar_t* python,
    const wchar_t* appDirectory, const wchar_t* workspace,
    const wchar_t* userDataDirectory, HWND* child);
PHYXI_API HRESULT __stdcall PhyXiHostResize(HWND child);
PHYXI_API HRESULT __stdcall PhyXiHostDetach(HWND child);
PHYXI_API HRESULT __stdcall PhyXiHostStatus(HWND child, wchar_t* json, unsigned capacity);
