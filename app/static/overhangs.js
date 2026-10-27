/* Four-base fusion labels are palindromic when equal to their reverse complement. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.Overhangs=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  const complement={A:'T',T:'A',C:'G',G:'C'};
  function isPalindromic(value){
    const sequence=String(value??'').trim().toUpperCase();
    return /^[ACGT]{4}$/.test(sequence)&&[...sequence].every((base,i)=>base===complement[sequence[3-i]]);
  }
  function labels(left,right){return [...new Set([left,right].filter(isPalindromic).map(value=>String(value).trim().toUpperCase()))];}
  return {isPalindromic,labels,warning:'Palindromic overhang · can self-ligate'};
});
