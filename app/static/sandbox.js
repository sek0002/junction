/* Serialize private draft saves; never read another account's browser storage. */
(function(root){
  function create({request,capture,report=()=>{},delay=450}){
    let ready=false,timer=null,pending=null,chain=Promise.resolve(),last=null;
    function schedule(){if(!ready)return;clearTimeout(timer);timer=setTimeout(()=>{pending=capture();flush().catch(report);},delay);}
    async function flush(){
      if(!ready)return;clearTimeout(timer);pending=capture();
      const snapshot=pending,encoded=JSON.stringify(snapshot);pending=null;
      if(encoded===last)return chain;
      chain=chain.catch(()=>{}).then(async()=>{await request('/api/workspace',{data:snapshot});last=encoded;});return chain;
    }
    return {schedule,flush,start(data){last=JSON.stringify(data);ready=true;},stop(){ready=false;clearTimeout(timer);},get ready(){return ready;}};
  }
  if(typeof module==='object'&&module.exports)module.exports={create};else root.SandboxState={create};
})(typeof window==='object'?window:globalThis);
