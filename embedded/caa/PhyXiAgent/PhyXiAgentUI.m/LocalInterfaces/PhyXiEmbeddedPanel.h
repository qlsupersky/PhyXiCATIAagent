#ifndef PhyXiEmbeddedPanel_h
#define PhyXiEmbeddedPanel_h
#include "CATDlgDialog.h"
#include <windows.h>
class PhyXiEmbeddedPanel : public CATDlgDialog {
public:
    explicit PhyXiEmbeddedPanel(CATDialog* parent);
    virtual ~PhyXiEmbeddedPanel();
    void Open();
    void OnSize(CATCommand*, CATNotification*, CATCommandClientData);
    void OnClose(CATCommand*, CATNotification*, CATCommandClientData);
private:
    HWND child_;
};
#endif
