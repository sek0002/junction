/* Read-only Design records use the same map and base viewer as saved plasmids. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.DesignPreview=api;})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  function record(entry,node,enzyme,fusion={}){
    const sequence=node.kind==='fragment'?node.oriented_sequence:node.sequence;
    if(!sequence||/[^ACGT]/.test(sequence))throw Error('Paste A/C/G/T DNA before viewing this insert.');
    const features=[],length=sequence.length;
    const add=(start,end,label,mode='constant')=>{if(start<end&&start>=0&&end<=length)features.push({start,end,label,type:'misc_feature',strand:1,qualifiers:{note:[mode==='dynamic'?'Dynamic region':'Constant region'],ApEinfo_fwdcolor:[mode==='dynamic'?'#8263AF':'#31856D']}});};
    if(node.kind==='placeholder'){
      let position=0;
      for(const section of [...entry.sections].sort((a,b)=>a.start-b.start)){
        add(position,section.start,'Constant');add(section.start,section.end,section.name,section.mode);position=section.end;
      }
      add(position,length,'Constant');
    }else{
      const digest=node.digest;
      add(digest.target_start,digest.target_end,entry.name);
      if(Number.isInteger(digest.left_site_start))add(digest.left_site_start+7,digest.left_site_start+11,'5′ '+digest.left_overhang);
      if(Number.isInteger(digest.right_site_start))add(digest.right_site_start-5,digest.right_site_start-1,'3′ '+digest.right_overhang);
      fusion=digest;
    }
    const context=fusion.left_overhang&&fusion.right_overhang?` · ${node.kind==='placeholder'?'Context · ':''}5′ ${fusion.left_overhang} / 3′ ${fusion.right_overhang}`:'';
    return {viewerTitle:node.kind==='placeholder'?'Insert':'Fragment',name:entry.name+(entry.reverse?' · RC':''),sequence,length,circular:false,enzyme,
      gc:100*(sequence.match(/[GC]/g)||[]).length/length,features,
      restriction_sites:node.sites||node.digest?.all_sites||node.digest?.sites||[],
      viewSummary:(node.kind==='placeholder'?'Insert':'Fragment')+' · '+length+' nt'+context};
  }
  function assembly(result){
    const product=result.assembly;
    if(!product?.sequence||/[^ACGT]/.test(product.sequence))throw Error('Generate an assembly before viewing it.');
    const output=JSON.parse(JSON.stringify(product));
    const variant=result.table_mode?result.assemblies?.[0]?.name:null;
    output.name=(result.name||'New design')+(variant?' · '+variant:'');
    output.viewerTitle='Example assembly';
    output.viewSummary=(result.valid?'Example assembly':'Schematic · Resolve assembly errors')+' · '+output.sequence.length.toLocaleString()+' bp · '+(output.circular?'Circular':'Linear');
    return output;
  }
  return {record,assembly};
});
