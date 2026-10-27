/* Pure label placement: preserve every label, keep its box inside the bounds. */
(function(root){
  'use strict';
  function spread(items,min,max,gap=8){
    const labels=items.map(item=>({...item})).sort((a,b)=>a.position-b.position);
    if(!labels.length)return labels;
    const required=labels.reduce((sum,item)=>sum+item.size,0)+gap*(labels.length-1);
    if(required>max-min+1e-7)throw new RangeError('Labels need more space');
    for(let i=0;i<labels.length;i++){
      const item=labels[i],previous=labels[i-1];
      const lower=previous?previous.position+previous.size/2+gap+item.size/2:min+item.size/2;
      item.position=Math.max(item.position,lower);
    }
    labels.at(-1).position=Math.min(labels.at(-1).position,max-labels.at(-1).size/2);
    for(let i=labels.length-2;i>=0;i--){
      labels[i].position=Math.min(labels[i].position,labels[i+1].position-labels[i+1].size/2-gap-labels[i].size/2);
    }
    return labels;
  }
  function rows(items,min,max,gap=10){
    const sorted=items.map(item=>({...item})).sort((a,b)=>a.position-b.position);
    const groups=[];let group=[],used=0;
    for(const item of sorted){
      if(item.size>max-min)throw new RangeError('A label exceeds the row width');
      const needed=item.size+(group.length?gap:0);
      if(group.length&&used+needed>max-min){groups.push(group);group=[];used=0;}
      used+=item.size+(group.length?gap:0);group.push(item);
    }
    if(group.length)groups.push(group);
    return{count:groups.length,labels:groups.flatMap((group,row)=>spread(group,min,max,gap).map(item=>({...item,row})))};
  }
  const api={spread,rows};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.MapLabelLayout=api;
})(typeof globalThis==='object'?globalThis:this);
