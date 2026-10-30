using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;

partial class CatiaBridge {
    static dynamic StylePoint(dynamic part,dynamic group,Dictionary<string,object> item,string name) {
        var xyz=(IList)item["xyz"]; var expr=(IList)item["formulas"];
        dynamic pt=SurfaceAdd(part,group,part.HybridShapeFactory.AddNewPointCoord(Convert.ToDouble(xyz[0]),Convert.ToDouble(xyz[1]),Convert.ToDouble(xyz[2])),name);
        Formula(part,name+"_X",pt.X,Convert.ToString(expr[0]));
        Formula(part,name+"_Y",pt.Y,Convert.ToString(expr[1]));
        Formula(part,name+"_Z",pt.Z,Convert.ToString(expr[2]));
        return pt;
    }
    static dynamic StyleSpline(dynamic part,dynamic group,IEnumerable points,string name,bool closed) {
        dynamic spline=part.HybridShapeFactory.AddNewSpline();spline.SetSplineType(0);spline.SetClosing(closed?1:0);int i=0;
        foreach(object raw in points) {dynamic pt=StylePoint(part,group,(Dictionary<string,object>)raw,name+"_P"+i++);spline.AddPoint(SurfaceRef(part,pt));}
        return SurfaceAdd(part,group,spline,name);
    }
    static dynamic StyleOutline(dynamic part,dynamic group,Dictionary<string,object> req) {
        if(Convert.ToString(req["outline_kind"])=="closed_spline") return StyleSpline(part,group,(IEnumerable)req["outline"],"Outline",true);
        var points=new List<object>();int i=0;
        foreach(object raw in (IEnumerable)req["outline"]) points.Add((object)StylePoint(part,group,(Dictionary<string,object>)raw,"Outline_P"+i++));
        var lines=new List<object>();
        for(i=0;i<points.Count-1;i++) lines.Add((object)SurfaceAdd(part,group,part.HybridShapeFactory.AddNewLinePtPt(SurfaceRef(part,points[i]),SurfaceRef(part,points[i+1])),"Outline_E"+i));
        dynamic wire=part.HybridShapeFactory.AddNewJoin(SurfaceRef(part,lines[0]),SurfaceRef(part,lines[1]));
        for(i=2;i<lines.Count;i++)wire.AddElement(SurfaceRef(part,lines[i]));
        dynamic arch=StyleSpline(part,group,(IEnumerable)req["arch"],"WheelArch",false);
        wire.AddElement(SurfaceRef(part,arch));wire.SetConnex(true);wire.SetManifold(true);wire.SetDeviation(.001d);
        return SurfaceAdd(part,group,wire,"Outline");
    }
    static object StyleSurfaceBuild(dynamic app,Dictionary<string,object> req,string output) {
        Directory.CreateDirectory(output);Fresh(Path.Combine(output,"model.CATPart"));
        string template=Convert.ToString(req["template"]);bool fender=template=="fender_reference";
        dynamic doc=app.Documents.Add("Part");dynamic part=doc.Part;dynamic factory=part.HybridShapeFactory;
        var values=(Dictionary<string,object>)req["parameters"];
        foreach(var pair in values) {dynamic dim=part.Parameters.CreateDimension(pair.Key,"LENGTH",0d);dim.ValuateFromString(Convert.ToString(pair.Value,System.Globalization.CultureInfo.InvariantCulture)+"mm");}
        dynamic construction=part.HybridBodies.Add();construction.Name="V2_Construction";
        dynamic body=part.HybridBodies.Add();body.Name="V2_SurfaceDemo";
        dynamic loft=factory.AddNewLoft();int section=0;
        foreach(object profile in (IEnumerable)req["profiles"]) {
            dynamic spline=StyleSpline(part,construction,(IEnumerable)profile,"Section_"+section++,false);
            loft.AddSectionToLoft(SurfaceRef(part,spline),1,new System.Runtime.InteropServices.DispatchWrapper(null));
        }
        SurfaceAdd(part,body,loft,"Loft");
        dynamic outline=StyleOutline(part,construction,req);
        var axis=(IList)req["cut_axis"];
        dynamic direction=factory.AddNewDirectionByCoord(Convert.ToDouble(axis[0]),Convert.ToDouble(axis[1]),Convert.ToDouble(axis[2]));
        dynamic cutter=SurfaceAdd(part,construction,factory.AddNewExtrude(SurfaceRef(part,outline),500d,500d,direction),"Outline_Cutter");
        dynamic trimmed=SurfaceAdd(part,body,factory.AddNewHybridSplit(SurfaceRef(part,loft),SurfaceRef(part,cutter),-1),"OutlineTrim");
        dynamic skin=trimmed;
        if(fender) {
            dynamic marker=StyleSpline(part,construction,(IEnumerable)req["marker"],"MarkerEllipse",true);
            dynamic markerCutter=SurfaceAdd(part,construction,factory.AddNewExtrude(SurfaceRef(part,marker),500d,500d,direction),"Marker_Cutter");
            skin=SurfaceAdd(part,body,factory.AddNewHybridSplit(SurfaceRef(part,trimmed),SurfaceRef(part,markerCutter),-1),"Trimmed");
        } else {
            // A native split retains the outer panel footprint; it is not a
            // fictitious physical bead. Final skin is exported separately.
            skin.Name="Trimmed";
        }
        dynamic plane=SurfaceAdd(part,construction,factory.AddNewPlaneEquation(1d,0d,0d,0d),"SeamPlane");
        dynamic left=SurfaceAdd(part,body,factory.AddNewHybridSplit(SurfaceRef(part,skin),SurfaceRef(part,plane),1),"Left");
        dynamic right=SurfaceAdd(part,body,factory.AddNewHybridSplit(SurfaceRef(part,skin),SurfaceRef(part,plane),-1),"Right");
        dynamic join=factory.AddNewJoin(SurfaceRef(part,left),SurfaceRef(part,right));join.SetConnex(true);join.SetManifold(true);join.SetDeviation(.001d);join.SetSimplify(false);
        SurfaceAdd(part,body,join,"Joined");
        dynamic offset=SurfaceAdd(part,body,factory.AddNewOffset(SurfaceRef(part,join),Convert.ToDouble(values["OffsetDistance"]),false,.001d),"Offset");
        Formula(part,"Offset_distance",offset.OffsetValue,"OffsetDistance");
        dynamic boundary=SurfaceAdd(part,construction,factory.AddNewBoundaryOfSurface(SurfaceRef(part,skin)),"PanelBoundary");
        dynamic flangeDirection=factory.AddNewDirectionByCoord(0d,fender?-1d:0d,fender?0d:-1d);
        dynamic flange=SurfaceAdd(part,body,factory.AddNewExtrude(SurfaceRef(part,boundary),0d,Convert.ToDouble(values["FlangeDepth"]),flangeDirection),"ReturnFlange");
        Formula(part,"Flange_depth",flange.EndOffset,"FlangeDepth");
        dynamic final=factory.AddNewJoin(SurfaceRef(part,join),SurfaceRef(part,flange));final.SetConnex(true);final.SetManifold(true);final.SetDeviation(.001d);final.SetSimplify(false);
        SurfaceAdd(part,body,final,"FinalPanel");part.Update();
        return SurfaceSave(app,doc,output);
    }
}
