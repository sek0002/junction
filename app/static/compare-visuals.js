(function(root){
  const perfect=m=>!!m&&m.exact===true&&m.identity===1&&(m.coverage===undefined||m.coverage===1)&&(m.reference_coverage===undefined||m.reference_coverage===1)&&(m.query_coverage===undefined||m.query_coverage===1);
  const recordsOf=job=>job?.result?.records||(job?.result?[job.result]:[]);
  const filePerfect=job=>job.status==='Done'&&recordsOf(job).length>0&&recordsOf(job).every(record=>!record.error&&record.matches?.some(perfect));
  function exportRecords(jobs,selection,scope){
    const fields=(object,keys)=>Object.fromEntries(keys.filter(key=>object[key]!==undefined).map(key=>[key,object[key]]));
    const output=[];
    for(const job of jobs){if(job.status!=='Done'||scope==='selected'&&!selection.has(job.id))continue;
      for(const record of recordsOf(job)){
        if(scope==='exact'&&(record.error||!record.matches?.some(perfect)))continue;
        output.push({filename:job.path,...fields(record,['query_name','query_length','query_circular','error','enzyme_detection']),
          matches:(record.matches||[]).map(match=>fields(match,['name','source','reference_length','identity','reference_coverage','query_coverage','aligned_bp','exact','orientation','rotation','changes','aliases'])),
          fragment_matches:(record.fragment_matches||[]).map(hit=>fields(hit,['name','plate_id','well','representation','query_spans','strand','identity','coverage','exact','status']))});
      }
    }
    return output;
  }
  const percent=m=>!m||!Number.isFinite(m.identity)?'—':!perfect(m)&&m.identity<1&&m.identity>=.99995?'>99.99%':(m.identity*100).toLocaleString(undefined,{maximumFractionDigits:2})+'%';
  function coverage(match){
    if(!match)return null;
    const bound=x=>Math.max(0,Math.min(1,x));
    if(Number.isFinite(match.reference_coverage))return bound(match.reference_coverage);
    if(Number.isFinite(match.coverage))return bound(match.coverage);
    const a=match.aligned_reference,b=match.aligned_query;
    if(typeof a==='string'&&typeof b==='string'&&a.length===b.length){let n=0,paired=0;for(let i=0;i<a.length;i++){if(a[i]!=='-'){n++;if(b[i]!=='-')paired++;}}return n?paired/n:null;}
    return perfect(match)?1:null;
  }
  const coveragePercent=match=>{const n=coverage(match);return n===null?'—':n<1&&n>=.99995?'>99.99%':(n*100).toLocaleString(undefined,{maximumFractionDigits:2})+'%';};
  const identityHue=match=>!Number.isFinite(match?.identity)?null:Math.round(Math.max(0,Math.min(1,(match.identity-.5)/.5))*120);
  const coverageHue=match=>{const n=coverage(match);return n===null?null:Math.round(Math.max(0,Math.min(1,(n-.5)/.5))*120);};
  const api={perfect,filePerfect,exportRecords,percent,coverage,coveragePercent,coverageHue,identityHue};if(typeof module==='object'&&module.exports)module.exports=api;else root.CompareVisuals=api;
})(typeof window==='object'?window:globalThis);
