const {test}=require('node:test'),assert=require('node:assert/strict');
const {resolveView,consumeWelcome,setup}=require('../app/static/home.js');

function page({reduced=false,href='https://junction.test/?welcome=1#home',active=true,loadingMode='splash'}={}){
  function node(){
    const classes=new Set(),attributes=new Map();
    return {hidden:true,inert:false,focused:0,isConnected:true,style:{setProperty(){}},handlers:{},dataset:{},attributes,
      classList:{add:(...v)=>v.forEach(x=>classes.add(x)),remove:(...v)=>v.forEach(x=>classes.delete(x)),contains:v=>classes.has(v)},
      addEventListener(name,fn){this.handlers[name]=fn;},focus(){this.focused++;},
      setAttribute:(key,value)=>attributes.set(key,value),removeAttribute:key=>attributes.delete(key),
      querySelectorAll:()=>[],getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
  }
  const nodes=Object.fromEntries(['home','home-intro','home-intro-skip','home-heading','home-intro-status','home-intro-retry','workbench-floating','worksheet-load-toast','worksheet-load-status','worksheet-load-retry'].map(id=>[id,node()]));
  if(active)nodes.home.classList.add('active');
  const backgrounds=[node(),node(),node(),nodes['workbench-floating']],cards=['build','design','library','uploads','compare','workbenches'].map(view=>Object.assign(node(),{dataset:{homeView:view}}));
  nodes.home.querySelectorAll=()=>cards;
  const target=node(),previous=node(),timers=new Map(),routes=[];let next=0,now=0,reloads=0;
  const win={location:{href,reload(){reloads++;}},history:{replaceState(a,b,url){win.location.href=new URL(url,win.location.href).href;}},performance:{now:()=>now},
    setTimeout(fn,ms){timers.set(++next,{fn,ms});return next;},clearTimeout:id=>timers.delete(id),scrollTo(){},
    matchMedia:()=>({matches:reduced,addEventListener(){}})};
  const doc={documentElement:{dataset:{loading:loadingMode}},activeElement:previous,getElementById:id=>nodes[id],querySelector:selector=>selector==='.topbar'?backgrounds[0]:selector==='main'?backgrounds[1]:selector==='body > footer'?backgrounds[2]:target};
  const controller=setup(win,doc,{navigate:view=>routes.push(view)});
  return {win,nodes,backgrounds,cards,routes,controller,timers,target,previous,
    elapsed(ms){now+=ms;},get reloads(){return reloads;},
    run(ms){const task=[...timers].find(([,t])=>t.ms===ms);assert.ok(task,'expected timer '+ms);timers.delete(task[0]);now+=ms;task[1].fn();}};
}
test('Home is the default while direct links to all tools and Profile remain valid',()=>{
  for(const view of ['home','build','design','library','uploads','compare','profile','workbenches','bin'])assert.equal(resolveView(view),view);
  for(const value of ['',undefined,'unknown','<script>'])assert.equal(resolveView(value),'home');
});
test('startup markers are consumed without losing URL parameters or the current route',()=>{
  const p=page({href:'https://junction.test/?welcome=1&instance=123&other=keep#build'});
  assert.equal(consumeWelcome(p.win),true);assert.equal(p.win.location.href,'https://junction.test/?other=keep#build');
  assert.equal(consumeWelcome(p.win),false);
});
test('every app opening shows a loading splash and isolates all background controls',()=>{
  const p=page({href:'https://junction.test/#home'});
  assert.equal(p.controller.isLoading,true);assert.equal(p.nodes['home-intro'].hidden,false);
  assert.equal(p.nodes['home-intro-status'].textContent,'Opening Junction…');
  assert.ok(p.backgrounds.every(n=>n.inert));assert.equal(p.nodes['home-intro'].focused,1);
  assert.equal(p.nodes['home-intro-skip'].hidden,true);assert.equal(p.nodes['home-intro-skip'].disabled,true);
  assert.equal(p.timers.size,0);
});
test('progress updates are text and loading cannot be skipped or escaped',()=>{
  const p=page();p.controller.status('Loading fragments…');
  assert.equal(p.nodes['home-intro-status'].textContent,'Loading fragments…');
  p.nodes['home-intro-skip'].handlers.click();p.nodes['home-intro'].handlers.keydown({key:'Escape',preventDefault(){}});
  assert.equal(p.nodes['home-intro'].hidden,false);assert.ok(p.backgrounds.every(n=>n.inert));
});
test('ready completes only the remaining animation, releases controls and focuses the heading',()=>{
  const p=page();p.elapsed(600);p.controller.ready();
  assert.equal(p.controller.isLoading,false);assert.equal(p.nodes['home-intro-status'].textContent,'Ready');
  assert.equal(p.nodes['home-intro-skip'].hidden,false);p.run(700);
  assert.ok(p.backgrounds.every(n=>!n.inert));assert.equal(p.nodes['home-heading'].focused,1);
  p.run(350);assert.equal(p.nodes['home-intro'].hidden,true);assert.equal(p.timers.size,0);
});
test('a slow restore has no additional entrance delay',()=>{
  const p=page();p.elapsed(3000);p.controller.ready();
  assert.ok(p.backgrounds.every(n=>!n.inert));assert.equal(p.nodes['home-heading'].focused,1);
  assert.deepEqual([...p.timers.values()].map(t=>t.ms),[350]);
});
test('Skip and Escape dismiss remaining animation after restoration completes',()=>{
  for(const escape of [false,true]){
    const p=page();p.controller.ready();
    if(escape)p.nodes['home-intro'].handlers.keydown({key:'Escape',preventDefault(){}});
    else p.nodes['home-intro-skip'].handlers.click();
    assert.equal(p.nodes['home-heading'].focused,1);assert.ok(p.backgrounds.every(n=>!n.inert));
    assert.ok(![...p.timers.values()].some(t=>t.ms===1300));
  }
});
test('deep links stay covered while restoring and focus their tool when ready',()=>{
  const p=page({active:false,href:'https://junction.test/#build'});p.controller.viewChanged('build');
  assert.ok(p.backgrounds.every(n=>n.inert));assert.equal(p.nodes['home-intro'].hidden,false);
  p.elapsed(1500);p.controller.ready();assert.equal(p.target.focused,1);assert.equal(p.nodes['home-heading'].focused,0);
});
test('reduced motion still waits for data, then reveals the restored instance immediately',()=>{
  const p=page({reduced:true});assert.equal(p.nodes['home-intro'].hidden,false);
  assert.ok(p.backgrounds.every(n=>n.inert));p.controller.ready();
  assert.equal(p.nodes['home-intro'].hidden,true);assert.ok(p.backgrounds.every(n=>!n.inert));assert.equal(p.timers.size,0);
});
test('loading failures keep the app isolated and provide a working Retry action',()=>{
  const p=page();p.controller.fail('<network unavailable>');
  assert.equal(p.nodes['home-intro-status'].textContent,'Could not load Junction. <network unavailable>');
  assert.equal(p.nodes['home-intro-retry'].hidden,false);assert.equal(p.nodes['home-intro-retry'].focused,1);
  assert.equal(p.nodes['home-intro'].attributes.get('aria-busy'),'false');
  p.nodes['home-intro'].handlers.keydown({key:'Escape',preventDefault(){}});p.nodes['home-intro-skip'].handlers.click();
  assert.ok(p.backgrounds.every(n=>n.inert));p.nodes['home-intro-retry'].handlers.click();assert.equal(p.reloads,1);
});
test('failed instance switches return to the ready UI without changing the old focus tab order',()=>{
  const p=page();p.controller.start('Loading Workbench…');p.controller.cancel();
  assert.equal(p.nodes['home-intro'].hidden,true);assert.ok(p.backgrounds.every(n=>!n.inert));
  assert.equal(p.previous.focused,1);assert.equal(p.previous.attributes.has('tabindex'),false);
});
test('starting another load cancels a pending fade from the previous load',()=>{
  const p=page();p.elapsed(1500);p.controller.ready();assert.equal(p.timers.size,1);
  p.controller.start('Loading another instance…');assert.equal(p.timers.size,0);
  assert.equal(p.nodes['home-intro'].hidden,false);assert.equal(p.nodes['home-intro'].classList.contains('home-intro-done'),false);
  assert.ok(p.backgrounds.every(n=>n.inert));p.controller.ready();p.run(1300);p.run(350);
  assert.equal(p.nodes['home-intro'].hidden,true);
});
test('dialog callbacks wait for restoration to finish',()=>{
  const p=page();let calls=0;p.controller.onReady(()=>calls++);assert.equal(calls,0);
  p.controller.ready();assert.equal(calls,0);p.run(1300);assert.equal(calls,1);
  p.controller.onReady(()=>calls++);assert.equal(calls,2);
});
test('cards route to tools and Workbench while modified clicks retain native behavior',()=>{
  const p=page({href:'https://junction.test/#home'});let prevented=0;
  for(const card of p.cards)card.handlers.click({button:0,preventDefault(){prevented++;}});
  assert.deepEqual(p.routes,['build','design','library','uploads','compare','workbenches']);assert.equal(prevented,6);
  for(const options of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1},{defaultPrevented:true}]){
    p.cards[0].handlers.click({...options,preventDefault(){throw Error('must preserve native navigation');}});
  }
  assert.equal(p.routes.length,6);
});

test('worksheet reloads show progress as a toast with no splash or minimum animation delay',()=>{
  const p=page({loadingMode:'worksheet',active:false,href:'https://junction.test/?worksheet=123#design'});
  const toast=p.nodes['worksheet-load-toast'];
  assert.equal(p.nodes['home-intro'].hidden,true);assert.equal(p.nodes['home-intro'].inert,true);
  assert.equal(toast.classList.contains('visible'),true);assert.equal(toast.classList.contains('loading'),true);
  assert.equal(p.nodes['worksheet-load-status'].textContent,'Loading worksheet…');
  p.controller.status('Restoring worksheets…');assert.equal(p.nodes['worksheet-load-status'].textContent,'Restoring worksheets…');
  p.controller.ready();assert.ok(p.backgrounds.every(n=>!n.inert));assert.equal(p.target.focused,1);
  assert.equal(p.nodes['worksheet-load-status'].textContent,'Worksheet loaded');
  assert.equal(p.win.location.href,'https://junction.test/#design');
  assert.deepEqual([...p.timers.values()].map(t=>t.ms),[2000]);
  p.run(2000);assert.equal(toast.classList.contains('visible'),false);
});
test('worksheet switch operations keep the splash hidden and can safely return after failure',()=>{
  const p=page();p.elapsed(1500);p.controller.ready();
  p.controller.startWorksheet('Saving the current worksheet…');
  assert.equal(p.nodes['home-intro'].hidden,true);assert.equal(p.nodes['worksheet-load-status'].textContent,'Saving the current worksheet…');
  assert.ok(p.backgrounds.every(n=>n.inert));assert.equal(p.timers.size,0);
  p.controller.cancel();assert.ok(p.backgrounds.every(n=>!n.inert));assert.equal(p.previous.focused,1);
  assert.equal(p.nodes['worksheet-load-toast'].classList.contains('visible'),false);
});
test('worksheet hydration failures keep their error and Retry action in the toast',()=>{
  const p=page({loadingMode:'worksheet'});p.controller.fail('Connection lost');
  assert.equal(p.nodes['home-intro'].hidden,true);assert.ok(p.backgrounds.every(n=>n.inert));
  assert.equal(p.nodes['worksheet-load-status'].textContent,'Could not load worksheet. Connection lost');
  assert.equal(p.nodes['worksheet-load-retry'].hidden,false);assert.equal(p.nodes['worksheet-load-retry'].focused,1);
  assert.equal(p.nodes['worksheet-load-toast'].classList.contains('loading'),false);
  p.nodes['worksheet-load-retry'].handlers.click();assert.equal(p.reloads,1);
});
test('opening a Workbench after a worksheet brings back the full splash',()=>{
  const p=page({loadingMode:'worksheet'});p.controller.ready();p.controller.start('Loading Workbench…');
  assert.equal(p.nodes['home-intro'].hidden,false);assert.equal(p.nodes['home-intro'].inert,false);
  assert.equal(p.nodes['worksheet-load-toast'].classList.contains('visible'),false);
  assert.equal(p.nodes['home-intro-status'].textContent,'Loading Workbench…');assert.ok(p.backgrounds.every(n=>n.inert));
});
