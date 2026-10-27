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
  const api={reverseComplement,orient,match};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.FragmentOrientation=api;
})(typeof globalThis==='object'?globalThis:this);
