const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {setup}=require('../app/static/pwa.js');
function installPage({secure=true,standalone=false}={}){
  const handlers={},registrations=[],nodes={};
  for(const id of ['install-app','install-close','install-message','install-dialog'])nodes[id]={hidden:false,textContent:'',open:false,classList:{toggle(){}},showModal(){this.open=true;},close(){this.open=false;}};
  const win={isSecureContext:secure,navigator:{serviceWorker:{register:(...args)=>{registrations.push(args);return Promise.resolve();}}},matchMedia:()=>({matches:standalone,addEventListener(){}}),addEventListener:(name,fn)=>handlers[name]=fn};
  setup(win,{getElementById:id=>nodes[id]});return {handlers,registrations,nodes};
}
test('install prompt is captured, only opened by click and consumed once',async()=>{
  const p=installPage();let prompts=0,prevented=0;
  p.handlers.beforeinstallprompt({preventDefault(){prevented++;},prompt:async()=>prompts++,userChoice:Promise.resolve({outcome:'dismissed'})});
  assert.equal(prevented,1);assert.equal(prompts,0);
  await p.nodes['install-app'].onclick();assert.equal(prompts,1);
  await p.nodes['install-app'].onclick();assert.equal(prompts,1);assert.ok(p.nodes['install-dialog'].open);
  assert.deepEqual(p.registrations,[['/service-worker.js',{scope:'/',updateViaCache:'none'}]]);
});
test('installed or standalone apps hide install and close its guide',async()=>{
  assert.ok(installPage({standalone:true}).nodes['install-app'].hidden);
  const p=installPage();await p.nodes['install-app'].onclick();assert.ok(p.nodes['install-dialog'].open);
  p.handlers.appinstalled();assert.ok(p.nodes['install-app'].hidden);assert.ok(!p.nodes['install-dialog'].open);
});
test('insecure origins explain HTTPS and do not register a worker',async()=>{
  const p=installPage({secure:false});await p.nodes['install-app'].onclick();
  assert.equal(p.registrations.length,0);assert.match(p.nodes['install-message'].textContent,/HTTPS/);
  p.nodes['install-close'].onclick();assert.ok(!p.nodes['install-dialog'].open);
});
function worker(){
  const handlers={},puts=[],deleted=[];let claims=0,network=async()=>new Response('fresh');
  const cache={addAll:async()=>{},put:async(...args)=>puts.push(args)};
  const caches={open:async()=>cache,match:async key=>new Response(typeof key==='string'&&key.includes('offline')?'Reconnect':'cached asset'),keys:async()=>['junction-static-old','junction-static-v1','junction-static-v3','other-app'],delete:async key=>deleted.push(key)};
  const self={location:{origin:'https://junction.test'},addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting:async()=>{},clients:{claim:async()=>claims++}};
  const context=vm.createContext({self,caches,URL,Response,fetch:request=>network(request)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/service-worker.js'),'utf8'),context);
  return {handlers,puts,deleted,cache,claims:()=>claims,setNetwork:fn=>network=fn,request:async(path,options={})=>{let response;handlers.fetch({request:{url:'https://junction.test'+path,method:'GET',mode:'cors',...options},respondWith:value=>response=value});return response?await response:undefined;}};
}
test('API reads stay live and offline writes fail explicitly without caching',async()=>{
  const w=worker();assert.equal(await (await w.request('/api/fragments')).text(),'fresh');assert.equal(w.puts.length,0);
  w.setNetwork(async()=>{throw Error('offline');});
  const response=await w.request('/api/build-list',{method:'POST'});
  assert.equal(response.status,503);assert.match((await response.json()).detail,/offline/);assert.equal(w.puts.length,0);
});
test('offline navigation shows reconnect rather than cached inventory or plans',async()=>{
  const w=worker();w.setNetwork(async()=>{throw Error('offline');});
  assert.equal(await (await w.request('/',{mode:'navigate'})).text(),'Reconnect');
  assert.equal(await (await w.request('/static/app.js?v=76')).text(),'cached asset');assert.equal(w.puts.length,0);
});
test('asset caching failures cannot break a valid online response',async()=>{
  const w=worker();w.cache.put=async()=>{throw Error('quota');};
  assert.equal(await (await w.request('/static/app.js?v=76')).text(),'fresh');
});
test('worker upgrade cleans only old Junction caches and claims clients',async()=>{
  const w=worker();let task;w.handlers.activate({waitUntil:value=>task=value});await task;
  assert.deepEqual(w.deleted,['junction-static-old','junction-static-v1']);assert.equal(w.claims(),1);
});
