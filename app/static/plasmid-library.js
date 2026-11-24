/* Filtering and stable sorting for the shared plasmid lists. */
(function(root,factory){const lib=factory();if(typeof module==='object'&&module.exports)module.exports=lib;else root.JunctionPlasmidLibrary=lib;})(typeof window==='object'?window:globalThis,()=>{
 'use strict';
 function normaliseView(input={}){input=input&&typeof input==='object'?input:{};return {search:typeof input.search==='string'?input.search.slice(0,1000):'',folder:input.folder==='unfiled'||/^\d+$/.test(String(input.folder))?String(input.folder):'all',sort:['newest','oldest','name','name-desc','length','length-desc','folder'].includes(input.sort)?input.sort:'newest'};}
 function filter(items,view={}){view=normaliseView(view);
  const words=String(view.search||'').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean),folder=String(view.folder||'all');
  const result=items.filter(p=>{if(folder==='unfiled'&&p.folder_id!=null||folder!=='all'&&folder!=='unfiled'&&String(p.folder_id)!==folder)return false;const text=[p.name,p.folder_name,p.notes,...Object.entries(p.backbone_options?.site_counts||{}).filter(([,n])=>n).map(([name])=>name)].join(' ').toLocaleLowerCase();return words.every(word=>text.includes(word));});
  const mode=view.sort||'newest',get=mode.startsWith('length')?p=>p.length:mode.startsWith('folder')?p=>p.folder_name||'':mode==='newest'||mode==='oldest'?p=>p.created_at||'':p=>p.name;
  const direction=['name-desc','length-desc','newest'].includes(mode)?-1:1;
  return result.sort((a,b)=>{const x=get(a),y=get(b),comparison=typeof x==='number'?x-y:String(x).localeCompare(String(y),undefined,{numeric:true,sensitivity:'base'});return comparison*direction||(a.id-b.id)*(['newest'].includes(mode)?-1:1);});
 }
 return {filter,normaliseView};
});
