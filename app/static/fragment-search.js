/* Query strand is independent of the orientation selected for assembly. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.FragmentSearch=api;})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function badge(fragment){
    const stock=stockBadge(fragment);const match=fragment.search_match;if(!match||!['overhang','sequence'].includes(match.kind))return stock;
    const rc=!!match.reverse_complement,label=(match.kind==='overhang'?'Overhang':'DNA')+(rc?' · RC':'');
    const location=match.kind==='overhang'?(match.side==='left'?'5′':'3′')+' overhang '+(match.matched_sequence||''):(match.source==='construct_sequence'?'Construct DNA':'Fragment DNA')+' at bases '+(match.start+1)+'–'+match.end;
    const title='Query matches '+(rc?'the reverse complement of ':'')+location+'. Assembly orientation remains automatic.';
    return stock+`<span class="fragment-search-match" title="${esc(title)}">${esc(label)}</span>`;
  }
  function location(fragment,plateLabel=value=>value){return [fragment.location,[plateLabel(fragment.plate_id||''),fragment.well].filter(Boolean).join(' / ')].filter(Boolean).join(' · ')||'Location not set';}
  function stockBadge(fragment){const source=fragment.custom_metadata?.linked_fragment_name;if(!source&&!fragment.custom_metadata?.linked_fragment_id)return '';return `<span class="fragment-search-match linked-stock-flag" title="${esc('Shares DNA with '+(source||'linked fragment')+'; independent stock and volume.')}">Linked stock</span>`;}
  return {badge,location,stockBadge};
});
