"""Controlled paired transport benchmark. No model inference, no geometry writes."""
import argparse,asyncio,json,statistics,time
from pathlib import Path
from engine import Engine,Backends,load_config,encode,project
from feedback import content_for_status

async def benchmark(config_path,node,output,repeats=3):
 output=Path(output);output.mkdir(parents=True,exist_ok=False)
 config=load_config(config_path)
 opened=time.perf_counter()
 async with Backends(config,output) as live:
  startup_ms=(time.perf_counter()-opened)*1000
  class Borrowed:
   def __init__(self,config,folder): self.schemas=live.schemas
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def call(self,*args):return await live.call(*args)
  engine=Engine(output/'workspace',config,node,backend_factory=Borrowed)
  rows=[]
  for count in [1,6,18]:
   for repeat in range(repeats):
    for arm in (['direct','ptc'] if repeat%2==0 else ['ptc','direct']):
     start=time.perf_counter()
     if arm=='direct':
      replies=[]
      for i in range(count):
       replies.append(await live.call('catia-v5','catia_plan_catalog',{'names':['catia_pad','catia_pocket','catia_get_inertia'],'include_schema':True}))
      elapsed=(time.perf_counter()-start)*1000
      raw_bytes=sum(len(encode(x).encode()) for x in replies)
      (output/f'raw-direct-{count}-{repeat}.json').write_text(encode(replies),encoding='utf-8')
      row={'arm':arm,'count':count,'repeat':repeat,'elapsed_ms':elapsed,'raw_bytes':raw_bytes,
       'visible_result_bytes':raw_bytes,'code_bytes':0,'individual_business_calls':count,'ok':all(project(x)['ok'] for x in replies)}
     else:
      code=f'let total=0; for(let i=0;i<{count};i++){{const r=await tools.catia_v5.catia_plan_catalog({{names:["catia_pad","catia_pocket","catia_get_inertia"],include_schema:true}});assert(r.ok);total++;}} return {{queries:total,completed:true}};'
      rid=f'bench-{count}-{repeat}'
      await engine.start(rid,code)
      await asyncio.gather(*engine.tasks)
      result=engine.status(rid)
      envelope=content_for_status(result).model_dump(mode='json',exclude_none=True)
      row={'arm':arm,'count':count,'repeat':repeat,'elapsed_ms':(time.perf_counter()-start)*1000,
       'raw_bytes':result['raw_tool_bytes'],'visible_result_bytes':len(encode(envelope).encode()),
       'business_status_bytes':len(encode(result).encode()),
       'return_bytes':result['guest_result_bytes'],'code_bytes':len(code.encode()),
       'individual_business_calls':0,'program_submissions':1,'status_reads':1,
       'ok':result['status']=='SUCCEEDED','backend_ms':result['backend_ms']}
     rows.append(row)
     print(encode(row),flush=True)
     (output/'measurements.json').write_text(json.dumps({'shared_connection_startup_ms':startup_ms,'repeats':repeats,'rows':rows,'model_inference':False,'CAD_dispatch':False},indent=2),encoding='utf-8')
 return rows

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--backends',required=True);p.add_argument('--node',required=True);p.add_argument('--output',required=True)
 p.add_argument('--repeats',type=int,default=3)
 a=p.parse_args();asyncio.run(benchmark(a.backends,a.node,a.output,a.repeats))
