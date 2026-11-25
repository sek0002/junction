/* Serialize private draft saves; never read another account's browser storage. */
(function(root){
  function create({request,capture,context,partial=false,report=()=>{},delay=450}){
    let ready=false,timer=null,chain=Promise.resolve(),last=null;
    function encode(data=capture()){
      // Snapshot identity and content together, before this write is queued.
      const value={data};if(context)value.context_version=context();
      return JSON.stringify(value);
    }
    function changes(encoded){
      if(encoded===last)return null;
      const body=JSON.parse(encoded);
      if(!partial)return body;
      const previous=last?JSON.parse(last):null;
      if(previous&&previous.context_version===body.context_version){
        for(const key of Object.keys(body.data)){
          if(JSON.stringify(previous.data[key])===JSON.stringify(body.data[key]))delete body.data[key];
        }
      }
      return Object.keys(body.data).length?{...body,partial:true}:null;
    }
    // A tab can finish loading while an older save is in flight.
    function remember(data){
      const previous=last?JSON.parse(last).data:{};
      last=encode({...previous,...data});
    }
    function schedule(){if(!ready)return;clearTimeout(timer);timer=setTimeout(()=>{flush().catch(report);},delay);}
    function write(persist){
      clearTimeout(timer);
      const encoded=encode();
      chain=chain.catch(()=>{}).then(async()=>{
        const snapshot=changes(encoded);
        const result=await persist(snapshot);
        if(partial){if(snapshot)remember(snapshot.data);}else last=encoded;
        return result;
      });
      return chain;
    }
    function flush(){
      if(!ready)return Promise.resolve();
      return write(snapshot=>snapshot?request('/api/workspace',snapshot):undefined);
    }
    return {schedule,flush,write,adopt:remember,pendingBody:()=>changes(encode()),body:data=>JSON.parse(encode(data)),start(data){last=data===undefined?null:encode(data);ready=true;},stop(){ready=false;clearTimeout(timer);return chain;},get ready(){return ready;}};
  }
  if(typeof module==='object'&&module.exports)module.exports={create};else root.SandboxState={create};
})(typeof window==='object'?window:globalThis);
