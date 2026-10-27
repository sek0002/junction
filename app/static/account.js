'use strict';
(()=>{
  const byId=id=>document.getElementById(id),dialog=byId('account-dialog');let currentUser=null;
  const originalFetch=window.fetch.bind(window);
  window.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href),local=url.origin===location.origin&&url.pathname.startsWith('/api/');
    if(local&&currentUser){const headers=new Headers(options.headers||(typeof input==='object'?input.headers:undefined));headers.set('X-Junction-User',String(currentUser.id));options={...options,headers};}
    const response=await originalFetch(input,options);
    if(local&&url.pathname!=='/api/auth/login'&&response.status===401)location.replace('/login');
    if(local&&response.headers.get('X-Junction-Account-Changed'))location.reload();
    return response;
  };
  const status=(message,error=false)=>{byId('account-status').textContent=message;byId('account-status').classList.toggle('auth-error',error);};
  async function request(url,body,method='POST'){
    const response=await fetch(url,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok){const result=await response.json();throw Error(typeof result.detail==='string'?result.detail:'Check the account details.');}
    return response.json();
  }
  const rights={can_upload:'Uploads',can_edit:'Edit library',can_archive:'Archive',can_manage_rules:'Default rules'};
  const node=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
  function acceptUser(user){
    currentUser=user;byId('account-open').setAttribute('aria-label','Account · '+user.username);byId('account-open').title='Account · '+user.username;
    byId('account-workspace').textContent=user.username+' · Personal sandbox';byId('admin-users').hidden=!user.is_admin;
    byId('account-rights').textContent=user.is_admin?'Admin · Full library access':Object.entries(rights).filter(([key])=>user[key]).map(([,label])=>label).join(' · ')||'Read-only library';
    window.dispatchEvent(new CustomEvent('junction-user',{detail:user}));
  }
  async function updateUser(user,changes){
    try{const saved=await request('/api/auth/users/'+user.id,changes,'PATCH');if(saved.id===currentUser.id){acceptUser(saved);if(!saved.is_admin)dialog.close();}await loadUsers();status('Account updated.');}
    catch(e){status(e.message,true);await loadUsers();}
  }
  let activityNext=null;
  async function loadActivity(append=false){
    const query=new URLSearchParams(),id=byId('activity-user').value;if(id)query.set('user_id',id);if(append&&activityNext)query.set('before',activityNext);
    try{const result=await request('/api/auth/activity?'+query);if(!append)byId('activity-body').replaceChildren();
      for(const item of result.items){const row=node('tr');for(const value of [new Date(item.created_at).toLocaleString(),item.username,item.action+' '+item.target,item.status])row.append(node('td',value));row.cells[0].dataset.sortValue=String(Date.parse(item.created_at));byId('activity-body').append(row);}
      activityNext=result.next;byId('activity-more').hidden=!activityNext;byId('activity-empty').hidden=!!byId('activity-body').children.length;
    }catch(e){status(e.message,true);}
  }
  async function loadUsers(){
    if(!currentUser?.is_admin)return;
    const users=await request('/api/auth/users?include_deleted='+byId('show-deleted-users').checked);byId('account-users').replaceChildren();
    const previous=byId('activity-user').value;byId('activity-user').replaceChildren(new Option('All users',''));for(const user of users)byId('activity-user').add(new Option(user.username+(user.deleted_at?' (deleted)':''),user.id));byId('activity-user').value=previous;
    for(const user of users){
      const row=node('article',undefined,'account-user'),heading=node('div',undefined,'account-user-heading'),info=node('div');info.append(node('b',user.username),node('small',(user.is_admin?'Admin':'User')+' · '+(user.deleted_at?'Deleted':user.active?'Active':'Disabled')));
      const controls=node('div',undefined,'button-row');
      const button=(text,handler)=>{const b=node('button',text,'secondary compact');b.type='button';b.onclick=handler;controls.append(b);return b;};
      button('Activity',()=>{byId('activity-user').value=String(user.id);byId('activity-section').open=true;loadActivity().then(()=>byId('activity-section').scrollIntoView({block:'start',behavior:'smooth'}));});
      if(user.deleted_at){button('Restore',async()=>{try{await request('/api/auth/users/'+user.id+'/restore',{});await loadUsers();status('Restored. Enable the account to allow sign-in.');}catch(e){status(e.message,true);}});}
      else{
        button('Reset PIN',()=>{byId('reset-user-id').value=user.id;byId('reset-user-name').textContent=user.username;byId('admin-new-pin').value='';byId('reset-pin-form').classList.remove('hidden');byId('admin-new-pin').focus();});
        const active=button(user.active?'Disable':'Enable',()=>updateUser(user,{active:!user.active}));active.disabled=user.id===currentUser.id;
        const remove=button('Delete',async()=>{if(remove.dataset.confirm!=='yes'){remove.dataset.confirm='yes';remove.textContent='Delete account?';return;}try{await request('/api/auth/users/'+user.id,{},'DELETE');await loadUsers();status('Account deleted. Its sandbox and activity are retained.');}catch(e){status(e.message,true);}});remove.classList.add('delete-user');remove.disabled=user.id===currentUser.id;
      }
      heading.append(info,controls);row.append(heading);
      if(!user.deleted_at){const permissions=node('div',undefined,'account-permissions'),label=node('label','Role'),role=node('select');role.setAttribute('aria-label','Role for '+user.username);role.add(new Option('User','user'));role.add(new Option('Admin','admin'));role.value=user.is_admin?'admin':'user';role.onchange=()=>updateUser(user,{is_admin:role.value==='admin'});label.append(role);permissions.append(label);
        for(const[key,text]of Object.entries(rights)){const l=node('label',undefined,'account-right'),check=node('input');check.type='checkbox';check.checked=user.is_admin||user[key];check.disabled=user.is_admin;check.setAttribute('aria-label',text+' for '+user.username);check.onchange=()=>updateUser(user,{[key]:check.checked});l.append(check,node('span',text));permissions.append(l);}row.append(permissions);}
      byId('account-users').append(row);
    }
  }
  byId('account-open').onclick=async()=>{status('');byId('change-pin-form').reset();byId('reset-pin-form').classList.add('hidden');dialog.showModal();try{const result=await request('/api/auth/session');acceptUser(result.user);if(currentUser.is_admin){await loadUsers();if(byId('activity-section').open)await loadActivity();}}catch(e){status(e.message,true);}};
  byId('account-close').onclick=()=>dialog.close();
  byId('logout').onclick=async()=>{try{await window.JunctionSandbox?.flush();await request('/api/auth/logout',{});location.replace('/login');}catch(e){status(e.message,true);}};
  byId('change-pin-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{if(byId('new-pin').value!==byId('confirm-pin').value)throw Error('New PINs do not match.');await window.JunctionSandbox?.flush();await request('/api/auth/pin',{current_pin:byId('current-pin').value,new_pin:byId('new-pin').value});event.target.reset();location.replace('/login');}catch(e){status(e.message,true);}finally{button.disabled=false;}};
  byId('create-user-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{const permissions=Object.fromEntries(Object.keys(rights).map(key=>[key,byId('new-'+key).checked]));await request('/api/auth/users',{username:byId('new-username').value.trim(),pin:byId('user-pin').value,is_admin:byId('new-user-role').value==='admin',...permissions});event.target.reset();await loadUsers();status('User created.');}catch(e){status(e.message,true);}finally{button.disabled=false;}};
  byId('reset-pin-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await window.JunctionSandbox?.flush();const id=Number(byId('reset-user-id').value);await request('/api/auth/users/'+id,{pin:byId('admin-new-pin').value},'PATCH');event.target.reset();event.target.classList.add('hidden');if(id===currentUser.id){location.replace('/login');return;}status('PIN reset.');}catch(e){status(e.message,true);}finally{button.disabled=false;}};
  byId('show-deleted-users').onchange=loadUsers;byId('activity-user').onchange=()=>loadActivity();byId('activity-refresh').onclick=()=>loadActivity();byId('activity-more').onclick=()=>loadActivity(true);byId('activity-section').ontoggle=()=>{if(byId('activity-section').open)loadActivity();};
  const ready=request('/api/auth/session').then(result=>{acceptUser(result.user);return result.user;});ready.catch(e=>status(e.message,true));
  window.JunctionAccount={ready,get user(){return currentUser;},allowed:right=>!!currentUser&&(currentUser.is_admin||currentUser[right])};
})();
