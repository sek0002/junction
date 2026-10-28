/* Query strand is independent of the orientation selected for assembly. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.FragmentSearch=api;})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function badge(fragment){
    const match=fragment.search_match;if(!match||!['overhang','sequence'].includes(match.kind))return '';
    const rc=!!match.reverse_complement,label=(match.kind==='overhang'?'Overhang':'DNA')+(rc?' · RC':'');
    const location=match.kind==='overhang'?(match.side==='left'?'5′':'3′')+' overhang '+(match.matched_sequence||''):(match.source==='construct_sequence'?'Construct DNA':'Fragment DNA')+' at bases '+(match.start+1)+'–'+match.end;
    const title='Query matches '+(rc?'the reverse complement of ':'')+location+'. Assembly orientation remains automatic.';
    return `<span class="fragment-search-match" title="${esc(title)}">${esc(label)}</span>`;
  }
  return {badge};
});
