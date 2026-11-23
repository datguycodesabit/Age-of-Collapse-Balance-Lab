'use strict';

let studyPreview, studyResult, studyId;
const studyViews={middle:'Zone 1 in the middle',zone2:'Zone 2 banks reliably',zone3:'Zone 3 wins bigger'};
const studyAxisName=key=>labels[key]||(
  key.startsWith('farm_location')?`Zone ${key.at(-1)} farm distance change`:
  key.startsWith('treasure_profile')?`Zone ${key.at(-1)} exact treasure counts`:
  key==='map_family'?'Map family':key.replaceAll('_',' '));
const studyValue=value=>value==null?'Range':typeof value==='object'
  ? Object.entries(value).map(([gold,count])=>`${count} × ${gold}g`).join(', ')||'No Treasure'
  : String(value);

function updateLargeStudyControls(){
  $('study-preview').disabled=busy||$('ruleset').value!=='dice';
  $('study-run').disabled=busy||!studyPreview;
  $('study-resume').disabled=busy||!$('study-saved').value;
  $('study-apply').disabled=busy||!studyResult;
}
function invalidateStudyPreview(){
  studyPreview=null;
  $('study-preview-results').hidden=true;
  updateLargeStudyControls();
}
function appendStudyAxis(axis={}){
  if($('study-axes').children.length>=12)throw Error('Use up to 12 study axes.');
  const row=document.createElement('div');
  row.className='study-axis';
  row.innerHTML='<label>Setting<select class="study-axis-key"></select></label><label>Choices<input class="study-axis-values" required></label><button type="button" class="study-remove">Remove</button><p class="muted small study-axis-help"></p>';
  const select=row.querySelector('select');
  const input=row.querySelector('input');
  const keys=[...new Set([...config.study_axes,...[1,2,3].flatMap(z=>[`farm_location${z}`,`treasure_profile${z}`])])];
  for(const key of keys.sort((a,b)=>studyAxisName(a).localeCompare(studyAxisName(b)))){
    select.add(new Option(studyAxisName(key),key));
  }
  select.value=axis.key??keys.find(k=>!Array.from($('study-axes').querySelectorAll('select')).some(s=>s.value===k));
  const help=row.querySelector('.study-axis-help');
  const refresh=()=>{
    const exact=select.value.startsWith('treasure_profile');
    const farm=select.value.startsWith('farm_location');
    input.placeholder=exact?'[{"2":6,"4":6}, null]':farm?'0, -1, 1':'1, 2, 3 or 1:3:1';
    help.textContent=exact?'Use a JSON list of card counts by gold value. null uses the range.':
      farm?'Signed steps from the current map’s farm distance. Zero keeps the farm in place.':
      'Enter comma-separated values or min:max:step.';
  };
  if(axis.values)input.value=select.value.startsWith('treasure_profile')?JSON.stringify(axis.values):axis.values.join(', ');
  select.onchange=()=>{input.value='';refresh();invalidateStudyPreview();};
  input.oninput=invalidateStudyPreview;
  row.querySelector('button').onclick=()=>{row.remove();invalidateStudyPreview();};
  refresh();
  $('study-axes').append(row);
}
function studyWhole(text){
  if(!/^-?\d+$/.test(text.trim())||!Number.isSafeInteger(Number(text)))throw Error('Enter whole-number axis values.');
  return Number(text);
}
async function studyPayload(){
  const axes=[...$('study-axes').children].map(row=>{
    const key=row.querySelector('select').value;
    const text=row.querySelector('input').value.trim();
    if(key.startsWith('treasure_profile'))return {key,values:JSON.parse(text)};
    if(text.includes(':')){
      const range=text.split(':');
      if(range.length!==3)throw Error('Enter ranges as min:max:step.');
      const [min,max,step]=range.map(studyWhole);
      return {key,min,max,step};
    }
    return {key,values:text.split(',').map(studyWhole)};
  });
  const files=[...$('study-maps').files];
  const maps=await Promise.all(files.map(async file=>{
    if(file.size>64000)throw Error('Choose a map or settings JSON file under 64 KB.');
    const data=JSON.parse(await file.text());
    return data.board?.layout??data.board??data.layout??data;
  }));
  const bounds=$('study-distances').value.split(',').map(range=>range.split(/[-–]/).map(studyWhole));
  return {settings:readSettings(),board:readMap(),'large-study':{
    axes,maps,generate:{count:$('study-generated').valueAsNumber,bounds},
    candidates:$('study-budget').valueAsNumber,screen:$('study-screen').valueAsNumber,
    refine:$('study-refine').valueAsNumber,fresh:$('study-fresh').valueAsNumber
  }};
}
function showStudyPreview(info){
  $('study-preview-results').hidden=false;
  $('study-preview-results').innerHTML=`<p><strong>${fmt(info.candidates.length,0)} setups</strong> including the current setup. Up to <strong>${fmt(info.maximum_matches,0)} matches</strong> across all stages.</p>
    <p class="muted small">${BigInt(info.grid).toLocaleString()} grid combinations · ${info.generated} generated maps · ${fmt(info.rejected,0)} invalid combinations skipped${info.warnings.length?` · ${esc(info.warnings.join(' '))}`:''}</p>
    <details><summary>Preview setup choices and farm distances</summary><div class="table-wrap"><table>
    <thead><tr><th scope="col">Setup</th><th scope="col">Choices</th><th scope="col">Farm steps from Surface, Z1 / Z2 / Z3</th></tr></thead>
    <tbody>${info.candidates.map(c=>`<tr><td>${c.id||'Current'}</td><td>${studyAxesText(c)}</td><td>${c.distances.map(d=>d.join(', ')||'—').join(' / ')}</td></tr>`).join('')}</tbody></table></div></details>`;
}
function studyAxesText(candidate){
  return Object.entries(candidate.axes).map(([key,value])=>`${esc(studyAxisName(key))} ${esc(studyValue(value))}`).join(' · ');
}
async function refreshSavedStudies(selected){
  const picker=$('study-saved');
  const old=selected??picker.value;
  const saved=await request('/api/large-studies');
  picker.replaceChildren(new Option('Choose a saved study',''),...saved.map(s=>
    new Option(`${s.complete?'Complete':'Checkpoint'} · ${s.candidates} setups · ${fmt(s.done,0)} matches · ${s.id.slice(0,7)}`,s.id)));
  if(saved.some(s=>s.id===old))picker.value=old;
  updateLargeStudyControls();
}
async function startLargeStudy(payload){
  try{
    const completed=await job('large-study',payload,started=>{
      studyId=started.study_id;
      $('cancel').textContent='Pause study';
    });
    studyResult=completed;
    renderLargeStudy();
    notice('Large Study finished.');
  }catch(error){notice(error.message,true);}
  finally{
    try{await refreshSavedStudies(studyId);}catch(error){notice(error.message,true);}
  }
}
function renderLargeStudy(){
  $('study-results').hidden=false;
  $('study-summary').textContent=`${fmt(studyResult.matches,0)} matches across all stages. Finalists and the current setup use fresh seed block ${studyResult.seed_blocks.fresh}.`;
  $('study-export-json').href=`/api/large-studies/${studyId}/json`;
  $('study-export-json').download=`study-${studyId}.json`;
  $('study-export-csv').href=`/api/large-studies/${studyId}/csv`;
  const candidates=studyResult.design.candidates;
  const picker=$('study-finalists');
  const finalists=studyResult.validation.filter(v=>v.candidate);
  picker.replaceChildren(...finalists.map(({candidate})=>new Option(candidates[candidate].label,candidate)));
  $('study-views').innerHTML=Object.entries(studyViews).map(([key,title])=>`<div><h3>${title}</h3>
    <p class="muted small">${studyResult.views[key].slice(0,3).map(id=>`<button type="button" data-study-choice="${id}">${esc(candidates[id].label)}</button>`).join(' ')}</p></div>`).join('');
  $('study-views').querySelectorAll('[data-study-choice]').forEach(button=>button.onclick=()=>{
    picker.value=button.dataset.studyChoice;
    showStudyComparison();
  });
  showStudyComparison();
  buildStudyHeatmap();
}
function studyComparisonSelection(){
  return studyResult.validation.find(v=>v.candidate===Number($('study-finalists').value));
}
function showStudyComparison(){
  const trial=studyComparisonSelection();
  const base=studyResult.validation[0];
  const profile=$('study-profile').value;
  const setup=studyResult.design.candidates[trial.candidate];
  const join=(items,convert=fmt)=>items.map(item=>convert(item)).join(' / ');
  const matchupSummary=(m,i)=>{
    const scored=[base[profile].matchups[i],m];
    const tradeoffs=scored.map(row=>{
      const [shallow,z2,z3]=row.routes;
      const middle=row.strict_score>=Math.min(z2.score,z3.score)&&row.strict_score<=Math.max(z2.score,z3.score);
      const big=z3.winning_score!=null&&z3.winning_score>Math.max(shallow.winning_score??0,z2.winning_score??0);
      return [middle?'Yes':'No',big&&z3.win<Math.min(row.strict_win,z2.win)?'Yes':'No'];
    });
    const rows=[
      ['Strict Zone 1 farmer’s mean score',r=>fmt(r.strict_score,2)],
      ['Mean qualifying score (Z1 / Z2 / Z3)',r=>join(r.routes.map(d=>d.score))],
      ['Split win share per seat (Z1 / Z2 / Z3)',r=>join(r.routes.map(d=>d.win),percent)],
      ['Strict Zone 1 farmer’s split win share',r=>percent(r.strict_win)],
      ['Mining followed by a bank at target depth (Z1 / Z2 / Z3)',r=>join(r.routes.map(d=>d.funnel.banked.rate),percent)],
      ['Seats mining each depth (Z1 / Z2 / Z3)',r=>join(r.actual_mined,percent)],
      ['Seats mining then banking (Z1 / Z2 / Z3)',r=>join(r.actual_banked,percent)],
      ['Winning score (Z1 / Z2 / Z3)',r=>join(r.routes.map(d=>d.winning_score))],
      ['95th-percentile cards drawn (Z1 / Z2 / Z3)',r=>join(r.p95_draws,n=>fmt(n,0))],
      ['Deck depleted (Z1 / Z2 / Z3)',r=>join(r.depleted,percent)],
      ['Estimated minutes per match',r=>fmt(r.minutes)],
      ['Estimated 95th-percentile seconds per turn',r=>fmt(r.p95_turn,0)],
    ];
    return `<details class="study-matchup"${i===0?' open':''}><summary>${esc(m.label)}</summary><div class="table-wrap"><table>
     <thead><tr><th scope="col">Measure</th><th scope="col">Current</th><th scope="col">${esc(setup.label)}</th></tr></thead><tbody>
     ${rows.map(([name,value])=>`<tr><th scope="row">${name}</th><td>${value(scored[0])}</td><td>${value(scored[1])}</td></tr>`).join('')}
     <tr><th scope="row">Zone 1 mean is between Zones 2 and 3</th><td>${tradeoffs[0][0]}</td><td>${tradeoffs[1][0]}</td></tr>
     <tr><th scope="row">Zone 3 wins less often and scores more when it wins</th><td>${tradeoffs[0][1]}</td><td>${tradeoffs[1][1]}</td></tr>
     <tr><th scope="row">Paired mean score change with approximate 95% interval</th><td>—</td><td>${m.score_delta.map((d,z)=>`<small>Zone ${z+1} · ${fmt(d.mean,2)} (${fmt(d.interval[0],2)} to ${fmt(d.interval[1],2)}) · ${d.games} matched games</small>`).join('')}</td></tr>
     </tbody></table></div></details>`;
  };
  const policies=Object.entries(trial[profile].policy).map(([depth,policy])=>`Zone ${depth} ${policy}`).join(' · ');
  $('study-comparison').innerHTML=`<p>${studyAxesText(setup)}</p><p class="muted small">${policies?esc(policies):'Original policies for all roles.'}</p>
    ${trial[profile].matchups.map(matchupSummary).join('')}`;
  updateLargeStudyControls();
}
const axisToken=value=>JSON.stringify(value);
function axisValues(key){
  return [...new Map(studyResult.design.candidates.map(c=>[axisToken(c.axes[key]),c.axes[key]])).values()]
    .sort((a,b)=>typeof a==='number'&&typeof b==='number'?a-b:studyValue(a).localeCompare(studyValue(b)));
}
function buildStudyHeatmap(){
  const axes=studyResult.design.axes;
  const list=()=>axes.map(axis=>new Option(studyAxisName(axis),axis));
  $('study-heat-x').replaceChildren(...list());
  $('study-heat-y').replaceChildren(new Option('One axis',''),...list());
  $('study-heat-y').value=axes[1]??'';
  function refresh(){
    const x=$('study-heat-x').value;
    if($('study-heat-y').value===x)$('study-heat-y').value='';
    const y=$('study-heat-y').value;
    const filters=$('study-heat-filters');
    const old=Object.fromEntries([...filters.querySelectorAll('select')].map(s=>[s.dataset.axis,s.value]));
    filters.replaceChildren(...axes.filter(key=>key!==x&&key!==y).map(key=>{
      const label=document.createElement('label');
      label.append(studyAxisName(key));
      const select=document.createElement('select');
      select.dataset.axis=key;
      select.add(new Option('All tested values',''));
      for(const value of axisValues(key))select.add(new Option(studyValue(value),axisToken(value)));
      select.value=old[key]??'';
      select.onchange=renderStudyHeatmap;
      label.append(select);
      return label;
    }));
    renderStudyHeatmap();
  }
  $('study-heat-x').onchange=$('study-heat-y').onchange=refresh;
  $('study-heat-metric').onchange=renderStudyHeatmap;
  refresh();
}
function screenMetric(row,key){
  const values=row.matchups.slice(0,2).map(m=>{
    const [,two,three]=m.routes;
    if(key==='middle')return Math.max(0,Math.min(two.score,three.score)-m.strict_score,m.strict_score-Math.max(two.score,three.score));
    if(key==='zone2')return 100*two.funnel.banked.rate;
    return three.winning_score;
  }).filter(n=>n!=null);
  return values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
}
function renderStudyHeatmap(){
  const x=$('study-heat-x').value,y=$('study-heat-y').value,metric=$('study-heat-metric').value;
  const filters=[...$('study-heat-filters').querySelectorAll('select')].filter(s=>s.value);
  const groups=new Map();
  for(const row of studyResult.screen){
    const c=studyResult.design.candidates[row.candidate];
    if(filters.some(s=>s.value!==axisToken(c.axes[s.dataset.axis])))continue;
    const key=axisToken([c.axes[x],y?c.axes[y]:null]);
    const rows=groups.get(key)??[];
    rows.push(screenMetric(row,metric));
    groups.set(key,rows);
  }
  const cells=new Map([...groups].map(([key,rows])=>{
    const numbers=rows.filter(value=>value!=null).sort((a,b)=>a-b);
    const n=numbers.length,i=Math.floor(n/2);
    return [key,{value:n?(n%2?numbers[i]:(numbers[i-1]+numbers[i])/2):null,count:rows.length}];
  }));
  const values=[...cells.values()].map(c=>c.value).filter(n=>n!=null);
  const low=Math.min(...values),high=Math.max(...values);
  const cols=axisValues(x),rows=y?axisValues(y):[null];
  $('study-heatmap').innerHTML=`<table class="study-heat-values"><thead><tr><th scope="col">${esc(y?studyAxisName(y):'Screening median')}</th>
    ${cols.map(v=>`<th scope="col">${esc(studyValue(v))}</th>`).join('')}</tr></thead><tbody>
    ${rows.map(row=>`<tr><th scope="row">${row===null&&!y?'All setups':esc(studyValue(row))}</th>${cols.map(col=>{
      const cell=cells.get(axisToken([col,row]));
      if(!cell)return '<td></td>';
      const value=cell.value;
      const scale=value==null||low===high?0:Math.round(4*(metric==='middle'?high-value:value-low)/(high-low));
      return `<td class="study-heat-${scale}">${fmt(value)}${metric==='zone2'&&value!=null?'%':''}<small>${cell.count} setups</small></td>`;
    }).join('')}</tr>`).join('')}</tbody></table>`;
}
function buildLargeStudy(){
  $('study-starter').onclick=()=>{
    $('study-axes').replaceChildren();
    for(const axis of config.study_starter)appendStudyAxis(axis);
    invalidateStudyPreview();
  };
  $('study-starter').click();
  $('study-add-axis').onclick=()=>{try{appendStudyAxis();invalidateStudyPreview();}catch(error){notice(error.message,true);}};
  for(const id of ['study-budget','study-screen','study-refine','study-fresh','study-maps','study-generated','study-distances']){
    $(id).addEventListener('input',invalidateStudyPreview);
  }
  $('study-preview').onclick=async()=>{
    try{
      const payload=await studyPayload();
      const preview=await request('/api/large-study-preview',payload);
      studyPreview=payload;
      showStudyPreview(preview);
      updateLargeStudyControls();
      notice('Preview ready. The study will use this snapshot of the rules and map.');
    }catch(error){invalidateStudyPreview();notice(error.message,true);}
  };
  $('study-run').onclick=()=>startLargeStudy(studyPreview);
  $('study-saved').onchange=updateLargeStudyControls;
  $('study-resume').onclick=()=>startLargeStudy({'large-study':{resume:$('study-saved').value}});
  $('study-finalists').onchange=$('study-profile').onchange=showStudyComparison;
  $('study-apply').onclick=async()=>{
    const setup=studyResult.design.candidates[studyComparisonSelection().candidate];
    setMap(setup.board);
    setSettings(setup.settings);
    tab('overview');
    await simulate();
  };
  refreshSavedStudies().catch(error=>notice(error.message,true));
}
