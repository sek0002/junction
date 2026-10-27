/* Both sequence rows share reference coordinates. Original upload coordinates
   remain available in hover details after query orientation and rotation. */
(function(root){
  const escape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const kind=(a,b)=>a===b?null:a==='-'?'insertion':b==='-'?'deletion':'substitution';
  const names={substitution:'Substitution',insertion:'Insertion',deletion:'Deletion'};
  const span=(a,b)=>a===b?'gap after '+a:`${a+1}–${b}`;
  // NEB recognition specificities: BsaI/BsmBI (1/5), BbsI (2/6), HindIII A/AGCTT.
  const enzymes={BsaI:{motifs:['GGTCTC','GAGACC'],offset:1,color:'var(--site-bsai)'},BsmBI:{motifs:['CGTCTC','GAGACG'],offset:1,color:'var(--site-bsmbi)'},BbsI:{motifs:['GAAGAC','GTCTTC'],offset:2,color:'var(--site-bbsi)'},HindIII:{motifs:['AAGCTT'],offset:0,color:'var(--site-hindiii)'}};
  const modulo=(value,n)=>(value%n+n)%n;
  function enzymeFor(feature){
    const label=String(feature.label||'').trim(),explicit=feature.enzyme||/restriction[_ ]site/i.test(feature.type||'');
    if(!explicit&&!/^(BsaI|BsmBI|Esp3I|BbsI|BpiI|HindIII)(?:\s+(?:recognition |restriction |cut )?site)?(?:\s*[·:]\s*\d.*)?$/i.test(label))return null;
    const text=[feature.enzyme,label,...(feature.qualifiers?.label||[]),...(feature.qualifiers?.note||[])].filter(Boolean).join(' ');
    return Object.keys(enzymes).find(name=>new RegExp('\\b'+name+'\\b','i').test(text))||(/\bEsp3I\b/i.test(text)?'BsmBI':/\bBpiI\b/i.test(text)?'BbsI':null);
  }
  function restrictionSites(sequence,circular=false){
    sequence=String(sequence).toUpperCase();const n=sequence.length,search=sequence+(circular&&n>=6?sequence.slice(0,5):''),sites=[];
    for(const[enzyme,spec]of Object.entries(enzymes))for(const[m,motif]of spec.motifs.entries()){
      let start=search.indexOf(motif);
      while(start>=0&&start<n){
        const strand=m===0?1:-1,rawTop=enzyme==='HindIII'?start+1:strand===1?start+6+spec.offset:start-spec.offset-4;
        const rawBottom=rawTop+4,cut=value=>circular?modulo(value,n):value>=0&&value<=n?value:null;
        const overhang=circular?Array.from({length:4},(_,i)=>sequence[modulo(rawTop+i,n)]).join(''):rawTop>=0&&rawBottom<=n?sequence.slice(rawTop,rawBottom):'';
        sites.push({enzyme,motif,start,end:start+6,strand,topCut:cut(rawTop),bottomCut:cut(rawBottom),overhang,wrapsOrigin:start+6>n,rawTop,rawBottom});
        start=search.indexOf(motif,start+1);
      }
    }
    return sites.sort((a,b)=>a.start-b.start||a.enzyme.localeCompare(b.enzyme)).map((site,index)=>({...site,index}));
  }
  function originalSpans(start,end,queryLength,rotation,orientation,circular=true){
    if(!queryLength)return [];
    if(start===end){const at=!circular&&!rotation?start:(start+rotation)%queryLength;return [[orientation==='-'?queryLength-at:at,orientation==='-'?queryLength-at:at]];}
    let at=(start+rotation)%queryLength,remaining=end-start;const parts=[];
    while(remaining>0){const size=Math.min(remaining,queryLength-at);parts.push(orientation==='-'?[queryLength-at-size,queryLength-at]:[at,at+size]);remaining-=size;at=0;}
    return parts;
  }
  function build(match){
    const reference=String(match.aligned_reference||match.sequence||''),query=String(match.aligned_query||(match.exact?reference:''));
    if(reference.length!==query.length||!reference.length)throw Error('Aligned sequences are unavailable.');
    const refBefore=new Int32Array(reference.length+1),queryBefore=new Int32Array(reference.length+1),referenceColumns=[],queryColumns=[];const changes=[];
    let current=null;
    for(let i=0;i<reference.length;i++){
      const a=reference[i],b=query[i],type=kind(a,b);refBefore[i+1]=refBefore[i]+(a!=='-');queryBefore[i+1]=queryBefore[i]+(b!=='-');
      if(a!=='-')referenceColumns.push(i);
      if(b!=='-')queryColumns.push(i);
      if(current&&type!==current.type){changes.push(current);current=null;}
      if(type&&!current)current={index:changes.length,type,startColumn:i,endColumn:i,reference_start:refBefore[i],reference_end:refBefore[i],query_start:queryBefore[i],query_end:queryBefore[i],reference_bases:'',query_bases:''};
      if(current){current.endColumn=i+1;current.reference_end=refBefore[i+1];current.query_end=queryBefore[i+1];if(a!=='-')current.reference_bases+=a;if(b!=='-')current.query_bases+=b;}
    }
    if(current)changes.push(current);
    referenceColumns.push(reference.length);
    queryColumns.push(reference.length);
    const n=queryBefore[query.length],rotation=n?((Number(match.rotation)||0)%n+n)%n:0,orientation=match.orientation==='-'?'-':'+';
    for(const change of changes)change.original_query_spans=originalSpans(change.query_start,change.query_end,n,rotation,orientation,match.circular!==false);
    const circular=match.circular!==false,refSites=restrictionSites(reference.replace(/-/g,''),circular),querySites=restrictionSites(query.replace(/-/g,''),circular);
    const features=(match.features||[]).filter(f=>f.type!=='source'&&Number.isFinite(f.start)&&Number.isFinite(f.end)&&f.end>f.start);
    for(const site of refSites)if(!features.some(f=>enzymeFor(f)===site.enzyme&&f.start===site.start))features.push({...site,type:'restriction_site',label:site.enzyme,autoRestriction:true,_siteSide:'reference',_siteIndex:site.index});
    const model={reference,query,refBefore,queryBefore,referenceColumns,queryColumns,changes,referenceLength:refBefore[reference.length],queryLength:n,columns:reference.length,rotation,orientation,circular,features,refSites,querySites};
    for(const site of refSites)site.shared=querySites.some(q=>q.enzyme===site.enzyme&&q.strand===site.strand&&refBefore[queryColumns[q.start]]===site.start);
    for(const site of querySites)site.shared=refSites.some(r=>r.enzyme===site.enzyme&&r.strand===site.strand&&r.start===refBefore[queryColumns[site.start]]);
    for(const site of querySites.filter(s=>!s.shared)){
      const segments=featureSpans(site,n).map(([a,b])=>({start:refBefore[queryColumns[a]],end:refBefore[queryColumns[b]]}));
      features.push({...site,start:segments[0].start,end:Math.max(...segments.map(s=>s.end)),segments,type:'restriction_site',label:site.enzyme+' · query only',autoRestriction:true,_siteSide:'query',_siteIndex:site.index});
    }
    return model;
  }
  function featureSpans(feature,length){
    if(!length)return [];
    if(feature.segments?.length)return feature.segments.flatMap(segment=>featureSpans(segment,length));
    const a=((feature.start%length)+length)%length,size=Math.min(length,feature.end-feature.start);
    return a+size>length?[[a,length],[0,a+size-length]]:[[a,a+size]];
  }
  function affected(model,change){
    if(!change)return [];
    return model.features.filter(feature=>featureSpans(feature,model.referenceLength).some(([a,b])=>change.reference_start===change.reference_end?
      a<=change.reference_start&&change.reference_start<=b||model.circular&&(change.reference_start===0||change.reference_start===model.referenceLength)&&(a===0||b===model.referenceLength):a<change.reference_end&&b>change.reference_start));
  }
  function startFor(model,center,size){return clamp(Math.round(center-size/2),0,Math.max(0,model.columns-size));}
  function windowRange(model,start,size){
    const count=Math.min(model.columns,Math.max(1,Math.round(size))),half=Math.floor(count/2);
    start=clamp(Math.round(start),0,model.columns-count);
    return {start,end:start+count,sliderMin:half,sliderMax:model.columns-count+half,sliderValue:start+half};
  }
  function columnForReference(model,position){return model.referenceColumns[clamp(Math.round(position),0,model.referenceLength)]??0;}
  function label(change){return `${change.index+1} · ${names[change.type]} · Ref ${span(change.reference_start,change.reference_end)}`;}
  function queryPosition(model,orientedPosition){const pos=(orientedPosition+model.rotation)%model.queryLength;return model.orientation==='-'?model.queryLength-pos:pos+1;}
  function originalQueryLabel(model,start,end){
    return originalSpans(start,end,model.queryLength,model.rotation,model.orientation,model.circular).map(([a,b])=>a===b?`gap after ${a}`:model.orientation==='-'?`${b}→${a+1}`:`${a+1}–${b}`).join(' / ');
  }
  function coordinateRuler(model,start,end){
    const ticks=[];
    for(let i=start;i<end;i++)if(model.reference[i]!=='-'&&(ticks.length===0||(model.refBefore[i]+1)%10===1))ticks.push({column:i,position:model.refBefore[i]+1});
    let last=end-1;while(last>=start&&model.reference[last]==='-')last--;
    if(last>=start&&(!ticks.length||last-ticks[ticks.length-1].column>=5))ticks.push({column:last,position:model.refBefore[last]+1});
    return `<div class="diff-sequence-row diff-coordinate-row"><span class="diff-sequence-label">Position</span><div class="diff-coordinate-axis" style="width:${(end-start)*cellWidth}px" aria-label="Reference coordinates shared by both sequences">${ticks.map(tick=>`<span class="diff-coordinate-tick" data-reference-position="${tick.position}" style="left:${(tick.column-start)*cellWidth+cellWidth/2}px">${tick.position.toLocaleString()}</span>`).join('')}</div></div>`;
  }
  function rangeText(start,end,length){return end>length?`${start+1}–${end%length} · across origin`:span(start,end);}
  function featuresAt(model,start,end){return affected(model,{reference_start:start,reference_end:end});}
  function featuresForSite(model,side,site){
    const found=new Set(),length=side==='query'?model.queryLength:model.referenceLength;
    for(const[a,b]of featureSpans(site,length)){
      const start=model.refBefore[siteColumn(model,side,a)],end=model.refBefore[siteColumn(model,side,b)];
      for(const feature of featuresAt(model,start,end))found.add(feature);
    }
    return model.features.filter(f=>found.has(f));
  }
  function featureList(features){return features.length?`<ul class="diff-hover-features">${features.slice(0,7).map(f=>`<li${enzymeFor(f)?` style="color:${enzymes[enzymeFor(f)].color}"`:''}>${escape(f.label||f.type)}</li>`).join('')}${features.length>7?`<li>+${features.length-7} more</li>`:''}</ul>`:'<small>No annotated feature</small>';}
  function hoverHtml(model,type,index,side='reference'){
    if(type==='feature'){
      const f=model.features[index];if(!f)return '';if(f.autoRestriction)return hoverHtml(model,'site',f._siteIndex,f._siteSide);const enzyme=enzymeFor(f),ranges=featureSpans(f,model.referenceLength);
      return `<strong${enzyme?` style="color:${enzymes[enzyme].color}"`:''}>${escape(f.label||f.type)}</strong><small>${escape(f.type||'Feature')} · ${f.strand===-1?'Reverse strand':f.strand===1?'Forward strand':'Strand unspecified'}</small><dl><dt>Reference</dt><dd>${ranges.map(x=>span(...x)).join(' / ')}</dd><dt>Length</dt><dd>${ranges.reduce((sum,[a,b])=>sum+b-a,0)} bp</dd></dl>${enzyme?`<small class="diff-hover-hint">${enzyme} restriction feature · click to inspect sequence</small>`:'<small class="diff-hover-hint">Click to inspect sequence</small>'}`;
    }
    if(type==='change'){
      const c=model.changes[index];if(!c)return '';
      return `<strong class="diff-kind-${c.type}">${names[c.type]} · ${Math.max(c.reference_bases.length,c.query_bases.length)} bp</strong><dl><dt>Reference</dt><dd>${span(c.reference_start,c.reference_end)}</dd><dt>Original query</dt><dd>${originalQueryLabel(model,c.query_start,c.query_end)}</dd></dl><div class="diff-hover-change"><code>${escape(c.reference_bases.slice(0,60)||'—')}${c.reference_bases.length>60?'…':''}</code><span>→</span><code>${escape(c.query_bases.slice(0,60)||'—')}${c.query_bases.length>60?'…':''}</code></div><small>Affected features</small>${featureList(affected(model,c))}<small class="diff-hover-hint">Click to focus this difference</small>`;
    }
    if(type==='site'){
      const site=(side==='query'?model.querySites:model.refSites)[index];if(!site)return '';const length=side==='query'?model.queryLength:model.referenceLength;
      const bond=(value,n)=>value===0?model.circular?`between ${n} / 1 (origin)`:'before base 1':`after base ${value}`;
      const cutText=value=>value===null?'Outside linear sequence':bond(value,length)+(side==='query'?` · original ${bond(originalSpans(value,value,model.queryLength,model.rotation,model.orientation,model.circular)[0][0],model.queryLength)}`:'');
      const original=side==='query'?originalQueryLabel(model,site.start,site.end):'';
      return `<strong style="color:${enzymes[site.enzyme].color}">${site.enzyme} · ${side==='query'?'Query':'Reference'}</strong><small>${site.shared?'Present in both sequences':side==='query'?'Query only':'Reference only'} · ${site.strand===1?'Forward':'Reverse'} recognition</small><dl><dt>Recognition</dt><dd><code>${site.motif}</code> · ${rangeText(site.start,site.end,length)}</dd>${original?`<dt>Original query</dt><dd>${original}</dd>`:''}<dt>Top cut ┃</dt><dd>${cutText(site.topCut)}</dd><dt>Bottom cut ┆</dt><dd>${cutText(site.bottomCut)}</dd><dt>5′ overhang</dt><dd><code>${site.overhang||'Outside linear sequence'}</code></dd></dl><small>Features at this site</small>${featureList(featuresForSite(model,side,site))}<small class="diff-hover-hint">Cuts use the displayed aligned strand · click to inspect</small>`;
    }
    if(type==='base'){
      const i=Number(index),position=side==='query'?model.queryBefore[i]:model.refBefore[i],letter=(side==='query'?model.query:model.reference)[i];
      const list=(side==='query'?model.querySites:model.refSites).filter(s=>featureSpans(s,side==='query'?model.queryLength:model.referenceLength).some(([a,b])=>a<=position&&position<b));
      const aligned=model.reference[i]==='-'?`gap after ${model.refBefore[i]}`:`base ${model.refBefore[i]+1}`;
      return `<strong>Reference ${aligned} · ${escape(letter)}</strong><small>${side==='query'?`${model.orientation==='-'?'Reverse-complement query':'Query'} · original ${letter==='-'?originalQueryLabel(model,position,position):'base '+queryPosition(model,position)}`:'Reference strand'}</small>${featureList(featuresAt(model,model.refBefore[i],model.refBefore[i]+(model.reference[i]==='-'?0:1)))}${list.length?`<small>Recognition sites</small><div class="diff-hover-enzymes">${list.map(s=>`<b style="color:${enzymes[s.enzyme].color}">${s.enzyme}</b>`).join(' · ')}</div>`:''}`;
    }
    return '';
  }
  function sequenceDecoration(model,side,position,letter){
    if(letter==='-')return {classes:'',style:'',site:null};
    const length=side==='query'?model.queryLength:model.referenceLength,sites=side==='query'?model.querySites:model.refSites;
    const motif=sites.find(s=>featureSpans(s,length).some(([a,b])=>a<=position&&position<b));
    const endTop=!model.circular&&position===length-1&&sites.find(s=>s.topCut===length),endBottom=!model.circular&&position===length-1&&sites.find(s=>s.bottomCut===length);
    const top=sites.find(s=>s.topCut===position)||endTop,bottom=sites.find(s=>s.bottomCut===position)||endBottom;
    return {classes:(motif?' diff-re-base':'')+(top?' diff-cut-top':'')+(bottom?' diff-cut-bottom':'')+(endTop?' diff-cut-end-top':'')+(endBottom?' diff-cut-end-bottom':''),
      site:motif||top||bottom||null,style:[motif?`--re-color:${enzymes[motif.enzyme].color}`:'',top?`--cut-top-color:${enzymes[top.enzyme].color}`:'',bottom?`--cut-bottom-color:${enzymes[bottom.enzyme].color}`:''].filter(Boolean).join(';')};
  }
  function siteColumn(model,side,position){return (side==='query'?model.queryColumns:model.referenceColumns)[position]??model.columns;}
  function siteEndColumn(model,side,position){return position>0?siteColumn(model,side,position-1)+1:0;}
  const cellWidth=12;
  function featureColor(feature,index){
    const q=feature.qualifiers||{},color=[feature.color,q.color,q[feature.strand===-1?'ApEinfo_revcolor':'ApEinfo_fwdcolor']].flat().find(value=>typeof value==='string'&&/^#[a-f0-9]{6}$/i.test(value));
    return color||`var(--feature-${index%8})`;
  }
  function featureLayout(parts){
    const ends=[];
    parts.sort((a,b)=>a.start-b.start||b.end-a.end);
    for(const part of parts){let lane=ends.findIndex(end=>end<=part.start);if(lane<0)lane=ends.length;ends[lane]=part.end;part.lane=lane;}
    return {parts,height:Math.max(1,ends.length)*6+4};
  }
  function annotationParts(model,start=0,end=model.columns,aligned=true){
    const parts=[];
    model.features.forEach((feature,index)=>{
      if(enzymeFor(feature))return;
      for(const[a,b]of featureSpans(feature,model.referenceLength)){
        const left=aligned?columnForReference(model,a):a,right=aligned?siteEndColumn(model,'reference',b):b;
        if(right>start&&left<end)parts.push({start:Math.max(start,left),end:Math.min(end,right),feature,index});
      }
    });
    return featureLayout(parts);
  }
  function featureSubtrack(model,offset,stop){
    const layout=annotationParts(model,offset,stop);
    if(!layout.parts.length)return '';
    return `<div class="diff-sequence-row diff-feature-subtrack"><span class="diff-sequence-label">Features</span><div class="diff-local-features" style="width:${(stop-offset)*cellWidth}px;height:${layout.height}px">${layout.parts.map(part=>`<button class="diff-local-feature" data-diff-feature="${part.index}" style="left:${(part.start-offset)*cellWidth}px;width:${(part.end-part.start)*cellWidth}px;top:${part.lane*6+2}px;--feature-color:${featureColor(part.feature,part.index)}" aria-describedby="diff-hover-tooltip" aria-label="View feature ${escape(part.feature.label||part.feature.type)}"></button>`).join('')}</div></div>`;
  }
  function cutSpans(site,length,circular){
    if(site.topCut===null||site.bottomCut===null)return [];
    const end=site.topCut+4;
    return circular&&end>length?[{start:site.topCut,end:length,top:true,bottom:false},{start:0,end:end-length,top:false,bottom:true}]:[{start:site.topCut,end:site.bottomCut===0&&end===length?length:site.bottomCut,top:true,bottom:true}];
  }
  function siteOverlay(model,side,offset,stop){
    const sites=side==='query'?model.querySites:model.refSites,length=side==='query'?model.queryLength:model.referenceLength;
    let groups='';
    for(const site of sites){
      let marks='';
      for(const[a,b]of featureSpans(site,length)){
        const left=Math.max(offset,siteColumn(model,side,a)),right=Math.min(stop,siteEndColumn(model,side,b));
        if(right>left)marks+=`<rect class="diff-site-motif" x="${(left-offset)*cellWidth}" y="2" width="${(right-left)*cellWidth}" height="20" rx="2"/>`;
      }
      const gapStart=site.strand===1?site.end:site.rawBottom,gapEnd=site.strand===1?site.rawTop:site.start;
      if(site.enzyme!=='HindIII'&&gapEnd>gapStart&&(model.circular||gapStart>=0&&gapEnd<=length))for(const[a,b]of featureSpans({start:gapStart,end:gapEnd},length)){
        const from=site.strand===1&&a>0&&a===modulo(gapStart,length)?siteEndColumn(model,side,a):siteColumn(model,side,a);
        const left=Math.max(offset,from),right=Math.min(stop,siteColumn(model,side,b));
        if(right>left)marks+=`<path class="diff-site-leader" d="M${(left-offset)*cellWidth} 22H${(right-offset)*cellWidth}"/>`;
      }
      for(const segment of cutSpans(site,length,model.circular)){
        const a=siteColumn(model,side,segment.start),b=siteColumn(model,side,segment.end);
        if(b<offset||a>stop)continue;
        const x1=(Math.max(offset,a)-offset)*cellWidth,x2=(Math.min(stop,b)-offset)*cellWidth;
        const top=segment.top&&a>=offset&&a<=stop,bottom=segment.bottom&&b>=offset&&b<=stop;
        if(x2>x1)marks+=`<path class="diff-cut-bridge" data-diff-cut-span="${a}:${b}" d="M${x1} 28H${x2}"/>`;
        if(top)marks+=`<path class="diff-cut-top-line" data-diff-cut-top="${a}" d="M${x1} 0V28"/>`;
        if(bottom)marks+=`<path class="diff-cut-bottom-line" data-diff-cut-bottom="${b}" d="M${x2} 15V28"/>`;
      }
      // Incomplete linear sites retain each valid nick without inventing an outside cut.
      if(site.topCut===null||site.bottomCut===null)for(const[key,cls,y]of [['topCut','top',0],['bottomCut','bottom',15]]){
        if(site[key]===null)continue;const column=siteColumn(model,side,site[key]);
        if(column>=offset&&column<=stop)marks+=`<path class="diff-cut-${cls}-line" data-diff-cut-${cls}="${column}" d="M${(column-offset)*cellWidth} ${y}V28"/>`;
      }
      if(marks)groups+=`<g data-diff-site="${site.index}" data-diff-side="${side}" style="--re-color:${enzymes[site.enzyme].color}" tabindex="0" role="button" aria-label="${site.enzyme} ${side} site" aria-describedby="diff-hover-tooltip">${marks}</g>`;
    }
    return `<svg class="diff-site-overlay" viewBox="0 0 ${(stop-offset)*cellWidth} 32" width="${(stop-offset)*cellWidth}" height="32">${groups}</svg>`;
  }
  function windowHtml(model,start,size,selectedIndex){
    const range=windowRange(model,start,size);start=range.start;const end=range.end,selected=model.changes[selectedIndex];let html='';
    {
      const offset=start,stop=end;
      let ref='',qry='',bars='';
      for(let i=offset;i<stop;i++){
        const a=model.reference[i],b=model.query[i],type=kind(a,b),active=selected&&i>=selected.startColumn&&i<selected.endColumn;
        const cls='diff-base'+(type?' change-'+type:'')+(active?' diff-selected-base':'');
        const rtitle=a==='-'?`Reference gap after ${model.refBefore[i]}`:`Reference base ${model.refBefore[i]+1}`;
        const qtitle=(model.reference[i]==='-'?`Reference gap after ${model.refBefore[i]}`:`Reference base ${model.refBefore[i]+1}`)+' · '+(b==='-'?'Query '+originalQueryLabel(model,model.queryBefore[i],model.queryBefore[i]):`Original query base ${queryPosition(model,model.queryBefore[i])}${model.orientation==='-'?' · reverse complement':''}`);
        const rd=sequenceDecoration(model,'reference',model.refBefore[i],a),qd=sequenceDecoration(model,'query',model.queryBefore[i],b),change=type?model.changes.find(c=>c.startColumn<=i&&i<c.endColumn):null;
        const attributes=side=>{const decoration=side==='query'?qd:rd;return `data-diff-column="${i}" data-diff-base="${i}" data-diff-side="${side}"${change?` data-diff-change="${change.index}"`:decoration.site?` data-diff-site="${decoration.site.index}"`:''} aria-describedby="diff-hover-tooltip"`;};
        ref+=`<span class="${cls}${rd.classes}" style="${rd.style}" ${attributes('reference')} aria-label="${rtitle}">${escape(a)}</span>`;qry+=`<span class="${cls}${qd.classes}" style="${qd.style}" ${attributes('query')} aria-label="${qtitle}">${escape(b)}</span>`;
        bars+=`<span class="diff-match-base${type?' change-'+type:' diff-match-equal'}" data-diff-column="${i}" aria-hidden="true">${type==='substitution'?'·':''}</span>`;
      }
      html+=`<div class="diff-sequence-block" data-diff-start="${offset}" data-diff-end="${stop}" style="--diff-columns:${stop-offset}">${coordinateRuler(model,offset,stop)}${featureSubtrack(model,offset,stop)}<div class="diff-sequence-row diff-strand-row"><div class="diff-sequence-label">Reference</div><div class="diff-base-track"><div class="diff-bases">${ref}</div>${siteOverlay(model,'reference',offset,stop)}</div></div><div class="diff-sequence-row diff-match-row"><span></span><div class="diff-bases">${bars}</div></div><div class="diff-sequence-row diff-strand-row"><div class="diff-sequence-label">Query${model.orientation==='-'?' (RC)':''}</div><div class="diff-base-track"><div class="diff-bases">${qry}</div>${siteOverlay(model,'query',offset,stop)}</div></div></div>`;
    }
    return html;
  }
  function overviewHtml(model,selectedIndex,filter,start,size){
    const n=Math.max(1,model.referenceLength),left=100*model.refBefore[start]/n,right=100*model.refBefore[Math.min(model.columns,start+size)]/n;
    const layout=annotationParts(model,0,n,false);
    let html=`<div class="diff-overview-axis"><span></span><div><span>1</span><span>${n.toLocaleString()} bp</span></div></div><div class="diff-overview-row"><span class="diff-lane-label">Features</span><div class="diff-lane diff-feature-lane diff-feature-compact" data-diff-track style="height:${layout.height}px">`;
    for(const part of layout.parts)html+=`<button class="diff-feature diff-annotation-feature" data-diff-feature="${part.index}" style="left:${100*part.start/n}%;width:${100*(part.end-part.start)/n}%;top:${part.lane*6+2}px;--feature-color:${featureColor(part.feature,part.index)}" aria-describedby="diff-hover-tooltip" aria-label="View feature ${escape(part.feature.label||part.feature.type)}"></button>`;
    html+='</div></div><div class="diff-overview-row"><span class="diff-lane-label">Sites</span><div class="diff-lane diff-site-lane" data-diff-track>';
    model.features.forEach((feature,index)=>{const enzyme=enzymeFor(feature);if(!enzyme)return;for(const[a,b]of featureSpans(feature,n))html+=`<button class="diff-feature diff-feature-re" data-diff-feature="${index}" style="left:clamp(0px,${100*a/n}%,calc(100% - 3px));width:max(3px,${100*(b-a)/n}%);--re-color:${enzymes[enzyme].color}" aria-describedby="diff-hover-tooltip" aria-label="View ${enzyme} site"></button>`;});
    html+='</div></div>';
    for(const type of Object.keys(names)){
      html+=`<div class="diff-overview-row"><span class="diff-lane-label">${names[type]}</span><div class="diff-lane" data-diff-track><div class="diff-window" style="left:${left}%;width:${Math.max(.15,right-left)}%"></div>`;
      for(const c of model.changes.filter(c=>c.type===type&&(filter==='all'||filter===type)))html+=`<button class="diff-marker change-${type}${c.index===selectedIndex?' diff-marker-selected':''}" data-diff-index="${c.index}" style="left:clamp(0px,${100*c.reference_start/n}%,calc(100% - 5px));width:max(5px,${100*(c.reference_end-c.reference_start)/n}%)" aria-describedby="diff-hover-tooltip" aria-label="${escape(label(c))}" aria-pressed="${c.index===selectedIndex}" tabindex="0"></button>`;
      html+='</div></div>';
    }
    return html;
  }
  const api={build,affected,startFor,windowRange,columnForReference,label,names,span,originalSpans,queryPosition,windowHtml,overviewHtml,restrictionSites,enzymeFor,enzymes,hoverHtml,featureSpans,siteColumn,annotationParts,featureSubtrack,siteOverlay,cutSpans,coordinateRuler,originalQueryLabel};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.DifferenceViewer=api;
})(typeof window==='object'?window:globalThis);
