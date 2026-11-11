(function(root){
  const perfect=m=>!!m&&m.exact===true&&m.identity===1&&(m.coverage===undefined||m.coverage===1)&&(m.reference_coverage===undefined||m.reference_coverage===1)&&(m.query_coverage===undefined||m.query_coverage===1);
  const recordsOf=job=>job?.result?.records||(job?.result?[job.result]:[]);
  const filePerfect=job=>job.status==='Done'&&recordsOf(job).length>0&&recordsOf(job).every(record=>!record.error&&record.matches?.some(perfect));
  const matchType=match=>perfect(match)?'exact':match?.adjusted_identity===1?'adjusted':null;
  function fileMatchType(job){
    if(filePerfect(job))return 'exact';
    const records=recordsOf(job);
    return job.status==='Done'&&records.length>0&&records.every(record=>!record.error&&record.matches?.some(matchType))?'adjusted':null;
  }
  const adjustmentFields=['adjusted_identity','adjusted_reference_coverage','adjusted_query_coverage','excluded_at_deletion_bp','excluded_at_deletion_events','excluded_at_deletion_spans','at_deletion_policy'];
  function exportRecords(jobs,selection,scope){
    const fields=(object,keys)=>Object.fromEntries(keys.filter(key=>object[key]!==undefined).map(key=>[key,object[key]]));
    const output=[];
    for(const job of jobs){if(job.status!=='Done'||scope==='selected'&&!selection.has(job.id))continue;
      for(const record of recordsOf(job)){
        if(scope==='exact'&&(record.error||!record.matches?.some(matchType)))continue;
        output.push({filename:job.path,...fields(record,['query_name','query_length','query_circular','error','enzyme_detection']),
          matches:(record.matches||[]).map(match=>fields(match,['name','source','reference_length','identity','reference_coverage','query_coverage','aligned_bp','exact','orientation','rotation','changes','aliases',...adjustmentFields])),
          fragment_matches:(record.fragment_matches||[]).map(hit=>fields(hit,['name','plate_id','well','representation','query_spans','strand','identity','coverage','exact','status',...adjustmentFields]))});
      }
    }
    return output;
  }
  const identity=(match,adjusted=true)=>adjusted&&Number.isFinite(match?.adjusted_identity)?match.adjusted_identity:match?.identity;
  const formatPercent=value=>!Number.isFinite(value)?'—':value<1&&value>=.99995?'>99.99%':(value*100).toLocaleString(undefined,{maximumFractionDigits:2})+'%';
  const percent=(match,adjusted=true)=>formatPercent(identity(match,adjusted));
  function coverage(match,adjusted=true){
    if(!match)return null;
    const bound=x=>Math.max(0,Math.min(1,x));
    if(adjusted&&Number.isFinite(match.adjusted_reference_coverage))return bound(match.adjusted_reference_coverage);
    if(Number.isFinite(match.reference_coverage))return bound(match.reference_coverage);
    if(Number.isFinite(match.coverage))return bound(match.coverage);
    const a=match.aligned_reference,b=match.aligned_query;
    if(typeof a==='string'&&typeof b==='string'&&a.length===b.length){let n=0,paired=0;for(let i=0;i<a.length;i++){if(a[i]!=='-'){n++;if(b[i]!=='-')paired++;}}return n?paired/n:null;}
    return perfect(match)?1:null;
  }
  const coveragePercent=(match,adjusted=true)=>formatPercent(coverage(match,adjusted));
  const identityHue=(match,adjusted=true)=>!Number.isFinite(identity(match,adjusted))?null:Math.round(Math.max(0,Math.min(1,(identity(match,adjusted)-.5)/.5))*120);
  const coverageHue=match=>{const n=coverage(match);return n===null?null:Math.round(Math.max(0,Math.min(1,(n-.5)/.5))*120);};
  function identityHtml(match){
    const number=(adjusted,label)=>{
      const hue=identityHue(match,adjusted),value=percent(match,adjusted);
      const tick=adjusted&&match?.adjusted_identity===1&&!perfect(match)?'<span class="exact-match-tick adjusted-match-tick" role="img" aria-label="100% adjusted identity" title="100% adjusted identity · A/T deletions excluded"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg></span>':'';
      return `<span class="compare-identity${hue===null?' is-unknown':''}" ${hue===null?'':`style="--identity-hue:${hue}"`} aria-label="${label} ${value}"><strong>${value}${tick}</strong><small>${label}</small></span>`;
    };
    const excluded=match?.excluded_at_deletion_bp||0;
    if(!excluded)return number(true,'identity');
    return `<span class="compare-adjusted-readout"><span class="compare-percentage-pair">${number(true,'Adjusted identity')}${number(false,'True identity')}</span><small class="compare-adjustment-note" title="Pure A or pure T deletions of at least 20 bases are excluded only from adjusted percentages">${excluded} A/T deletion bp excluded</small></span>`;
  }
  function coverageHtml(match){
    if(!match?.excluded_at_deletion_bp)return coveragePercent(match);
    return `<span class="compare-percentage-pair"><span>${coveragePercent(match)}<small>Adjusted coverage</small></span><span>${coveragePercent(match,false)}<small>True coverage</small></span></span>`;
  }
  const api={perfect,filePerfect,matchType,fileMatchType,exportRecords,identity,percent,coverage,coveragePercent,coverageHue,identityHue,identityHtml,coverageHtml};if(typeof module==='object'&&module.exports)module.exports=api;else root.CompareVisuals=api;
})(typeof window==='object'?window:globalThis);
