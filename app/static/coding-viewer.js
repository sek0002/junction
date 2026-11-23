/* Coding consequences use real sequence changes, including adjusted-away gaps. */
(function(root){
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={synonymous:'Synonymous',missense:'Missense',stop_gained:'Stop gained',stop_lost:'Stop lost',start_lost:'Start lost',
    frameshift:'Frameshift',inframe_insertion:'In-frame insertion',inframe_deletion:'In-frame deletion',frameshift_context:'Frameshift context',uncertain:'Uncertain'};
  const label=effect=>labels[effect.type]||'Uncertain';
  const frame=value=>value===null||value===undefined?'—':value>0?'+'+value:String(value);
  const spans=values=>(values||[]).map(([a,b])=>`${a+1}–${b}`).join(', ')||'—';
  function effectsHtml(effects){
    if(!effects?.length)return '';
    return '<div class="coding-effects">'+effects.map(effect=>`<span class="coding-effect coding-${escape(effect.type)}"><b>${label(effect)}</b><span>${escape(effect.region_name)} · AA ${effect.amino_acid_position}</span><code>${escape(effect.reference_codon)} → ${escape(effect.query_codon)} · ${escape(effect.protein_change)}</code></span>`).join('')+'</div>';
  }
  function summaryHtml(report){
    if(!report)return '';
    const counts=report.summary||{};
    const changed=Object.entries(counts).filter(([kind,count])=>count&&labels[kind]&&kind!=='synonymous');
    if(!changed.length)return counts.synonymous?`<small class="coding-summary coding-synonymous">${report.predicted?'Predicted · ':''}${counts.synonymous} synonymous substitution${counts.synonymous===1?'':'s'}</small>`:'';
    return `<small class="coding-summary">${report.predicted?'Predicted · ':''}${changed.map(([kind,count])=>`${count} ${labels[kind].toLowerCase()}`).join(' · ')}</small>`;
  }
  function regionHtml(region){
    const effects=region.effects||[],counts=new Map();
    for(const effect of effects)counts.set(label(effect),(counts.get(label(effect))||0)+1);
    const outcome=region.query_only?'Query translation':region.protein_changed===null?'Review translation':region.protein_changed?'Protein changed':'Protein unchanged';
    const status=effects.length?[...counts].map(([kind,count])=>`${count} ${kind}`).join(' · '):outcome;
    const basis=region.basis==='predicted_orf'?'Predicted ORF':region.source==='query'?'Uploaded CDS':'Reference CDS';
    const table=effects.length?`<div class="table-scroll"><table><thead><tr><th>Effect</th><th>Reference</th><th>Original query</th><th>Codons</th><th>Protein</th></tr></thead><tbody>${effects.map(effect=>`<tr><td><span class="coding-effect coding-${escape(effect.type)}">${label(effect)}</span></td><td>${spans(effect.reference_spans)}</td><td>${spans(effect.query_spans)}</td><td><code>${escape(effect.reference_codon)} → ${escape(effect.query_codon)}</code></td><td><code>${escape(effect.protein_change)}</code><small>Ref AA ${effect.amino_acid_position} · Query AA ${effect.query_amino_acid_position}</small></td></tr>`).join('')}</tbody></table></div>`:'';
    return `<details class="coding-region"><summary><b>${escape(region.name)}</b><span>${basis}${region.query_only?'':` · Ref frame ${frame(region.reference_frame)}`} · Query frame ${frame(region.query_frame)}</span><small>${escape(status)}</small></summary><div class="coding-region-body"><div class="coding-region-meta"><span>Code ${region.translation_table} · codon_start ${region.codon_start}</span><span>${region.query_only?'':`Reference ${region.reference_aa_length} aa · `}Query ${region.query_aa_length} aa</span><span>${outcome}</span></div>${region.warnings?.length?`<ul class="coding-warnings">${region.warnings.map(text=>`<li>${escape(text)}</li>`).join('')}</ul>`:''}${table}<details class="coding-proteins"><summary>Translations</summary>${region.query_only?'':`<label>Reference</label><pre>${escape(region.reference_protein)||'Unavailable'}</pre>`}<label>Query</label><pre>${escape(region.query_protein)||'Unavailable'}</pre></details></div></details>`;
  }
  function panelHtml(report){
    if(!report)return '<p class="small muted">Translation analysis is unavailable for this alignment.</p>';
    const regions=report.regions||[];
    const annotated=regions.filter(region=>region.basis==='annotated_cds'),predicted=regions.filter(region=>region.basis==='predicted_orf');
    let html=report.query_only?'<p class="small muted">Query translation · no reference alignment. * = stop codon.</p>':'<p class="small muted">Codons include all observed sequence changes. Frames refer to each original sequence. * = stop codon.</p>';
    if(report.warnings?.length)html+=`<ul class="coding-warnings">${report.warnings.map(text=>`<li>${escape(text)}</li>`).join('')}</ul>`;
    if(report.effects_capped)html+='<p class="coding-warnings">Coding-effect list capped at 10,000 entries.</p>';
    if(annotated.length)html+='<h3>Annotated CDS</h3>'+annotated.map(regionHtml).join('');
    if(report.predicted){
      html+=`<h3>Predicted ORFs</h3><p class="small muted">Six-frame ATG-to-stop search · minimum ${report.min_orf_aa} aa · standard genetic code. Predictions indicate possible coding regions.</p>`;
      html+=`<div class="coding-frame-grid">${Object.entries(report.frames||{}).map(([source,frames])=>`<div><b>${source==='query'?'Query':'Reference'} frames</b>${frames.map(item=>`<span>Frame ${frame(item.frame)} · ${item.orf_count} ORFs · longest ${item.longest_aa} aa</span>`).join('')}</div>`).join('')}</div>`;
      html+=predicted.map(regionHtml).join('')||'<p class="small muted">No predicted ORFs meet the minimum length.</p>';
    }
    if(report.unassigned_substitution_bp)html+=`<p class="small muted">${report.unassigned_substitution_bp} substituted bases fall outside the analysed coding regions.</p>`;
    return html;
  }
  const api={labels,label,effectsHtml,summaryHtml,panelHtml};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.CodingViewer=api;
})(typeof window==='object'?window:globalThis);
