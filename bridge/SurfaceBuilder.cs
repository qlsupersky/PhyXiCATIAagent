using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Globalization;

partial class CatiaBridge {
    static readonly string[] SurfaceStages={"Loft","Trimmed","Left","Right","Joined","Offset"};
    static dynamic SurfaceAdd(dynamic part,dynamic body,dynamic shape,string name) {
        body.AppendHybridShape(shape); shape.Name=name;
        try { part.UpdateObject(shape); } catch(Exception ex) { throw new InvalidOperationException("Surface stage "+name+": "+ex.Message); }
        return shape;
    }
    static dynamic SurfaceRef(dynamic part,dynamic shape) { return part.CreateReferenceFromObject(shape); }
    static void Formula(dynamic part,string name,dynamic target,string expression) { part.Relations.CreateFormula(name,"",target,expression); }
    static object SurfaceBuild(dynamic app,string requestPath,string output) {
        var req=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(requestPath));
        string template=Convert.ToString(req["template"]);
        if(template=="roof_reference" || template=="fender_reference") return StyleSurfaceBuild(app,req,output);
        if(template!="roof" && template!="fender") throw new ArgumentException("Unknown demonstration surface.");
        Directory.CreateDirectory(output);
        Fresh(Path.Combine(output,"model.CATPart"));
        dynamic doc=app.Documents.Add("Part"); dynamic part=doc.Part; dynamic factory=part.HybridShapeFactory;
        var parameters=(Dictionary<string,object>)req["parameters"];
        foreach(var pair in parameters) {
            dynamic parameter=part.Parameters.CreateDimension(pair.Key,"LENGTH",0d);
            parameter.ValuateFromString(Convert.ToDouble(pair.Value).ToString("R",CultureInfo.InvariantCulture)+"mm");
        }
        dynamic construction=part.HybridBodies.Add(); construction.Name="V2_Construction";
        dynamic surfaces=part.HybridBodies.Add(); surfaces.Name="V2_SurfaceDemo";
        var sections=new List<object>(); int i=0;
        foreach(object rawProfile in (IEnumerable)req["profiles"]) {
            dynamic spline=factory.AddNewSpline(); spline.SetSplineType(0); spline.SetClosing(0); int j=0;
            foreach(object rawPoint in (IEnumerable)rawProfile) {
                var item=(Dictionary<string,object>)rawPoint;
                var xyz=(IList)item["xyz"]; var expr=(IList)item["formulas"];
                dynamic pt=SurfaceAdd(part,construction,factory.AddNewPointCoord(Convert.ToDouble(xyz[0]),Convert.ToDouble(xyz[1]),Convert.ToDouble(xyz[2])),"Point_"+i+"_"+j);
                Formula(part,"Fx_"+i+"_"+j,pt.X,Convert.ToString(expr[0]));
                Formula(part,"Fy_"+i+"_"+j,pt.Y,Convert.ToString(expr[1]));
                Formula(part,"Fz_"+i+"_"+j,pt.Z,Convert.ToString(expr[2]));
                spline.AddPoint(SurfaceRef(part,pt)); j++;
            }
            SurfaceAdd(part,construction,spline,"Section_"+i); sections.Add((object)spline); i++;
        }
        dynamic loft=factory.AddNewLoft();
        if(template=="fender") {
            // Radial section planes rotate around the arch. Explicit inner,
            // middle and outer guides preserve their intended correspondence.
            foreach(int index in new int[]{0,4,8}) {
                dynamic guide=factory.AddNewSpline(); guide.SetSplineType(0); guide.SetClosing(0);
                for(int rank=0;rank<5;rank++) guide.AddPoint(SurfaceRef(part,construction.HybridShapes.Item("Point_"+rank+"_"+index)));
                SurfaceAdd(part,construction,guide,"Guide_"+index);
                loft.AddGuide(SurfaceRef(part,guide));
            }
        }
        foreach(dynamic section in sections) loft.AddSectionToLoft(SurfaceRef(part,section),1,new System.Runtime.InteropServices.DispatchWrapper(null));
        SurfaceAdd(part,surfaces,loft,"Loft");
        dynamic trimPlane;
        if(template=="roof") {
            trimPlane=SurfaceAdd(part,construction,factory.AddNewPlaneOffset(part.OriginElements.PlaneYZ,0d,false),"TrimPlane");
            Formula(part,"Trim_position",trimPlane.Offset,"0.5 * RoofLength - TrimMargin");
        } else {
            trimPlane=SurfaceAdd(part,construction,factory.AddNewPlaneOffset(part.OriginElements.PlaneXY,0d,false),"TrimPlane");
            Formula(part,"Trim_position",trimPlane.Offset,"TrimHeight");
        }
        part.Update();
        dynamic trimmed=SurfaceAdd(part,surfaces,factory.AddNewHybridSplit(SurfaceRef(part,loft),SurfaceRef(part,trimPlane),template=="roof"?-1:1),"Trimmed");
        dynamic centerPlane=SurfaceAdd(part,construction,factory.AddNewPlaneEquation(1d,0d,0d,0d),"SeamPlane");
        dynamic left=SurfaceAdd(part,surfaces,factory.AddNewHybridSplit(SurfaceRef(part,trimmed),SurfaceRef(part,centerPlane),1),"Left");
        dynamic right=SurfaceAdd(part,surfaces,factory.AddNewHybridSplit(SurfaceRef(part,trimmed),SurfaceRef(part,centerPlane),-1),"Right");
        dynamic join=factory.AddNewJoin(SurfaceRef(part,left),SurfaceRef(part,right));
        join.SetConnex(true); join.SetManifold(true); join.SetDeviation(.001d); join.SetSimplify(false);
        SurfaceAdd(part,surfaces,join,"Joined");
        dynamic offset=factory.AddNewOffset(SurfaceRef(part,join),Convert.ToDouble(parameters["OffsetDistance"]),false,.001d);
        SurfaceAdd(part,surfaces,offset,"Offset");
        Formula(part,"Offset_distance",offset.OffsetValue,"OffsetDistance");
        part.Update();
        return SurfaceSave(app,doc,output);
    }
    static object SurfaceRevise(dynamic app,string requestPath,string output) {
        var req=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(requestPath));
        string previous=Convert.ToString(req["catpart"]); string target=Path.Combine(output,"model.CATPart");
        Fresh(target);
        // File.Copy + Open collides with the CATIA internal document ID when
        // the source is already open. SaveAs moves the session document to a
        // new path while preserving the previous file on disk.
        dynamic doc=null;
        for(int n=1;n<=app.Documents.Count;n++) {
            dynamic candidate=app.Documents.Item(n);
            try { if(String.Equals(Convert.ToString(candidate.FullName),previous,StringComparison.OrdinalIgnoreCase)) {doc=candidate;break;} } catch {}
        }
        if(doc==null) {
            // Historical revisions share CATIA's internal document ID. Close
            // only saved, managed siblings before opening an older revision;
            // otherwise CATIA displays a duplicate-ID modal dialog.
            var related=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            object raw;
            if(req.TryGetValue("related_catparts",out raw)) foreach(object path in (IEnumerable)raw) related.Add(Path.GetFullPath(Convert.ToString(path)));
            var siblings=new List<object>();
            for(int n=1;n<=app.Documents.Count;n++) {
                dynamic candidate=app.Documents.Item(n);string path;
                try {path=Path.GetFullPath(Convert.ToString(candidate.FullName));} catch {continue;}
                if(!related.Contains(path)) continue;
                if(!Convert.ToBoolean(candidate.Saved)) throw new InvalidOperationException("A related CATPart has unsaved edits. Save or discard them in CATIA before switching historical revision: "+path);
                siblings.Add((object)candidate);
            }
            foreach(dynamic sibling in siblings) sibling.Close();
            doc=app.Documents.Open(previous);
        }
        if(!Convert.ToBoolean(doc.Saved)) throw new InvalidOperationException("Previous CATPart has unsaved edits. Save or discard them in CATIA before creating a revision.");
        doc.SaveAs(target); dynamic part=doc.Part;
        foreach(var pair in (Dictionary<string,object>)req["parameters"]) {
            part.Parameters.Item(pair.Key).ValuateFromString(Convert.ToDouble(pair.Value).ToString("R",CultureInfo.InvariantCulture)+"mm");
        }
        part.Update();
        return SurfaceSave(app,doc,output);
    }
    static void SurfaceHide(dynamic doc,dynamic item,bool hide) {
        dynamic sel=doc.Selection; sel.Clear(); sel.Add(item); sel.VisProperties.SetShow(hide?1:0); sel.Clear();
    }
    static object SurfaceSave(dynamic app,dynamic doc,string output) {
        dynamic part=doc.Part; dynamic body=part.HybridBodies.Item("V2_SurfaceDemo");
        SurfaceHide(doc,part.HybridBodies.Item("V2_Construction"),true);
        var records=new List<object>();
        var stages=new List<string>(SurfaceStages);
        string visible="Joined";
        try {dynamic final=body.HybridShapes.Item("FinalPanel");stages.Add("ReturnFlange");stages.Add("FinalPanel");visible="FinalPanel";} catch {}
        try {dynamic outer=body.HybridShapes.Item("OutlineTrim");stages.Add("OutlineTrim");} catch {}
        foreach(string name in stages) {
            dynamic shape=body.HybridShapes.Item(name);
            double area=Convert.ToDouble(doc.GetWorkbench("SPAWorkbench").GetMeasurable(SurfaceRef(part,shape)).Area)*1e6;
            if(Double.IsNaN(area)||Double.IsInfinity(area)||area<=0) throw new InvalidOperationException("Invalid area: "+name);
            string path=Path.Combine(output,name+".step"); Fresh(path);
            // PasteSpecial carries visibility from the source. Revisions have
            // intermediate stages hidden, which otherwise export empty STEP.
            SurfaceHide(doc,shape,false);
            dynamic selection=doc.Selection; selection.Clear(); selection.Add(shape); selection.Copy();
            dynamic isolated=app.Documents.Add("Part");
            try {
                dynamic sel=isolated.Selection; sel.Clear(); sel.Add(isolated.Part); sel.PasteSpecial("CATPrtResultWithOutLink");
                isolated.Part.Update();
                // Result surfaces pasted into the main body can retain their
                // old no-show attribute independently of the source display.
                for(int b=1;b<=isolated.Part.Bodies.Count;b++) {
                    dynamic pastedBody=isolated.Part.Bodies.Item(b);
                    SurfaceHide(isolated,pastedBody,false);
                    for(int h=1;h<=pastedBody.HybridShapes.Count;h++) SurfaceHide(isolated,pastedBody.HybridShapes.Item(h),false);
                    for(int h=1;h<=pastedBody.Shapes.Count;h++) SurfaceHide(isolated,pastedBody.Shapes.Item(h),false);
                }
                isolated.ExportData(path,"stp");
                if(!File.Exists(path)||new FileInfo(path).Length==0) throw new IOException("Surface STEP export failed.");
            } finally { isolated.Close(); doc.Activate(); }
            records.Add(new {name=name,area_mm2=area,step=path});
            SurfaceHide(doc,shape,name!=visible);
        }
        part.InWorkObject=body.HybridShapes.Item(visible);
        part.Update(); string target=Path.Combine(output,"model.CATPart");
        if(File.Exists(target)) doc.Save(); else doc.SaveAs(target);
        doc.Activate(); try {app.ActiveWindow.ActiveViewer.Reframe();} catch {}
        return new {catpart=target,stages=records,native_history=true,native_parameter_formulas=true,class_a_accepted=false};
    }
}
