/* Serialize private draft saves; never read another account's browser storage. */
(function(root){
  function create({request,capture,context,report=()=>{},delay=450}){
    let ready=false,timer=null,chain=Promise.resolve(),last=null;
    function encode(data=capture()){
      // Snapshot identity and content together, before this write is queued.
      const value={data};if(context)value.context_version=context();
      return JSON.stringify(value);
    }
    function schedule(){if(!ready)return;clearTimeout(timer);timer=setTimeout(()=>{flush().catch(report);},delay);}
    function write(persist){
      clearTimeout(timer);
      const encoded=encode();
      chain=chain.catch(()=>{}).then(async()=>{
        const snapshot=encoded===last?null:JSON.parse(encoded);
        const result=await persist(snapshot);
        last=encoded;
        return result;
      });
      return chain;
    }
    function flush(){
      if(!ready)return Promise.resolve();
      return write(snapshot=>snapshot?request('/api/workspace',snapshot):undefined);
    }
    return {schedule,flush,write,body:data=>JSON.parse(encode(data)),start(data){last=data===undefined?null:encode(data);ready=true;},stop(){ready=false;clearTimeout(timer);return chain;},get ready(){return ready;}};
  }
  if(typeof module==='object'&&module.exports)module.exports={create};else root.SandboxState={create};
})(typeof window==='object'?window:globalThis);
