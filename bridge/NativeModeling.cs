// Generic verification bridge. Geometry comes exclusively from the bound model macro.
using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Collections.Generic;
using System.Web.Script.Serialization;
internal static class NativeModeling
{
    const string Root=@"__ROOT__";
    const string MacroSha="__MACRO_SHA__";
    const string CheckSha="__CHECK_SHA__";
    const string RunId="__RUN_ID__";
    static readonly List<object> Refs=new List<object>();
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer();
    static Dictionary<string,object> Checks;
    static bool ComReturned=false;
    static bool ScriptErrorReturned=false;
    static bool IsScriptEngineFailure(COMException error)
    {
        string message=error.Message??"";
        // A CATIA response containing a bound VBScript engine diagnostic is
        // different from RPC disconnects/timeouts, whose CAD outcome is unknown.
        return message.IndexOf("REVIEWED.CATScript",StringComparison.OrdinalIgnoreCase)>=0 &&
               message.IndexOf("CATMain",StringComparison.OrdinalIgnoreCase)>=0 &&
               message.IndexOf("Microsoft VBScript",StringComparison.OrdinalIgnoreCase)>=0;
    }
    static object Keep(object x){Refs.Add(x);return x;}
    static void Emit(string name,object detail){Console.WriteLine(Json.Serialize(new{at=DateTime.UtcNow.ToString("o"),name=name,detail=detail}));Console.Out.Flush();}
    static void Before(string call){Emit("before_call",new{call=call});}
    static string Hash(string p){using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(File.ReadAllBytes(p))).Replace("-","").ToLowerInvariant();}
    static bool Same(string a,string b){return String.Equals(Path.GetFullPath(a),Path.GetFullPath(b),StringComparison.OrdinalIgnoreCase);}
    static object Read(dynamic doc)
    {
        dynamic part=Keep(doc.Part);dynamic body=Keep(part.MainBody);
        System.Collections.IList expected=(System.Collections.IList)Checks["features"];
        var features=new List<object>();
        bool passed=(int)body.Shapes.Count==expected.Count && (int)body.Sketches.Count==Convert.ToInt32(Checks["sketch_count"]) && (int)part.Bodies.Count==1 && (int)part.HybridBodies.Count==0;
        for(int i=1;i<=(int)body.Shapes.Count;i++)
        {
            dynamic feature=Keep(body.Shapes.Item(i));string name=(string)feature.Name;
            var actual=new Dictionary<string,object>();actual["name"]=name;
            if(i>expected.Count){passed=false;features.Add(actual);continue;}
            var e=(Dictionary<string,object>)expected[i-1];passed=passed&&name==(string)e["name"];
            if(e.ContainsKey("depth_mm")){double depth=(double)feature.FirstLimit.Dimension.Value;actual["depth_mm"]=depth;passed=passed&&Math.Abs(depth-Convert.ToDouble(e["depth_mm"]))<1e-6;}
            if(e.ContainsKey("symmetric")){bool sym=(bool)feature.IsSymmetric;actual["symmetric"]=sym;passed=passed&&sym==Convert.ToBoolean(e["symmetric"]);}
            features.Add(actual);
        }
        dynamic wb=Keep(doc.GetWorkbench("SPAWorkbench"));dynamic measure=Keep(wb.GetMeasurable(part.CreateReferenceFromObject(body)));
        double volume=(double)measure.Volume*1e9;bool updated=(bool)part.IsUpToDate(body);
        bool volumeChecked=Checks["volume_mm3"]!=null;
        double expectedVolume=volumeChecked?Convert.ToDouble(Checks["volume_mm3"]):0;
        bool volumeMatch=!volumeChecked||Math.Abs(volume-expectedVolume)<=Math.Max(0.001,expectedVolume*1e-7);
        passed=passed&&updated&&volume>0&&volumeMatch;
        return new{passed=passed,features=features,sketch_count=(int)body.Sketches.Count,body_count=(int)part.Bodies.Count,
            volume_mm3=volume,expected_volume_mm3=Checks["volume_mm3"],volume_checked=volumeChecked,volume_match=volumeMatch,up_to_date=updated,saved=(bool)doc.Saved,
            limitations="Checks are model-proposed and automatically bound, independent COM readback; not complete requirement equivalence, topology or Class-A proof"};
    }
    static bool Passed(object x){return (bool)x.GetType().GetProperty("passed").GetValue(x,null);}
    [STAThread]
    static int Main(string[] args)
    {
        Console.OutputEncoding=new UTF8Encoding(false);
        string outcome="UNKNOWN";
        try
        {
            if(args.Length!=0||Root.Contains("__"))throw new ArgumentException("Locally bound bridge required");
            string macro=Path.Combine(Root,"REVIEWED.CATScript"),checks=Path.Combine(Root,"CHECKS.json"),output=Path.Combine(Root,"RESULT.CATPart"),image=Path.Combine(Root,"RESULT.jpg"),unused=Path.Combine(Root,"unused.txt");
            if(Hash(macro)!=MacroSha||Hash(checks)!=CheckSha)throw new InvalidDataException("Bound files changed before COM");
            Checks=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(checks,Encoding.UTF8));
            foreach(byte b in File.ReadAllBytes(macro))if(b>127)throw new InvalidDataException("Not ASCII");
            foreach(string p in new[]{output,image,unused})if(File.Exists(p))throw new IOException("Output exists; refuse replay");
            Before("Marshal.GetActiveObject");dynamic app=Keep(Marshal.GetActiveObject("CATIA.Application"));
            dynamic docs=Keep(app.Documents);int count=(int)docs.Count;var old=new List<dynamic>();var states=new List<string>();
            for(int i=1;i<=count;i++){dynamic doc=Keep(docs.Item(i));old.Add(doc);states.Add((string)doc.FullName+"|"+((bool)doc.Saved).ToString());}
            Emit("baseline_inventory",new{count=count,paths_and_saved=states,apartment=Thread.CurrentThread.GetApartmentState().ToString(),bitness=IntPtr.Size*8});
            dynamic service=Keep(app.SystemService);
            Emit("dispatch_attempted",new{run_id=RunId,macro_sha256=MacroSha,origin="user_authorized_automatic_execution",output=output});
            Before("SystemService.ExecuteScript");object result;
            try{result=service.ExecuteScript(Root,1,"REVIEWED.CATScript","CATMain",new object[]{RunId,output,unused});}
            catch(COMException error)
            {
                if(IsScriptEngineFailure(error))
                {
                    ComReturned=true;ScriptErrorReturned=true;
                    Emit("com_return_observed",new{returned_error=true,kind="CATIA_VBScript_engine_error",hresult=error.ErrorCode});
                    Emit("macro_runtime_failed",new{run_id=RunId,macro_sha256=MacroSha,checks_sha256=CheckSha,
                        known_script_engine_return=true,message=error.Message,hresult=error.ErrorCode,
                        partial_document_may_exist=true});
                }
                throw;
            }
            ComReturned=true;
            Emit("com_return_observed",new{value=result});
            if((int)docs.Count!=count+1)throw new InvalidDataException("Unexpected documents count");
            dynamic own=Keep(app.ActiveDocument);
            if((string)own.Part.MainBody.Name!="Own_"+RunId)throw new InvalidDataException("New owned document identity failed");
            object first=Read(own);Emit("independent_readback",first);
            for(int i=0;i<count;i++)if((string)old[i].FullName+"|"+((bool)old[i].Saved).ToString()!=states[i])throw new InvalidDataException("Existing document metadata changed");
            if(!Passed(first))
            {
                string candidate=Path.Combine(Root,"FAILED-CANDIDATE.CATPart"),diagnostic=Path.Combine(Root,"FAILED-CANDIDATE.jpg");
                if(File.Exists(candidate)||File.Exists(diagnostic))throw new IOException("Diagnostic output exists; refuse overwrite");
                Before("Document.SaveAs.own_failed_candidate");own.SaveAs(candidate);
                if(!Same((string)own.FullName,candidate)||!(bool)own.Saved||!File.Exists(candidate))throw new InvalidDataException("Candidate save failed");
                dynamic failedViewer=Keep(app.ActiveWindow.ActiveViewer);failedViewer.Reframe();failedViewer.Update();failedViewer.CaptureToFile(5,diagnostic);
                for(int i=0;i<count;i++)if((string)old[i].FullName+"|"+((bool)old[i].Saved).ToString()!=states[i])throw new InvalidDataException("Existing metadata changed while saving candidate");
                Emit("validation_failed",new{passed=false,candidate=candidate,image=diagnostic,candidate_sha256=Hash(candidate),image_sha256=Hash(diagnostic),reason="independent_readback_mismatch",readback=first,original_metadata_unchanged=true});
                outcome="FAILED";
                return 3;
            }
            Before("Document.SaveAs.own_new");own.SaveAs(output);
            if(!Same((string)own.FullName,output)||!(bool)own.Saved||!File.Exists(output))throw new InvalidDataException("Own save failed");
            Emit("save_returned",new{output=output,sha256=Hash(output)});
            Before("Document.Close.own_saved");own.Close();
            Before("Documents.Open.own_saved");dynamic reopened=Keep(docs.Open(output));
            if(!Same((string)reopened.FullName,output)||!(bool)reopened.Saved)throw new InvalidDataException("Reopened identity failed");
            object after=Read(reopened);Emit("reopened_readback",after);if(!Passed(after))throw new InvalidDataException("Reopened readback rejected");
            Before("Document.Activate.own_reopened");reopened.Activate();
            if(!Same((string)app.ActiveDocument.FullName,output))throw new InvalidDataException("Wrong active document");
            dynamic viewer=Keep(app.ActiveWindow.ActiveViewer);viewer.Reframe();viewer.Update();
            Before("Viewer.CaptureToFile.own_result");viewer.CaptureToFile(5,image);
            if(!File.Exists(image)||new FileInfo(image).Length==0||Hash(macro)!=MacroSha||Hash(checks)!=CheckSha)throw new InvalidDataException("Capture/source validation failed");
            for(int i=0;i<count;i++)if((string)old[i].FullName+"|"+((bool)old[i].Saved).ToString()!=states[i])throw new InvalidDataException("Pre-existing metadata changed after reopen");
            Emit("experiment_validated",new{passed=true,macro_sha256=MacroSha,checks_sha256=CheckSha,model=output,model_sha256=Hash(output),image=image,image_sha256=Hash(image),original_document_count=count,
                limitations="Automatically executed program; metadata-only protection of old docs; no GUI/global lock or executable sandbox."});
            outcome="SUCCEEDED";return 0;
        }
        catch(Exception error){outcome=ComReturned?"FAILED":"UNKNOWN";Emit("probe_error",new{type=error.GetType().FullName,message=error.Message,hresult=error.HResult,same_request_no_replay=true});return 2;}
        finally
        {
            for(int i=Refs.Count-1;i>=0;i--)if(Marshal.IsComObject(Refs[i]))try{Marshal.ReleaseComObject(Refs[i]);}catch{}
            Emit("execution_finished",new{run_id=RunId,macro_sha256=MacroSha,checks_sha256=CheckSha,com_return_observed=ComReturned,script_error_returned=ScriptErrorReturned,outcome=outcome,bridge_pid=System.Diagnostics.Process.GetCurrentProcess().Id});
        }
    }
}
