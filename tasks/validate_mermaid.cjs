const fs = require('fs');
const path = require('path');
const http = require('http');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const assets = 'C:/Users/Minsoo/.vscode/extensions/openai.chatgpt-26.51021.22027-win32-x64/webview/assets';
const names = ['통합프로젝트_계획.md','심화프로젝트_계획.md','docs/구현명세/기본프로젝트_구현명세.md','docs/구현명세/심화프로젝트_구현명세.md'];
const output = path.join(__dirname, 'validation');
fs.mkdirSync(output,{recursive:true});
const diagrams = names.flatMap(name => [...fs.readFileSync(path.join(root,name),'utf8').matchAll(/```mermaid\r?\n([\s\S]*?)```/g)].map((m,i)=>({file:name,index:i+1,source:m[1]})));
const server = http.createServer((req,res)=>{
  if(req.url==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<html><body style="margin:24px;background:white;font-family:Malgun Gothic"></body></html>');return;}
  const filename = path.resolve(assets,decodeURIComponent(req.url.slice(1)));
  if(!filename.startsWith(path.resolve(assets)+path.sep)){res.writeHead(403);res.end();return;}
  if(!fs.existsSync(filename)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',filename.endsWith('.js')?'text/javascript':'application/octet-stream');fs.createReadStream(filename).pipe(res);
});
(async()=>{
  let browser;
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const origin=`http://127.0.0.1:${server.address().port}`;
    browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    await context.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.abort());
    const page=await context.newPage();await page.goto(origin);
    await page.evaluate(async()=>{window.mermaid=(await import('/mermaid.core-935601623134.js')).default;window.mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'neutral',fontFamily:'Malgun Gothic',flowchart:{htmlLabels:false}});});
    const results=[];
    for(let i=0;i<diagrams.length;i++){
      const diagram=diagrams[i];
      try{
        const svg=await page.evaluate(async({source,id})=>{await window.mermaid.parse(source); const {svg}=await window.mermaid.render(id,source); document.body.innerHTML='<main style="width:1200px">'+svg+'</main>';return svg;},{source:diagram.source,id:'diagram'+i});
        fs.writeFileSync(path.join(output,`diagram-${i+1}.svg`),svg);
        await page.locator('main').screenshot({path:path.join(output,`diagram-${i+1}.png`)});
        results.push({file:diagram.file,index:diagram.index,status:'PASS'});
      }catch(e){results.push({file:diagram.file,index:diagram.index,status:'FAIL',error:e.message});}
    }
    const report={engine:'Local bundled Mermaid in isolated headless Chrome; external requests blocked',diagrams:results};
    fs.writeFileSync(path.join(output,'mermaid-validation.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));if(results.some(r=>r.status==='FAIL'))process.exitCode=1;
  }catch(e){console.error(e.stack);process.exitCode=1;}
  finally{if(browser)await browser.close();server.close();}
})();
