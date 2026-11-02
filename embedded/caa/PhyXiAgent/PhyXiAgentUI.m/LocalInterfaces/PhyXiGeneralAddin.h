#ifndef PhyXiGeneralAddin_h
#define PhyXiGeneralAddin_h
#include "CATBaseUnknown.h"
class CATCmdContainer;
// Experimental general-workshop entry; requires an authorized matching CAA SDK.
class PhyXiGeneralAddin : public CATBaseUnknown {
    CATDeclareClass;
public:
    PhyXiGeneralAddin();
    virtual ~PhyXiGeneralAddin();
    void CreateCommands();
    CATCmdContainer* CreateToolbars();
};
#endif
