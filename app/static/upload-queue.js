/* Browser-local file queues; each file is validated and committed independently. */
(function(root){
  'use strict';
  function create({extensions,maxBytes=10*1024*1024,changed=()=>{}}){
    const jobs=[];let next=1,running=false;
    const key=file=>JSON.stringify([file.name,file.size,file.lastModified]);
    function add(files){
      let added=0;
      for(const file of files){
        if(jobs.some(job=>job.key===key(file)))continue;
        const extension=file.name.toLowerCase().split('.').pop();
        const error=!extensions.includes(extension)?'Unsupported file type':!file.size?'Empty file':file.size>maxBytes?'File exceeds the 10 MB limit':'';
        jobs.push({id:next++,key:key(file),file,status:error?'Error':'Queued',error,invalid:!!error,result:null,signature:null});added++;
      }
      changed();return added;
    }
    function remove(id){if(running)return false;const index=jobs.findIndex(job=>job.id===id);if(index<0)return false;jobs.splice(index,1);changed();return true;}
    function clear(){if(running)return false;jobs.splice(0);changed();return true;}
    function invalidate(){for(const job of jobs)if(job.status!=='Imported'&&!job.invalid){job.status='Queued';job.result=null;job.signature=null;job.error='';}changed();}
    async function run({preview=false,signature='',request,eligible=()=>true}){
      if(running)return false;
      // Snapshot the batch so a newly dropped file never joins an already running import.
      const batch=jobs.filter(job=>!job.invalid&&job.status!=='Imported'&&eligible(job)&&(!preview||job.status!=='Ready'||job.signature!==signature));
      running=true;changed();
      try{
        for(const job of batch){
          job.status=preview?'Previewing':'Importing';job.error='';changed();
          try{job.result=await request(job.file,job);job.signature=signature;job.status=preview?'Ready':'Imported';}
          catch(error){job.result=null;job.signature=null;job.error=error.message||'Upload failed';job.status='Error';}
          changed();
        }
      }finally{running=false;changed();}
      return true;
    }
    return{jobs,add,remove,clear,invalidate,run,get running(){return running;}};
  }
  function bindDrop(zone,input,add){
    let depth=0;
    input.addEventListener('change',()=>{add(Array.from(input.files||[]));input.value='';});
    zone.addEventListener('dragenter',event=>{event.preventDefault();depth++;zone.classList.add('drag-over');});
    zone.addEventListener('dragover',event=>{event.preventDefault();if(event.dataTransfer)event.dataTransfer.dropEffect='copy';});
    zone.addEventListener('dragleave',event=>{event.preventDefault();if(--depth<=0){depth=0;zone.classList.remove('drag-over');}});
    zone.addEventListener('drop',event=>{event.preventDefault();depth=0;zone.classList.remove('drag-over');add(Array.from(event.dataTransfer?.files||[]));});
  }
  const exported={create,bindDrop};
  if(typeof module==='object'&&module.exports)module.exports=exported;else root.JunctionUploadQueue=exported;
})(typeof window!=='undefined'?window:globalThis);
