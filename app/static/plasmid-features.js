/* Imported GenBank features retain their disjoint segments and qualifiers. */
(function(root){
  'use strict';
  function segments(feature,length){
    const source=feature.segments?.length?feature.segments:[feature],result=[];
    for(const part of source){
      const start=+part.start,end=+part.end,strand=+(part.strand??feature.strand??0);
      if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||start>=length||end<=start)continue;
      if(end>length&&feature.wraps_origin){result.push({start,end:length,strand},{start:0,end:end%length,strand});}
      else if(end<=length)result.push({start,end,strand});
    }
    return result.filter(part=>part.end>part.start);
  }
  function name(feature){return String(feature.label||feature.qualifiers?.gene?.[0]||feature.type||'Feature');}
  function location(feature,length){
    if(feature.raw_location)return feature.raw_location;
    return segments(feature,length).map(p=>(p.strand===-1?'complement(':'')+(p.start+1)+(p.end-p.start>1?'..'+p.end:'')+(p.strand===-1?')':'')).join(', ');
  }
  function size(feature,length){return segments(feature,length).reduce((n,p)=>n+p.end-p.start,0);}
  function contains(feature,position,length){return segments(feature,length).some(p=>position>=p.start&&position<p.end);}
  function anchor(feature,length){const parts=segments(feature,length).sort((a,b)=>(b.end-b.start)-(a.end-a.start));return parts.length?(parts[0].start+parts[0].end)/2:0;}
  function color(feature,fallback){
    const q=feature.qualifiers||{},value=[q.color,q[feature.strand===-1?'ApEinfo_revcolor':'ApEinfo_fwdcolor']].flat().find(v=>typeof v==='string'&&/^#[\da-f]{6}$/i.test(v));
    return value||fallback;
  }
  function qualifiers(feature,compact=false){
    return Object.entries(feature.qualifiers||{}).filter(([key])=>key!=='label'&&!/color|ApEinfo_graphic/i.test(key)).map(([key,values])=>{
      let text=(Array.isArray(values)?values:[values]).map(v=>v===true?'Yes':String(v)).join('; ');
      if(compact&&key==='translation')text=text.replace(/\s/g,'').length+' aa';
      else if(compact&&text.length>240)text=text.slice(0,237)+'…';
      return[key,text];
    });
  }
  function lanes(features,length){
    const occupied=[],indices=[];
    for(const feature of features){
      const parts=segments(feature,length);let lane=occupied.findIndex(items=>!items.some(a=>parts.some(b=>a.start<b.end&&b.start<a.end)));
      if(lane<0){lane=occupied.length;occupied.push([]);}occupied[lane].push(...parts);indices.push(lane);
    }
    return {indices,count:Math.max(1,occupied.length)};
  }
  const api={segments,name,location,size,contains,anchor,color,qualifiers,lanes};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.PlasmidFeatures=api;
})(typeof globalThis==='object'?globalThis:this);
