'use strict';
(()=>{
  const selectors={
    can_upload:'#commit-upload,#import-plasmid,#save-assembly,#save-backbone',
    can_edit:'#inventory-body input:not([type=checkbox]),#inventory-body [data-yield-lock],#inventory-body [data-record-reset],#reset-inventory,#apply-inventory-rules,[data-plasmid-name],[data-topology],[data-backbone],[data-save-plasmid]',
    can_archive:'#archive-fragments,#archive-plates,#restore-bin,[data-archive-plasmids]',
    can_manage_rules:'#inventory-rules-form input,#inventory-rules-form button'
  };
  const locked=new WeakSet();let queued=false;
  function apply(){queued=false;if(!window.JunctionAccount?.user)return;
    for(const[right,selector]of Object.entries(selectors))for(const el of document.querySelectorAll(selector)){
      const allowed=window.JunctionAccount.allowed(right);
      if(!allowed){if(!el.disabled){el.disabled=true;locked.add(el);}if(!el.classList.contains('permission-limited'))el.classList.add('permission-limited');}
      else {if(locked.has(el)){locked.delete(el);el.disabled=false;}el.classList.remove('permission-limited');}
    }
  }
  const schedule=()=>{if(!queued){queued=true;requestAnimationFrame(apply);}};
  window.addEventListener('junction-user',schedule);new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});schedule();
})();
