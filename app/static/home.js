/* Home navigation and the animated loading screen for instance restoration. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.JunctionHome=factory();
})(typeof window==='object'?window:globalThis,()=>{
  const views=new Set(['home','build','design','library','uploads','compare','profile','workbenches','bin']);
  function resolveView(value){return views.has(value)?value:'home';}
  function consumeWelcome(win){
    const url=new URL(win.location.href),welcome=url.searchParams.get('welcome')==='1';
    if(welcome||url.searchParams.has('instance')){url.searchParams.delete('welcome');url.searchParams.delete('instance');win.history.replaceState(null,'',url.pathname+url.search+url.hash);}
    return welcome;
  }
  function setup(win,doc,{navigate}){
    const home=doc.getElementById('home'),intro=doc.getElementById('home-intro');
    const skip=doc.getElementById('home-intro-skip'),heading=doc.getElementById('home-heading');
    const reduced=win.matchMedia('(prefers-reduced-motion: reduce)');
    const background=[doc.querySelector('.topbar'),doc.querySelector('main'),doc.querySelector('body > footer'),doc.getElementById('workbench-floating')].filter(Boolean);
    const status=doc.getElementById('home-intro-status'),retryButton=doc.getElementById('home-intro-retry');
    const clock=()=>win.performance?.now?.()??Date.now();
    let timer=null,closing=null,playing=false,loading=false,failed=false,started=0,previousFocus=null;
    const readyCallbacks=[];
    function setStatus(message){status.textContent=message;}
    function finish({focus=false,immediate=false,restore=false}={}){
      if(loading||failed)return;
      win.clearTimeout(timer);win.clearTimeout(closing);playing=false;
      background.forEach(node=>node.inert=false);
      intro.inert=true;intro.removeAttribute('aria-modal');
      intro.classList.add('home-intro-done');
      if(immediate||reduced.matches)intro.hidden=true;
      else closing=win.setTimeout(()=>{intro.hidden=true;},350);
      home.classList.add('jhome-revealed');
      if(focus){
        const target=restore&&previousFocus?.isConnected?previousFocus:home.classList.contains('active')?heading:doc.querySelector('.view.active h1');
        if(target&&!(restore&&target===previousFocus))target.setAttribute('tabindex','-1');target?.focus({preventScroll:true});
      }
      const callbacks=readyCallbacks.splice(0);callbacks.forEach(fn=>fn());
    }
    function start(message='Opening Junction…'){
      win.clearTimeout(closing);win.clearTimeout(timer);started=clock();previousFocus=doc.activeElement;
      playing=true;loading=true;failed=false;
      intro.hidden=false;intro.inert=false;intro.setAttribute('aria-modal','true');intro.setAttribute('aria-label','Loading Junction');intro.setAttribute('aria-busy','true');
      intro.classList.remove('home-intro-done','home-intro-error');home.classList.remove('jhome-revealed');
      skip.hidden=true;skip.disabled=true;retryButton.hidden=true;setStatus(message);
      background.forEach(node=>node.inert=true);
      for(const node of intro.querySelectorAll('.j-part,.splash-type,.intro-orbit,.intro-wordmark')){
        node.style.animation='none';void node.offsetWidth;node.style.animation='';
      }
      intro.focus({preventScroll:true});
    }
    function ready(message='Ready'){
      if(!playing)return;
      loading=false;failed=false;intro.setAttribute('aria-busy','false');intro.setAttribute('aria-label','Junction ready');
      skip.hidden=false;skip.disabled=false;setStatus(message);consumeWelcome(win);
      const remaining=reduced.matches?0:Math.max(0,1300-(clock()-started));
      if(!remaining)finish({focus:true,immediate:reduced.matches});
      else timer=win.setTimeout(()=>finish({focus:true}),remaining);
    }
    function fail(message){
      win.clearTimeout(timer);loading=false;failed=true;
      intro.setAttribute('aria-busy','false');intro.setAttribute('aria-label','Junction loading error');intro.classList.add('home-intro-error');
      skip.hidden=true;skip.disabled=true;retryButton.hidden=false;setStatus('Could not load Junction. '+message);retryButton.focus();
    }
    function cancel(){loading=false;failed=false;retryButton.hidden=true;finish({focus:true,immediate:true,restore:true});}
    skip.addEventListener('click',()=>finish({focus:true}));
    retryButton.addEventListener('click',()=>win.location.reload());
    intro.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&!loading&&!failed){event.preventDefault();finish({focus:true});}
      if(event.key==='Tab'){event.preventDefault();(failed?retryButton:loading?intro:skip).focus();}
    });
    for(const card of home.querySelectorAll('[data-home-view]')){
      card.addEventListener('click',event=>{
        if(event.defaultPrevented||event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
        event.preventDefault();navigate(card.dataset.homeView);
        if(card.dataset.homeView!=='profile'){const title=doc.querySelector('.view.active h1');title?.setAttribute('tabindex','-1');title?.focus({preventScroll:true});}
        win.scrollTo({top:0,behavior:'auto'});
      });
      card.addEventListener('pointermove',event=>{
        if(reduced.matches)return;
        const rect=card.getBoundingClientRect();
        card.style.setProperty('--mx',(event.clientX-rect.left)/rect.width*100+'%');
        card.style.setProperty('--my',(event.clientY-rect.top)/rect.height*100+'%');
      });
    }
    const motionChange=()=>{if(reduced.matches&&playing&&!loading&&!failed)finish({focus:true,immediate:true});};
    reduced.addEventListener('change',motionChange);
    start();
    return {
      start,status:setStatus,ready,fail,cancel,
      onReady(fn){if(playing)readyCallbacks.push(fn);else fn();},
      get isLoading(){return loading;},
      viewChanged(name){
        if(name!=='home')home.classList.remove('jhome-revealed');
        else if(!playing)home.classList.add('jhome-revealed');
      }
    };
  }
  return {resolveView,consumeWelcome,setup};
});
