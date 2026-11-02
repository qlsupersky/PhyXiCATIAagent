'use strict';
const {app, BrowserWindow, dialog} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
let child, window;
async function launch() {
  const root = path.resolve(__dirname,'..');
  const configFile = path.join(root,'config.json');
  const config = fs.existsSync(configFile)?JSON.parse(fs.readFileSync(configFile,'utf8').replace(/^\uFEFF/,'')):{};
  const python = process.env.PHYXI_PYTHON || config.python || 'python';
  const workspace = process.env.PHYXI_WORKSPACE || config.workspace;
  child = spawn(python,['-u',path.join(root,'web_server.py'),'--descriptor-stdout',...(workspace?['--workspace',workspace]:[])],
    {cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
  let opened = false;
  child.on('error',()=>dialog.showErrorBox('PhyXi','无法启动 Python 后端。请先运行 install.ps1 或设置 PHYXI_PYTHON。'));
  readline.createInterface({input:child.stdout}).on('line',async line=>{
    if(opened)return;
    let descriptor;try{descriptor=JSON.parse(line);}catch{return;}
    if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(descriptor.url)||typeof descriptor.token!=='string')return;
    opened=true;
    window = new BrowserWindow({width:1440,height:960,minWidth:900,minHeight:680,title:'PhyXi · CATIA 工作台',backgroundColor:'#f6f8fb',
      webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
    window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    window.webContents.on('will-navigate',(event,url)=>{if(new URL(url).origin!==descriptor.url)event.preventDefault();});
    await window.loadURL(descriptor.url+'/#token='+encodeURIComponent(descriptor.token));
    if(process.env.PHYXI_ELECTRON_SMOKE==='1'){
      setTimeout(async()=>{
        try{
          const title=await window.webContents.executeJavaScript('document.title');
          if(process.env.PHYXI_ELECTRON_SCREENSHOT){const picture=await window.webContents.capturePage();fs.writeFileSync(process.env.PHYXI_ELECTRON_SCREENSHOT,picture.toPNG());}
          console.log(JSON.stringify({smoke:true,title,nodeIntegration:false,sandbox:true}));app.quit();
        }catch{app.exit(1);}
      },1200);
    }
  });
  child.on('exit',()=>{if(!opened){dialog.showErrorBox('PhyXi','WebUI 后端启动失败。请检查 Python 依赖。');app.quit();}});
  // Do not print child stderr: upstream failures may contain provider details.
  child.stderr.on('data',()=>{});
}
app.whenReady().then(launch);
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',()=>{if(child?.stdin?.writable)child.stdin.end('shutdown\n');});
