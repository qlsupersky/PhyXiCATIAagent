#include "PhyXiGeneralAddin.h"
#include "CATCommandHeader.h"
#include "CATCreateWorkshop.h"
#include "CATCmdContainer.h"
#include "CATCmdStarter.h"
#include "TIE_CATIAfrGeneralWksAddin.h"

CATImplementClass(PhyXiGeneralAddin, Implementation, CATBaseUnknown, CATNull);
TIE_CATIAfrGeneralWksAddin(PhyXiGeneralAddin);
MacDeclareHeader(PhyXiCommandHeader);

PhyXiGeneralAddin::PhyXiGeneralAddin() {}
PhyXiGeneralAddin::~PhyXiGeneralAddin() {}
void PhyXiGeneralAddin::CreateCommands() {
    new PhyXiCommandHeader("PhyXiOpen", "PhyXiAgentUI", "PhyXiEmbeddedCmd", NULL);
}
CATCmdContainer* PhyXiGeneralAddin::CreateToolbars() {
    NewAccess(CATCmdContainer, toolbar, PhyXiAgentToolbar);
    NewAccess(CATCmdStarter, open, PhyXiAgentOpen);
    SetAccessCommand(open, "PhyXiOpen");
    SetAccessChild(toolbar, open);
    AddToolbarView(toolbar, 1, Right);
    return toolbar;
}
