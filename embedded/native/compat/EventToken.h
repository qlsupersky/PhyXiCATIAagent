#pragma once
// Windows Runtime ABI value type (used only for MinGW builds of WebView2).
// MSVC builds should use the Windows SDK's EventToken.h instead.
typedef struct EventRegistrationToken { __int64 value; } EventRegistrationToken;
