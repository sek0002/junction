'use strict';
document.getElementById('login-form').onsubmit=async event=>{
  event.preventDefault();const button=document.getElementById('sign-in'),error=document.getElementById('login-error');
  button.disabled=true;error.hidden=true;
  try{
    const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value.trim(),pin:document.getElementById('pin').value})});
    if(!response.ok){const data=await response.json();throw Error(typeof data.detail==='string'?data.detail:'Enter a username and a 6–12 digit PIN.');}
    document.getElementById('pin').value='';location.replace('/#build');
  }catch(e){error.textContent=e.message||'Unable to sign in.';error.hidden=false;document.getElementById('pin').value='';}
  finally{button.disabled=false;}
};
