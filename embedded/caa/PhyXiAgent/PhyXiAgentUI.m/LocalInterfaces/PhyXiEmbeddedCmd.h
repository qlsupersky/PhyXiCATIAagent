#ifndef PhyXiEmbeddedCmd_h
#define PhyXiEmbeddedCmd_h
#include "CATStateCommand.h"
class PhyXiEmbeddedCmd : public CATStateCommand {
    CATDeclareClass;
public:
    PhyXiEmbeddedCmd();
    virtual ~PhyXiEmbeddedCmd();
    void BuildGraph();
};
#endif
