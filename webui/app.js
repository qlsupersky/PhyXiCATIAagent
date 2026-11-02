'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('phyxiToken');
if (token) sessionStorage.setItem('phyxiToken', token);
history.replaceState(null, '', location.pathname);
let files = [], busy = false, requestBusy = false, taskMode = false, catalog = {}, operation = null;
let lastView = '', lastPlans = '';
function notice(text, error=false) { $('notice').textContent = text; $('notice').classList.toggle('error', error); }
async function api(route, body) {
  const response = await fetch('/api/' + route, {method: body === undefined ? 'GET':'POST',
    headers: {'Authorization':'Bearer ' + token, 'Content-Type':'application/json'}, body: body === undefined ? undefined:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
  return result;
}
function element(tag, text, cls) {const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function options(id, list, label, selected) {
  const select=$(id); select.replaceChildren(new Option(label,''));
  for(const item of list)select.add(new Option(item.label,item.id));
  if(selected!==undefined)select.value=selected;
}
function choose() {
  const model = catalog.models?.find(m=>m.providerID+'/'+m.id===$('models').value);
  return {model:model?{id:model.id,providerID:model.providerID,...($('variants').value?{variant:$('variants').value}:{})}:null,agent:$('agents').value||null};
}
function setBusy(value) {
  busy = value;
  for(const id of ['send','new','connect','sessions','models','agents','variants','attach','file','clear','refresh','prompt'])$(id).disabled = value || requestBusy;
}
function render(state) {
  setBusy(!!state.active);
  $('connection').textContent = state.connected?'已连接':'未连接';$('connection').classList.toggle('ready',state.connected);
  $('project').textContent = state.project || '';
  $('mcp').replaceChildren();
  for(const server of state.mcp||[]) {const row=element('div',undefined,'server'); row.append(element('i',undefined,'dot '+(server.status.status==='connected'?'ok':'')),element('span',server.name+' · '+server.status.status));$('mcp').append(row);}
  if(state.catalog?.models?.length && JSON.stringify(catalog)!==JSON.stringify(state.catalog)) {
    catalog=state.catalog;
    options('models',catalog.models.map(m=>({id:m.providerID+'/'+m.id,label:m.providerID+' / '+m.name})),'沿用会话模型');
    options('agents',catalog.agents.map(a=>({id:a.id,label:a.name})),'沿用会话 Agent');
  }
  if(state.sessions)options('sessions',state.sessions.map(s=>({id:s.id,label:s.title||s.id})),'选择或新建会话',state.session||'');
  if(JSON.stringify(state.plans)!==lastPlans){
    lastPlans=JSON.stringify(state.plans);$('plan-progress').replaceChildren();
    if(state.plans?.length)$('plan-progress').append(element('div','共享 CAD 队列的最近计划','section-label'));
    for(const plan of state.plans||[]){
      const card=element('div',undefined,'tool');card.append(element('div',plan.request_id+' · '+plan.status,'tool-title'));
      for(const result of plan.results||[])card.append(element('div',result.step+' · '+result.code+' · 核验 '+result.verification.status,'step'));
      const event=plan.events?.at(-1);if(event?.type==='step_started')card.append(element('div','正在执行：'+event.step,'step'));
      if(plan.skipped_steps?.length)card.append(element('div','未执行：'+plan.skipped_steps.join(', '),'check'));
      $('plan-progress').append(card);
    }
  }
  const view=JSON.stringify([state.messages,state.tools]);
  if(view!==lastView) {
    lastView=view;
    const box=$('messages'),atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<90;
    if(state.messages?.length) {
      box.replaceChildren();
      for(const message of state.messages){const row=element('article',undefined,'message '+message.role);row.append(element('div',message.role==='user'?'你':'OPENCODE','role'),element('div',message.text));if(message.files?.length)row.append(element('div',message.files.join(' · '),'file-names'));box.append(row);}
      if(atBottom)box.scrollTop=box.scrollHeight;
    } else box.replaceChildren(element('div','连接 OpenCode，开始图文对话或多步骤任务。','empty'));
    $('tools').replaceChildren();
    for(const tool of state.tools||[]) {
      const card=element('div',undefined,'tool'),title=element('div',undefined,'tool-title');
      title.append(element('strong',tool.name),element('span',tool.status));card.append(title);
      const plan=tool.feedback?.plan;
      if(plan?.results)for(const result of plan.results){card.append(element('div',result.step+' · '+result.tool+' · '+result.code,'step'));card.append(element('div','核验：'+result.verification.status+' / 完成：'+result.completion,'check'));}
      const detail=element('details'); detail.append(element('summary','查看实际工具返回'),element('pre',tool.text));card.append(detail);$('tools').append(card);
    }
  }
  if(state.active){operation=state.active;sessionStorage.setItem('phyxiOperation',operation);$('job-status').textContent='正在执行 · '+state.active;}
}
async function action(fn){if(requestBusy)return;requestBusy=true;setBusy(busy);try{await fn();}catch(error){notice(error.message,true);}finally{requestBusy=false;setBusy(busy);}}
$('connect').onclick=()=>action(async()=>{notice('正在连接本机 OpenCode…');render(await api('connect',{}));notice('已连接。文字、图片与工具在同一会话中连续工作。');});
$('new').onclick=()=>action(async()=>{render(await api('new',choose()));notice('新对话已建立');});
$('sessions').onchange=()=>action(async()=>{if(!$('sessions').value)return;render(await api('select',{session:$('sessions').value}));$('models').value='';$('agents').value='';$('variants').value='';notice('已切换会话，沿用该会话模型和 Agent');});
$('models').onchange=()=>{const m=catalog.models.find(m=>m.providerID+'/'+m.id===$('models').value);options('variants',(m?.variants||[]).map(v=>({id:typeof v==='string'?v:v.id,label:typeof v==='string'?v:v.id})),'沿用模型变体');};
$('refresh').onclick=()=>action(async()=>{const state=await api('refresh',{});render(state);notice(state.pending?'原请求仍在执行或等待确认；未重发':'已有结果已刷新');});
$('full').onclick=()=>action(async()=>{await api('full',{});notice('已打开同一会话的 OpenCode 原生界面');});
$('interrupt').onclick=()=>action(async()=>{notice((await api('interrupt',{})).message);});
$('stop').onclick=()=>action(async()=>{await api('stop-waiting',{});notice('已停止前端等待，后端任务可能继续。刷新原会话核对，不重复发送。');});
function previews(){
  $('attachments').replaceChildren();
  for(const file of files){const card=element('div',undefined,'attachment');if(file.type.startsWith('image/')){const image=document.createElement('img');image.src=URL.createObjectURL(file);image.onload=()=>URL.revokeObjectURL(image.src);card.append(image);}card.append(element('span',file.name));$('attachments').append(card);}
}
function addFiles(items){if(busy)return;if(files.length+items.length>12)return notice('每轮最多12个附件',true);const next=[...files,...items];if(next.some(f=>f.size>8*1024*1024)||next.reduce((s,f)=>s+f.size,0)>16*1024*1024)return notice('单附件最多8MiB，每轮合计16MiB',true);files=next;previews();}
$('attach').onclick=()=>$('file').click();$('file').onchange=()=>{addFiles(Array.from($('file').files));$('file').value='';};
$('clear').onclick=()=>{files=[];previews();};
$('prompt').addEventListener('paste',event=>{const items=[...event.clipboardData.items].filter(i=>i.kind==='file').map(i=>i.getAsFile());if(items.length){event.preventDefault();addFiles(items);}});
function mode(enabled){taskMode=enabled;$('task-help').hidden=!enabled;$('chat-tab').classList.toggle('selected',!enabled);$('task-tab').classList.toggle('selected',enabled);$('prompt').placeholder=enabled?'每行一个目标，例如：\n创建制动盘原生零件\n检查体积和孔数\n保存并重新打开核对':'例如：按参考图创建五孔制动盘，检查体积并保存原生零件…';}
$('chat-tab').onclick=()=>mode(false);$('task-tab').onclick=()=>mode(true);
async function fileData(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onerror=reject;r.onload=()=>resolve({name:file.name,data:r.result.split(',')[1]});r.readAsDataURL(file);});}
$('send').onclick=()=>action(async()=>{
  let text=$('prompt').value.trim();if(!text&&!files.length)return;
  if(taskMode)text='请在同一轮中按顺序完成以下任务，使用实际工具结果反馈每一步。若支持catia_plan_run，可将明确的CATIA工具步骤合并为一次计划调用；遇到失败停止后续修改，报告已完成、失败和未执行项，不把未测量项标为通过。\n'+text.split('\n').filter(x=>x.trim()).map((x,i)=>(i+1)+'. '+x).join('\n');
  const payload={operation_id:crypto.randomUUID(),text,files:await Promise.all(files.map(fileData)),...choose()};
  // A lost HTTP response never triggers automatic POST replay.
  operation=payload.operation_id;sessionStorage.setItem('phyxiOperation',operation);
  const job=await api('send',payload);setBusy(job.status==='RUNNING');$('prompt').value='';files=[];previews();notice('任务已提交。工具反馈将持续更新。');
});
$('prompt').addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();if(!busy&&!requestBusy)$('send').click();}});
async function poll(){
  try{
    if(!token)return notice('缺少本机会话认证，请使用启动入口重新打开。',true);
    const state=await api('state');render(state);
    const id=operation||sessionStorage.getItem('phyxiOperation');
    if(id){const job=await api('jobs/'+id);$('job-status').textContent=job.status+' · '+id+(job.message?'\n'+job.message:'');if(job.status!=='RUNNING'&&job.status!=='NOT_FOUND'){notice(job.status==='SUCCEEDED'?'本轮已完成。请查看实际工具反馈与核验结果。':'本轮状态：'+job.status+'。请刷新原会话核对。',job.status!=='SUCCEEDED');operation=null;sessionStorage.removeItem('phyxiOperation');}}
  }catch(error){if(busy)notice('连接暂时不可用，未重发请求。可稍后刷新原会话。',true);}
  finally{setTimeout(poll,900);}
}
poll();
