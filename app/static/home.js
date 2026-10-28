/* Home navigation and the one-time entrance after a successful sign-in. */
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
    const background=[doc.querySelector('.topbar'),doc.querySelector('main'),doc.querySelector('body > footer')].filter(Boolean);
    let timer=null,closing=null,playing=false;
    function finish({focus=false,immediate=false}={}){
      win.clearTimeout(timer);win.clearTimeout(closing);playing=false;
      background.forEach(node=>node.inert=false);
      intro.inert=true;intro.removeAttribute('aria-modal');
      intro.classList.add('home-intro-done');
      if(immediate||reduced.matches)intro.hidden=true;
      else closing=win.setTimeout(()=>{intro.hidden=true;},350);
      home.classList.add('jhome-revealed');
      if(focus&&home.classList.contains('active')){heading.focus({preventScroll:true});win.scrollTo({top:0,behavior:'auto'});}
    }
    function play(){
      if(!home.classList.contains('active')||reduced.matches){finish({immediate:true});return;}
      win.clearTimeout(closing);win.clearTimeout(timer);playing=true;
      intro.hidden=false;intro.inert=false;intro.setAttribute('aria-modal','true');
      intro.classList.remove('home-intro-done');home.classList.remove('jhome-revealed');
      background.forEach(node=>node.inert=true);
      for(const node of intro.querySelectorAll('.j-part,.splash-type,.intro-orbit,.intro-wordmark')){
        node.style.animation='none';void node.offsetWidth;node.style.animation='';
      }
      skip.focus({preventScroll:true});
      timer=win.setTimeout(()=>finish({focus:true}),1850);
    }
    skip.addEventListener('click',()=>finish({focus:true}));
    intro.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();finish({focus:true});}
      if(event.key==='Tab'){event.preventDefault();skip.focus();}
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
    const motionChange=()=>{if(reduced.matches&&playing)finish({focus:true,immediate:true});};
    reduced.addEventListener('change',motionChange);
    return {
      welcome(){if(consumeWelcome(win))play();else home.classList.add('jhome-revealed');win.scrollTo({top:0,behavior:'auto'});},
      viewChanged(name){
        if(name!=='home'){if(playing)finish({immediate:true});home.classList.remove('jhome-revealed');}
        else if(!playing)home.classList.add('jhome-revealed');
      }
    };
  }
  return {resolveView,consumeWelcome,setup};
});
