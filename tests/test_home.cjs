const {test}=require('node:test'),assert=require('node:assert/strict');
const {resolveView,consumeWelcome,setup}=require('../app/static/home.js');

function page({reduced=false,href='https://junction.test/?welcome=1#home'}={}){
  function node(){
    const classes=new Set(),attributes=new Map();
    return {hidden:true,inert:false,focused:0,style:{setProperty(){}},handlers:{},dataset:{},
      classList:{add:v=>classes.add(v),remove:v=>classes.delete(v),contains:v=>classes.has(v)},
      addEventListener(name,fn){this.handlers[name]=fn;},focus(){this.focused++;},
      setAttribute:(key,value)=>attributes.set(key,value),removeAttribute:key=>attributes.delete(key),
      querySelectorAll:()=>[],getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
  }
  const nodes=Object.fromEntries(['home','home-intro','home-intro-skip','home-heading'].map(id=>[id,node()]));
  nodes.home.classList.add('active');const backgrounds=[node(),node(),node()],cards=['build','design','library','uploads','compare','profile'].map(view=>Object.assign(node(),{dataset:{homeView:view}}));
  nodes.home.querySelectorAll=()=>cards;
  const target=node(),timers=new Map(),routes=[];let next=0,motion;
  const win={location:{href},history:{replaceState(a,b,url){win.location.href=new URL(url,win.location.href).href;}},
    setTimeout(fn,ms){timers.set(++next,{fn,ms});return next;},clearTimeout:id=>timers.delete(id),scrollTo(){},
    matchMedia:()=>({matches:reduced,addEventListener:(name,fn)=>{motion=fn;}})};
  const doc={getElementById:id=>nodes[id],querySelector:selector=>selector==='.topbar'?backgrounds[0]:selector==='main'?backgrounds[1]:selector==='body > footer'?backgrounds[2]:target};
  const controller=setup(win,doc,{navigate:view=>routes.push(view)});
  return {win,nodes,backgrounds,cards,routes,controller,timers,target,
    run(ms){const task=[...timers].find(([,t])=>t.ms===ms);assert.ok(task,'expected timer '+ms);timers.delete(task[0]);task[1].fn();}};
}
test('Home is the default while direct links to all tools and Profile remain valid',()=>{
  for(const view of ['home','build','design','library','uploads','compare','profile','workbenches','bin'])assert.equal(resolveView(view),view);
  for(const value of ['',undefined,'unknown','<script>'])assert.equal(resolveView(value),'home');
});
test('successful-login marker is consumed once without losing URL parameters or the current route',()=>{
  const p=page({href:'https://junction.test/?welcome=1&other=keep#home'});
  assert.equal(consumeWelcome(p.win),true);assert.equal(p.win.location.href,'https://junction.test/?other=keep#home');
  assert.equal(consumeWelcome(p.win),false);
});
test('login intro isolates background controls, finishes and restores keyboard focus once',()=>{
  const p=page();p.controller.welcome();
  assert.equal(p.nodes['home-intro'].hidden,false);assert.ok(p.backgrounds.every(n=>n.inert));
  assert.equal(p.nodes['home-intro-skip'].focused,1);
  p.run(1850);assert.ok(p.backgrounds.every(n=>!n.inert));assert.equal(p.nodes['home-heading'].focused,1);
  p.run(350);assert.equal(p.nodes['home-intro'].hidden,true);
  p.controller.welcome();assert.equal(p.nodes['home-intro'].hidden,true);assert.equal(p.timers.size,0);
});
test('Skip and Escape both end the entrance and preserve focus in Home',()=>{
  for(const escape of [false,true]){
    const p=page();p.controller.welcome();
    if(escape)p.nodes['home-intro'].handlers.keydown({key:'Escape',preventDefault(){}});
    else p.nodes['home-intro-skip'].handlers.click();
    assert.equal(p.nodes['home-heading'].focused,1);assert.ok(p.backgrounds.every(n=>!n.inert));
    assert.ok(![...p.timers.values()].some(t=>t.ms===1850));
  }
});
test('reduced motion skips the intro, and deep links never get a blocking entrance',()=>{
  for(const reduced of [true,false]){
    const p=page({reduced});if(!reduced)p.nodes.home.classList.remove('active');p.controller.welcome();
    assert.equal(p.nodes['home-intro'].hidden,true);assert.equal(p.timers.size,0);assert.ok(p.backgrounds.every(n=>!n.inert));
  }
});
test('leaving Home during an entrance cancels it and releases controls',()=>{
  const p=page();p.controller.welcome();p.controller.viewChanged('build');
  assert.equal(p.nodes['home-intro'].hidden,true);assert.equal(p.timers.size,0);assert.ok(p.backgrounds.every(n=>!n.inert));
});
test('cards route to real tools and Profile while modified clicks retain normal browser behavior',()=>{
  const p=page({href:'https://junction.test/#home'});let prevented=0;
  for(const card of p.cards)card.handlers.click({button:0,preventDefault(){prevented++;}});
  assert.deepEqual(p.routes,['build','design','library','uploads','compare','profile']);assert.equal(prevented,6);
  for(const options of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1},{defaultPrevented:true}]){
    p.cards[0].handlers.click({...options,preventDefault(){throw Error('must preserve native navigation');}});
  }
  assert.equal(p.routes.length,6);
});
