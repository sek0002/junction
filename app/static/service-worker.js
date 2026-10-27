/* Cache public presentation assets only. Inventory, uploads and plans are never cached. */
const CACHE_PREFIX='junction-static-';
const CACHE=CACHE_PREFIX+'v3';
const OFFLINE='/static/offline.html';
const PUBLIC_ASSETS=[OFFLINE,'/static/assets/junction-mark-v4.svg','/static/assets/junction-icon-v4-192.png','/static/assets/junction-icon-v4-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(PUBLIC_ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith(CACHE_PREFIX)&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url);
  if(url.origin!==self.location.origin)return;
  if(url.pathname.startsWith('/api/')){
    event.respondWith(fetch(request).catch(()=>new Response(JSON.stringify({detail:'Junction is offline. Reconnect to the server and retry.'}),{status:503,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
    return;
  }
  if(request.method!=='GET')return;
  if(request.mode==='navigate'){
    event.respondWith(fetch(request).catch(()=>caches.match(OFFLINE)));
  }else if(url.pathname.startsWith('/static/')){
    event.respondWith(fetch(request).then(async response=>{
      if(response.ok&&!response.redirected&&!/no-store/i.test(response.headers.get('Cache-Control')||'')){try{const cache=await caches.open(CACHE);await cache.put(request,response.clone());}catch{/* Cache storage is optional. */}}
      return response;
    }).catch(()=>caches.match(request)));
  }
});
