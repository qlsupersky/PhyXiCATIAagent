using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

// CATIA automation runs in a dedicated STA process. No CATIA assemblies required.
partial class CatiaBridge {
    static JavaScriptSerializer json = new JavaScriptSerializer();
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        try {
            if(args.Length < 1) throw new ArgumentException("Expected info, export, import, or create-test.");
            dynamic app = Marshal.GetActiveObject("CATIA.Application");
            object result;
            switch(args[0]) {
                case "surface-build": result=SurfaceBuild(app,Path.GetFullPath(args[1]),Path.GetFullPath(args[2])); break;
                case "surface-revise": result=SurfaceRevise(app,Path.GetFullPath(args[1]),Path.GetFullPath(args[2])); break;
                case "info": result=Info(app); break;
                case "capture":
                    Fresh(Path.GetFullPath(args[1]));
                    dynamic window=app.ActiveWindow;
                    int layout=(int)window.Layout;
                    try {window.Layout=1;window.ActiveViewer.Reframe();window.ActiveViewer.CaptureToFile(5,Path.GetFullPath(args[1]));}
                    finally {window.Layout=layout;}
                    result=new {image=Path.GetFullPath(args[1]),format="JPEG",scope="current CATIA viewport; occlusion possible"}; break;
                case "documents": result=Documents(app); break;
                case "launch-macro":
                    app.SystemService.ExecuteScript(Path.GetFullPath(args[1]),1,"PhyXiCATIAAgent.CATScript","CATMain",new object[]{});
                    result=new {launched=true}; break;
                case "export": result=Export(app, Path.GetFullPath(args[1])); break;
                case "import": result=Import(app,Path.GetFullPath(args[1]),args.Length>2?Path.GetFullPath(args[2]):null); break;
                case "housing-boolean": result=HousingBoolean(app,Path.GetFullPath(args[1]),Path.GetFullPath(args[2]),args[3]); break;
                case "create-test": result=CreateTest(app,Path.GetFullPath(args[1])); break;
                default: throw new ArgumentException("Unknown command.");
            }
            Console.WriteLine(json.Serialize(new {ok=true,result=result})); return 0;
        } catch(Exception ex) {
            Console.WriteLine(json.Serialize(new {ok=false,error=ex.Message,hresult=ex.HResult})); return 1;
        }
    }
    static object Info(dynamic app) {
        dynamic doc=app.ActiveDocument;
        var data=new Dictionary<string,object>();
        data["application"]=Convert.ToString(app.Caption);
        data["document"]=Convert.ToString(doc.Name);
        try {data["path"]=Convert.ToString(doc.FullName);} catch {data["path"]="";}
        dynamic part;
        try {part=doc.Part;} catch {throw new InvalidOperationException("Activate a CATPart document first (assemblies are not supported).");}
        var bodies=new List<object>();
        for(int i=1;i<=(int)part.Bodies.Count;i++) {
            dynamic body=part.Bodies.Item(i); var features=new List<string>();
            for(int j=1;j<=(int)body.Shapes.Count;j++) features.Add(Convert.ToString(body.Shapes.Item(j).Name));
            bodies.Add(new {name=Convert.ToString(body.Name),features=features});
        }
        data["bodies"]=bodies;
        var hybridBodies=new List<object>();
        for(int i=1;i<=(int)part.HybridBodies.Count;i++) {
            dynamic body=part.HybridBodies.Item(i); var features=new List<string>();
            for(int j=1;j<=(int)body.HybridShapes.Count;j++) features.Add(Convert.ToString(body.HybridShapes.Item(j).Name));
            hybridBodies.Add(new {name=Convert.ToString(body.Name),features=features});
        }
        data["hybrid_bodies"]=hybridBodies;
        var parameters=new List<object>();
        for(int i=1;i<=(int)part.Parameters.Count && i<=300;i++) {
            dynamic p=part.Parameters.Item(i);
            try { parameters.Add(new {name=Convert.ToString(p.Name),value=Convert.ToString(p.ValueAsString())}); } catch {}
        }
        data["parameters"]=parameters;
        data["parameter_count"]=(int)part.Parameters.Count;
        data["parameters_truncated"]=(int)part.Parameters.Count>300;
        try {dynamic rf=part.CreateReferenceFromObject(part.MainBody); dynamic m=doc.GetWorkbench("SPAWorkbench").GetMeasurable(rf); data["volume_mm3"]=(double)m.Volume*1e9;} catch {}
        var selection=new List<string>(); dynamic sel=doc.Selection;
        for(int i=1;i<=(int)sel.Count2;i++) {try {selection.Add(Convert.ToString(sel.Item2(i).Value.Name));} catch {selection.Add("Topology");}}
        data["selection"]=selection; return data;
    }
    static void Fresh(string path) {
        if(File.Exists(path)) throw new IOException("Refusing to overwrite existing file: "+path);
        Directory.CreateDirectory(Path.GetDirectoryName(path));
    }
    static object Export(dynamic app,string path) {
        Fresh(path); dynamic doc=app.ActiveDocument;
        try {dynamic p=doc.Part;} catch {throw new InvalidOperationException("Activate a CATPart document first.");}
        object info=Info(app);
        doc.ExportData(path,"stp");
        if(!File.Exists(path)||new FileInfo(path).Length==0) throw new IOException("CATIA produced no STEP file.");
        return new {step=path,snapshot=info};
    }
    static object Import(dynamic app,string path,string save) {
        if(!File.Exists(path)) throw new FileNotFoundException("STEP file not found.",path);
        if(save!=null) Fresh(save);
        // CATIA's STEP translator returns a transient .step Document, whereas
        // the converted CATPart/CATProduct is exposed as ActiveDocument.
        dynamic opened=app.Documents.Open(path);
        dynamic doc=app.ActiveDocument;
        try {dynamic p=doc.Part;} catch {
            var leaves=new List<object>();
            try { FindParts(doc.Product, leaves); } catch {}
            if(leaves.Count!=1) throw new InvalidOperationException("STEP must contain exactly one CATPart; found "+leaves.Count+". Root document: "+Convert.ToString(doc.Name));
            doc=leaves[0];
        }
        try {dynamic p=doc.Part; p.Update();} catch(Exception ex) {throw new InvalidOperationException("CATPart update failed: "+ex.Message);}
        if(save!=null) doc.SaveAs(save);
        doc.Activate();
        try {app.ActiveWindow.ActiveViewer.Reframe();} catch {}
        return Info(app);
    }
    static void FindParts(dynamic product,List<object> leaves) {
        if((int)product.Products.Count==0) {
            dynamic doc=product.ReferenceProduct.Parent;
            try {dynamic p=doc.Part; leaves.Add((object)doc);} catch {}
            return;
        }
        for(int i=1;i<=(int)product.Products.Count;i++) FindParts(product.Products.Item(i),leaves);
    }
    static object Documents(dynamic app) {
        var list=new List<object>();
        for(int i=1;i<=(int)app.Documents.Count;i++) {
            dynamic doc=app.Documents.Item(i); string kind="other"; int count=0;
            try {dynamic p=doc.Part;kind="Part";} catch {try {dynamic p=doc.Product;kind="Product";count=(int)p.Products.Count;} catch {}}
            list.Add(new {name=Convert.ToString(doc.Name),kind=kind,children=count});
        }
        return list;
    }
    static object HousingBoolean(dynamic app,string toolPath,string save,string operation) {
        if(operation!="remove_existing" && operation!="add_groove") throw new ArgumentException("Invalid groove operation");
        dynamic original=app.ActiveDocument;
        string source=Convert.ToString(original.FullName);
        // SaveAs captures current in-memory geometry in a distinct file and
        // changes this document's path; the original disk file is untouched.
        Fresh(save);original.SaveAs(save);
        if(!String.Equals(Path.GetFullPath(Convert.ToString(original.FullName)),save,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("CATIA did not switch SaveAs to the requested distinct file; no boolean applied.");
        dynamic doc=original;doc.Activate();
        dynamic part=doc.Part;dynamic main=part.MainBody;
        dynamic beforeMeasure=doc.GetWorkbench("SPAWorkbench").GetMeasurable(part.CreateReferenceFromObject(main));
        double before=(double)beforeMeasure.Volume*1e9;
        Import(app,toolPath,null);dynamic toolDoc=app.ActiveDocument;dynamic toolBody=toolDoc.Part.MainBody;
        dynamic selection=toolDoc.Selection;selection.Clear();selection.Add(toolBody);selection.Copy();
        doc.Activate();int count=(int)part.Bodies.Count;selection=doc.Selection;selection.Clear();selection.Add(part);selection.PasteSpecial("CATPrtResultWithOutLink");selection.Clear();
        if((int)part.Bodies.Count!=count+1) throw new InvalidOperationException("Groove tool copy did not create exactly one Body");
        dynamic operand=part.Bodies.Item(count+1);operand.Name="PhyXi_Groove_Tool";part.InWorkObject=main;
        dynamic feature;
        if(operation=="remove_existing") feature=part.ShapeFactory.AddNewAdd(operand);
        else feature=part.ShapeFactory.AddNewRemove(operand);
        feature.Name=operation=="remove_existing" ? "PhyXi_Fill_Whole_Groove" : "PhyXi_Cut_Whole_Groove";
        part.Update();doc.Save();doc.Activate();
        try {app.ActiveWindow.ActiveViewer.Reframe();} catch {}
        return new {source=source,before_volume_mm3=before,snapshot=Info(app),implementation="CATIA native Boolean Add/Remove on copied original body; imported groove operand only"};
    }
    static object CreateTest(dynamic app,string path) {
        Fresh(path); dynamic doc=app.Documents.Add("Part"); dynamic part=doc.Part;
        dynamic sk=part.MainBody.Sketches.Add(part.OriginElements.PlaneXY);
        sk.SetAbsoluteAxisData(new object[]{0d,0d,0d,1d,0d,0d,0d,1d,0d});
        dynamic f=sk.OpenEdition();
        f.CreateLine(-60d,-45d,60d,-45d); f.CreateLine(60d,-45d,60d,45d);
        f.CreateLine(60d,45d,-60d,45d); f.CreateLine(-60d,45d,-60d,-45d);
        sk.CloseEdition(); part.InWorkObject=sk;
        dynamic pad=part.ShapeFactory.AddNewPad(sk,20d); part.Update();
        doc.SaveAs(path); return Info(app);
    }
}
