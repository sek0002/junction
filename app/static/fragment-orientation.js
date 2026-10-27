/* Fusion labels are compared in one assembled 5′→3′ frame. */
(function(root){
  'use strict';
  const reverseComplement=value=>String(value||'').toUpperCase().split('').reverse().map(base=>({A:'T',C:'G',G:'C',T:'A'}[base]||base)).join('');
  function flipped(digest){return {...digest,left_overhang:reverseComplement(digest.right_overhang),right_overhang:reverseComplement(digest.left_overhang),target:reverseComplement(digest.target),sequence:reverseComplement(digest.sequence),input_sequence:reverseComplement(digest.input_sequence),reverse_complement:!digest.reverse_complement,orientation:digest.reverse_complement?1:-1};}
  function orient(part,reverse){
    const forward=part.forward_digest||(part.digest?.reverse_complement?flipped(part.digest):part.digest)||{};
    return {...part,forward_digest:forward,digest:reverse?flipped(forward):{...forward,reverse_complement:false,orientation:1},reverse_complement:!!reverse,orientation:reverse?-1:1};
  }
  function match(part,left,right){return [false,true].map(reverse=>orient(part,reverse)).find(p=>(!left||p.digest.left_overhang===left)&&(!right||p.digest.right_overhang===right))||null;}
  function alternatives(parts,fragments,index,{left,right,hasBackbone=false,closed=false}={}){
    const current=parts[index];if(!current)return [];
    const label=value=>/^[ACGT]{4}$/.test(value||'')?value:null;
    const labels=(...values)=>[...new Set(values.map(label).filter(Boolean))];
    // Keep occupied fragment junctions and matched backbone ends intact. Empty
    // ends and unmatched backbone ends are free to change during a swap.
    const leftLabels=index?labels(label(parts[index-1].digest.right_overhang)||current.digest.left_overhang):!hasBackbone&&closed?labels(parts.at(-1).digest.right_overhang):hasBackbone&&label(left)&&left===current.digest.left_overhang?labels(left):[];
    const rightLabels=index+1<parts.length?labels(label(parts[index+1].digest.left_overhang)||current.digest.right_overhang):!hasBackbone&&closed?labels(parts[0].digest.left_overhang):hasBackbone&&label(right)&&right===current.digest.right_overhang?labels(right):[];
    const used=new Set(parts.map(part=>part.id));
    const result=[];
    for(const part of fragments){
      if(used.has(part.id)||!part.digest.valid)continue;
      const variants=[false,true].map(reverse=>orient(part,reverse)).filter(part=>(!leftLabels.length||leftLabels.includes(part.digest.left_overhang))&&(!rightLabels.length||rightLabels.includes(part.digest.right_overhang))).map(part=>{
        const mismatches=[];
        if(hasBackbone&&index===0&&label(left)&&part.digest.left_overhang!==left)mismatches.push('5′ backbone: '+part.digest.left_overhang+' / '+left);
        if(hasBackbone&&index===parts.length-1&&label(right)&&part.digest.right_overhang!==right)mismatches.push('3′ backbone: '+part.digest.right_overhang+' / '+right);
        return {...part,swap_backbone_mismatches:mismatches};
      }).sort((a,b)=>a.swap_backbone_mismatches.length-b.swap_backbone_mismatches.length||Number(a.reverse_complement)-Number(b.reverse_complement));
      if(variants.length)result.push(variants[0]);
    }
    return result.sort((a,b)=>a.swap_backbone_mismatches.length-b.swap_backbone_mismatches.length||a.name.localeCompare(b.name)||(a.plate_id||'').localeCompare(b.plate_id||'')||(a.well||'').localeCompare(b.well||''));
  }
  const api={reverseComplement,orient,match,alternatives};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.FragmentOrientation=api;
})(typeof globalThis==='object'?globalThis:this);
