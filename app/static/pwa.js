/* Installation is optional. All scientific work remains on the same server. */
(function(root){
  function setup(win,doc){
    const button=doc.getElementById('install-app'),dialog=doc.getElementById('install-dialog'),message=doc.getElementById('install-message');
    if(!button||!dialog)return;
    const display=win.matchMedia('(display-mode: standalone)');
    let pending=null;
    const standalone=()=>display.matches||win.navigator.standalone===true;
    const sync=()=>{button.hidden=standalone();};
    sync();display.addEventListener?.('change',sync);
    function showGuide(text=''){
      message.textContent=text||(!win.isSecureContext?'Open Junction over HTTPS to install on this device.':'');
      message.classList.toggle('hidden',!message.textContent);
      if(!dialog.open)dialog.showModal();
    }
    win.addEventListener('beforeinstallprompt',event=>{event.preventDefault();pending=event;sync();});
    win.addEventListener('appinstalled',()=>{pending=null;button.hidden=true;if(dialog.open)dialog.close();});
    doc.getElementById('install-close').onclick=()=>dialog.close();
    button.onclick=async()=>{
      if(!pending){showGuide();return;}
      const prompt=pending;pending=null;
      try{
        await prompt.prompt();
        if((await prompt.userChoice).outcome==='accepted')button.hidden=true;
      }catch{showGuide('Use your browser’s install menu to add Junction.');}
    };
    if(win.isSecureContext&&'serviceWorker' in win.navigator){
      win.navigator.serviceWorker.register('/service-worker.js',{scope:'/',updateViaCache:'none'}).catch(()=>{});
    }
  }
  if(typeof module==='object'&&module.exports)module.exports={setup};
  else setup(root,root.document);
})(typeof window==='object'?window:globalThis);
