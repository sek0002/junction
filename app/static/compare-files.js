/* Display-only filtering/sorting never changes comparison processing order. */
(function(root,factory){
  const api=factory(typeof module==='object'&&module.exports?require('./compare-visuals.js'):root.CompareVisuals);
  if(typeof module==='object'&&module.exports)module.exports=api;else root.CompareFiles=api;
})(typeof globalThis==='object'?globalThis:this,visuals=>{
  const collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
  const records=job=>job?.result?.records||(job?.result?[job.result]:[]);
  const record=job=>records(job)[job.recordIndex]||records(job)[0];
  const normalize=value=>String(value??'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  function searchable(job){return normalize([job.path,job.file?.name,job.status,job.error,...records(job).flatMap(r=>[r.query_name,r.error,...(r.matches||[]).flatMap(m=>[m.name,m.source,...(m.aliases||[]).map(a=>a.name)]),...(r.fragment_matches||[]).map(f=>f.name)])].filter(Boolean).join(' '));}
  function matches(job,filter,selection){
    const rs=records(job),valid=rs.filter(r=>!r.error);
    if(filter==='exact')return visuals.filePerfect(job);
    if(filter==='differences')return job.status==='Done'&&!visuals.filePerfect(job)&&valid.some(r=>r.matches?.length);
    if(filter==='no-matches')return job.status==='Done'&&valid.length>0&&valid.every(r=>!r.matches?.length);
    if(filter==='errors')return job.status==='Error'||rs.some(r=>r.error);
    if(filter==='selected')return selection.has(job.id);
    return !filter||filter==='all'||job.status.toLowerCase()===filter;
  }
  function value(job,key){
    const r=record(job),best=r?.matches?.[0];
    if(key==='file')return job.path;
    if(key==='status')return ['Queued','Comparing','Done','Error','Skipped'].indexOf(job.status);
    if(key==='match')return best?.name??null;
    if(key==='identity')return best?.identity??null;
    if(key==='fragments')return job.status==='Done'&&r&&!r.error?(r.fragment_matches?.length||0):null;
    return null;
  }
  function compare(a,b,direction=1){
    if(a===null||a===undefined||a==='')return b===null||b===undefined||b===''?0:1;
    if(b===null||b===undefined||b==='')return -1;
    return direction*(typeof a==='number'&&typeof b==='number'?a-b:collator.compare(String(a),String(b)));
  }
  function select(jobs,view={},selection=new Set()){
    const terms=normalize(view.search).trim().split(/\s+/).filter(Boolean);
    const visible=jobs.filter(job=>matches(job,view.filter,selection)&&(!terms.length||terms.every(term=>searchable(job).includes(term))));
    if(view.sort)visible.sort((a,b)=>compare(value(a,view.sort),value(b,view.sort),view.direction||1)||jobs.indexOf(a)-jobs.indexOf(b));
    return visible;
  }
  function selectVisible(selection,jobs,checked){for(const job of jobs)if(job.status==='Done')checked?selection.add(job.id):selection.delete(job.id);}
  return{select,value,compare,records,record,selectVisible};
});
