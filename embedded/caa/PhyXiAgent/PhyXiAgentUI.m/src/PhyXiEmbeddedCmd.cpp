#include "PhyXiEmbeddedCmd.h"
#include "PhyXiEmbeddedPanel.h"
#include "CATApplicationFrame.h"
#include "CATDlgWindow.h"
#include "CATCreateExternalObject.h"

CATImplementClass(PhyXiEmbeddedCmd, Implementation, CATStateCommand, CATNull);
CATCreateClass(PhyXiEmbeddedCmd);

namespace { PhyXiEmbeddedPanel* panel = NULL; }
PhyXiEmbeddedCmd::PhyXiEmbeddedCmd()
    : CATStateCommand("PhyXiEmbeddedCmd", CATDlgEngOneShot, CATCommandModeShared) {
    // The panel belongs to the native frame, not to this transient command.
    CATApplicationFrame* frame = CATApplicationFrame::GetFrame();
    if (frame && !panel) panel = new PhyXiEmbeddedPanel(frame->GetMainWindow());
    if (panel) panel->Open();
}
PhyXiEmbeddedCmd::~PhyXiEmbeddedCmd() {}
void PhyXiEmbeddedCmd::BuildGraph() { RequestDelayedDestruction(); }
