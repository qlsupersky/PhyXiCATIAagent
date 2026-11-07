// Run once with a fresh outer request ID. This is an async-function body.
const gate = await tools.native_modeling.modeling_status({});
assert(gate.data.gate.status === 'IDLE', 'Shared CATIA gate is busy');
await tools.catia_v5.catia_connect({});
const docs = await tools.catia_v5.catia_list_documents({});
const w=80,h=50,t=8,bossR=12,bossH=12,boreR=5;
const locations = [-28,0,28].flatMap(x=>[-16,16].map(y=>({x,y,r:3})));
const holes = locations.filter(p=>Math.hypot(p.x,p.y)-p.r>bossR);
assert(holes.length===6,'Bolt holes overlap boss');
const code = ['Language="VBSCRIPT"','Sub CATMain(runId, outputPath, resultPath)',
'Dim doc, part, body, sk, f, pad, bs, bf, boss, hs, hf, cut, cs, cf, bore',
'Set doc=CATIA.Documents.Add("Part")','Set part=doc.Part','Set body=part.MainBody',
'body.Name="Own_" & runId','doc.Product.PartNumber="CodeModeSixHoleFlange"',
'part.InWorkObject=body','Set sk=body.Sketches.Add(part.OriginElements.PlaneXY)',
'sk.Name="BaseSketch"','Set f=sk.OpenEdition()'];
const v=[[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]];
for(let i=0;i<4;i++){const a=v[i],b=v[(i+1)%4];code.push(`f.CreateLine ${a[0]},${a[1]},${b[0]},${b[1]}`);}
code.push('sk.CloseEdition',`Set pad=part.ShapeFactory.AddNewPad(sk,${t})`,
'pad.Name="BasePad"','part.Update','part.InWorkObject=body',
'Set bs=body.Sketches.Add(part.OriginElements.PlaneXY)','bs.Name="BossSketch"',
'Set bf=bs.OpenEdition()',`bf.CreateClosedCircle 0,0,${bossR}`,'bs.CloseEdition',
`Set boss=part.ShapeFactory.AddNewPad(bs,${bossH})`,'boss.Name="CentralBoss"',
'part.Update','part.InWorkObject=body',
'Set hs=body.Sketches.Add(part.OriginElements.PlaneXY)','hs.Name="BoltSketch"','Set hf=hs.OpenEdition()');
for(const p of holes) code.push(`hf.CreateClosedCircle ${p.x},${p.y},${p.r}`);
code.push('hs.CloseEdition','Set cut=part.ShapeFactory.AddNewPocket(hs,24)',
'cut.Name="SixBoltHoles"','cut.IsSymmetric=True','part.Update','part.InWorkObject=body',
'Set cs=body.Sketches.Add(part.OriginElements.PlaneXY)','cs.Name="CenterSketch"',
'Set cf=cs.OpenEdition()',`cf.CreateClosedCircle 0,0,${boreR}`,'cs.CloseEdition',
'Set bore=part.ShapeFactory.AddNewPocket(cs,24)','bore.Name="CenterBore"',
'bore.IsSymmetric=True','part.Update','End Sub');
const expected=w*h*t+Math.PI*bossR**2*(bossH-t)
 -holes.reduce((sum,p)=>sum+Math.PI*p.r**2*t,0)-Math.PI*boreR**2*bossH;
const result=await tools.native_modeling.modeling_execute({
request_id:'ptc-six-hole-flange-20261107-01',
requirement:'Create an editable80x50x8mm plate, central R12 boss total height12mm, six D6 bolt through holes and D10 central bore. Preserve existing documents.',
macro_ascii:code.join('\n')+'\n',
checks:{features:[{name:'BasePad',depth_mm:t,symmetric:false},
{name:'CentralBoss',depth_mm:bossH,symmetric:false},
{name:'SixBoltHoles',depth_mm:24,symmetric:true},
{name:'CenterBore',depth_mm:24,symmetric:true}],sketch_count:4,volume_mm3:expected},
summary:'Code Mode generated native demonstration flange with loop and geometry checks.'});
const finalGate=await tools.native_modeling.modeling_status({});
assert(finalGate.data.gate.status==='IDLE');
assert(result.data.final.passed && result.data.reopened_readback.passed,'Native readback failed');
const verified=result.data.reopened_readback;
return {boltHoles:holes.length,centerBore:1,expectedVolume_mm3:expected,
 existingDocuments:Array.isArray(docs.data)?docs.data.length:null,
 job_id:result.data.job_id,model:result.data.final.model,
 measuredVolume_mm3:verified.volume_mm3,saved:verified.saved,
 features:verified.features.map(f=>f.name),sketches:verified.sketch_count,
 bodies:verified.body_count,gate:finalGate.data.gate.status};
