'use strict';
const $ = id => document.getElementById(id);
let config, testPreset, result, previous, searchResult, activeJob, caveBalance, busy=false;
let exactTreasureProfiles={};
const controls = new Map();
const labels = {};
const limits = {
  turns:[1,60,1],players:[1,20,1],runs:[1,5000,1],seed:[0,9007199254740991,1],
  start_energy:[0,100,1],gain:[0,100,1],cap:[1,100,1],lose_depth:[0,3,1],lose_loot:[0,20,1],
  hp1:[1,40,1],hp2:[1,40,1],hp3:[1,60,1],atk1:[0,15,1],atk2:[0,15,1],atk3:[0,15,1],
  avg_roll:[0.5,12,0.5],delve:[1,20,1],retreat:[1,20,1],retreat_start:[1,61,1],
  zone2_start:[1,61,1],zone3_start:[1,61,1],loot_per_depth:[0,20,1],deep_cache_loot:[0,50,1],
  enhance:[0,20,1],p_treasure:[0,100,1],p_monster:[0,100,1],p_enhance:[0,100,1],
  dark_cost:[1,10,1],rough_cost:[1,10,1],boots_price:[0,30,1],flashlight_price:[0,30,1],
  climbing_price:[0,30,1],buy_boots:[0,1,1],buy_flashlight:[0,1,1],buy_climbing:[0,1,1],
  farm_visits:[0,20,1],farm_cost:[1,20,1],mine_cost:[1,20,1],boss_enabled:[0,1,1],boss_start:[1,201,1],
  boss_threshold:[1,6,1],boss_loot_loss:[0,30,1],boss_energy_hit:[0,30,1],
  gear_slots:[0,10,1],gear_priority:[0,4,1],max_zone:[1,3,1],route_policy:[0,3,1],
  blade_savings:[0,5,1],pack_protection:[0,5,1],charm_bonus:[0,5,1],battery_gain:[0,5,1],
  potion_chance:[0,100,0.1],use_potions:[0,1,1],deep_entry_tonic:[0,1,1],
  shared_decks:[0,1,1],sword_savings:[0,20,1],shield_savings:[0,20,1],upgrade_price:[0,20,1],
  dice_rules:[0,1,1],sword_price:[0,20,1],shield_price:[0,20,1],
  field_starter_gear:[0,1,1],sword_damage_bonus:[0,3,1],shop_gold_prices:[0,1,1],
  full_energy_moves:[0,1,1],
  farm_shared_limit:[0,20,1],deep_tonic_energy:[1,10,1],boots_move_range:[2,6,1],shield_block_per_level:[1,3,1],
  bow_savings:[0,20,1],grenade_savings:[0,20,1],canister_gain:[0,20,1],energy_potion_gain:[0,20,1],
  adaptive_retreat:[0,1,1],retreat_slack:[0,10,1],farm_detour_limit:[-1,60,1]
};
const priorities=['Balanced','Farm and profit','Deep expedition','Safe return','Mixed, price-aware shoppers'];
for(const z of [1,2,3]){
  limits['hp_min'+z]=limits['hp_max'+z]=[1,100,1];
  limits['treasure_min'+z]=limits['treasure_max'+z]=[0,50,1];
  limits['deck_monsters'+z]=limits['deck_treasures'+z]=[0,50,1];
  limits['bounty'+z]=[0,20,1];
}
const help = {
  turns:'More turns give players more time to get back.',players:'Players have separate discoveries but share one boss schedule per game.',
  runs:'More games reduce sampling noise but take longer.',seed:'Same seed and settings reproduce the same results.',
  start_energy:'Starting pool in dice rules, limited by the Energy cap.',
  gain:'Energy added each later round in dice rules. Earlier modes also use this for round 1.',
  cap:'Higher capacity lets players absorb larger combat costs.',
  retreat_start:'Start retreating on this turn in fixed-turn mode.',
  adaptive_retreat:'Turn back based on energy, equipment and the route through the gates.',
  retreat_slack:'Future turns to reserve beyond the estimated energy refills needed to walk home.',
  farm_detour_limit:'Skip an intermediate farm if it adds more than this many steps. Use -1 to visit regardless of distance.',
  zone2_start:'Earliest turn Zone 2 becomes accessible.',zone3_start:'Earliest turn Zone 3 becomes accessible.',
  lose_depth:'Knockdown ejects to the safe side of a previous zone’s gate.',lose_loot:'Points removed from carried loot per knockdown.',
  hp1:'Higher HP can add an entire combat round.',hp2:'Higher HP can add an entire combat round.',hp3:'Higher HP can add an entire combat round.',
  atk1:'Energy lost between surviving combat rounds.',atk2:'Energy lost between surviving combat rounds.',atk3:'Energy lost between surviving combat rounds.',
  avg_roll:'Average attack damage, not a random die roll.',delve:'Paid on every outward tile; also the combat attack cost.',retreat:'Paid on every tile back toward Surface.',
  loot_per_depth:'Treasure points = this value × zone number.',enhance:'Energy received from an Enhancement card.',
  deep_cache_loot:'Gold awarded on first reaching the Zone 3 farm. Set to 0 to disable.',
  p_treasure:'Higher treasure chance increases reward opportunities.',p_monster:'Higher monster chance increases combat exposure.',p_enhance:'All three card chances must total at most 100%.',
  dark_cost:'Zone 2 and 3 movement multiplier without a Flashlight, including retreat.',
  rough_cost:'Extra Zone 3 multiplier without a Climbing Kit; stacks with darkness.',
  boots_price:'Permanent Boots halve movement costs: two normal steps per energy.',
  flashlight_price:'Flashlight removes the darkness surcharge in Zones 2 and 3.',
  climbing_price:'Climbing Kit removes the rough-ground surcharge in Zone 3.',
  buy_boots:'1: auto-buy when affordable at a shop. 0: never buy.',
  buy_flashlight:'1: auto-buy when affordable at a shop. 0: never buy.',
  buy_climbing:'1: auto-buy when affordable at a shop. 0: never buy.',
  farm_visits:'Standard, mining and gear policies seek this many paid draws before advancing. 0 skips paid mining.',
  farm_cost:'One activation per special farm each turn, drawing two cards.',
  mine_cost:'One activation per regular mine each turn, drawing one card.',
  boss_enabled:'1 enables the shared per-game boss. 0 disables collapse.',
  boss_start:'First end-of-turn d6 roll; boss starts in Zone 3.',
  boss_threshold:'A successful die roll moves the monster toward Surface. The third advance seals the entrance.',
  boss_loot_loss:'Carried loot lost when ejected from a collapsing zone.',
  boss_energy_hit:'Energy lost when ejected from Zone 3 or 2. The final seal kills everyone still underground.'
};
const fmt=(n,d=1)=>n==null?'—':Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(text,error=false){$('message').textContent=text;$('message').className='notice'+(error?' error':'');$('message').hidden=!text;}
function tab(name){if(name!=='explorer')stopReplay();document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('[data-tab]').forEach(e=>e.classList.toggle('active',e.dataset.tab===name));}
document.querySelectorAll('[data-tab]').forEach(e=>e.addEventListener('click',()=>tab(e.dataset.tab)));
$('go-strategy').onclick=()=>tab('strategy-balance');
$('toggle-settings').onclick=()=>{const open=document.querySelector('.sidebar').classList.toggle('expanded');$('toggle-settings').setAttribute('aria-expanded',String(open));$('toggle-settings').textContent=open?'Hide settings':'Edit settings';};
function readSettings(){
  const settings={};
  for(const [key,{number}] of controls){
    if(!number.checkValidity()||number.value.trim()==='')throw Error(`${labels[key]}: enter a valid number (${number.min}–${number.max}).`);
    settings[key]=Number(number.value);
  }
  settings.treasure_profiles=structuredClone(exactTreasureProfiles);
  return settings;
}
const earlierDiceFields = new Set([
  'sword_savings','shield_savings','hp1','hp2','hp3','avg_roll','zone2_start','zone3_start',
  'loot_per_depth','enhance','p_treasure','p_monster','p_enhance','farm_visits','farm_detour_limit',
  'gear_slots','gear_priority','route_policy','lose_loot','potion_chance'
]);
const diceMovementFields = new Set(['delve','retreat','dark_cost','rough_cost']);
function showActiveSettings(dice, shared, fullMove){
  $('ruleset').value=dice?'dice':shared?'decks':'independent';
  const auditTab=document.querySelector('[data-tab="action-ev"]');
  if(shared&&auditTab.classList.contains('active'))tab('overview');
  auditTab.hidden=shared;
  $('shop-detours').closest('label').hidden=shared;
  $('load-escape-setup').parentElement.hidden=shared;
  $('shared-rule-catalog').hidden=!shared;
  $('strategy-run').disabled=busy||!dice;
  $('run-preset-search').disabled=busy||!dice;
  for(const [key,{number}] of controls){
    const field=number.closest('.field');
    const group=field.closest('details').dataset.group;
    const earlierGear=group==='Equipment'&&!['boots_price','buy_boots','dark_cost','rough_cost'].includes(key);
    field.hidden=['dice_rules','shared_decks'].includes(key)
      || dice&&(earlierDiceFields.has(key)||earlierGear||fullMove&&diceMovementFields.has(key)
        || !fullMove&&key==='boots_move_range')
      || !dice&&(group==='Dice rules'||key==='start_energy')
      || !shared&&group==='Zone decks';
  }
  for(const details of $('settings').querySelectorAll('details[data-group]')){
    details.hidden=!details.querySelector('.field:not([hidden])');
  }
  for(const option of $('route-study-item').options)option.disabled=shared&&option.value!=='Boots';
  if(shared&&$('route-study-item').value!=='Boots')$('route-study-item').value='Boots';
  const kind=$('route-study-kind');
  kind.querySelector('[value="gear"]').hidden=dice;
  if(dice&&kind.value==='gear'){
    kind.value='depth';
    kind.onchange?.();
  }
  for(const select of document.querySelectorAll('.range-name')){
    for(const option of select.options){
      const zone=option.value.match(/^(?:deck_treasures|treasure_min|treasure_max)([123])$/)?.[1];
      option.disabled=controls.get(option.value).number.closest('.field').hidden
        || Boolean(zone&&Object.hasOwn(exactTreasureProfiles,zone));
    }
  }
  refreshTargetMetrics(dice,shared);
}
function renderRules(s){
  const dice=Boolean(s.dice_rules),shared=Boolean(s.shared_decks);
  const movement=dice&&s.full_energy_moves
    ? `One Move costs 1 Energy and covers up to two squares with standard gear or ${s.boots_move_range} with Boots.`
    : 'Movement is charged per square. Boots halve the cost.';
  const banking=dice?'Walk onto the Surface Exit to deposit gold. You can go back down. The highest bank among players on Surface at the deadline wins.'
    :'Surface extraction banks your treasure and ends the expedition.';
  const currency=dice&&s.shop_gold_prices?'gold':'Treasure cards';
  const shop=dice?`Sword ${s.sword_price} · Shield ${s.shield_price} · Boots ${s.boots_price} · Upgrade ${s.upgrade_price} ${currency}. ${s.field_starter_gear?'Starter Sword and Shield are also sold underground.':''}`
    :'Earlier shop menus and item effects are under Equipment.';
  const boss=s.boss_enabled?`From round ${s.boss_start}, roll one shared d6 at round end. A ${s.boss_threshold}+ collapses the next zone. The third collapse kills anyone underground.`
    :'Collapse is disabled.';
  const combat=dice?`<h3>Combat</h3><p>Roll a d6 plus weapon bonuses. A surviving monster hits Energy after Shield blocks ${s.shield_block_per_level} per level. A hit that takes you to zero drops carried gold and ends the turn.</p>
    <div class="table-wrap"><table><thead><tr><th>Zone</th><th>Monster HP</th><th>Attack</th><th>Bounty</th><th>Treasure range</th></tr></thead><tbody>${[1,2,3].map(z=>`<tr><td>${z}</td><td>${s['hp_min'+z]}–${s['hp_max'+z]}</td><td>${s['atk'+z]}</td><td>${s['bounty'+z]}</td><td>${s['treasure_min'+z]}–${s['treasure_max'+z]}</td></tr>`).join('')}</tbody></table></div>`:'';
  $('active-rules').innerHTML=`<h3>Movement and mining</h3><p>${dice?`Start with ${s.start_energy} Energy. `:''}Gain ${s.gain} per round, up to ${s.cap}. ${movement}</p>
    <p>Mine for ${s.mine_cost} Energy (one card). Farm for ${s.farm_cost} (up to two cards). Each site can be used once per player per round. ${dice&&s.farm_shared_limit?`Each farm has ${s.farm_shared_limit} shared activations per round. `:''}${dice?'Walking draws no cards.':''}</p>
    ${dice&&s.deep_entry_tonic&&s.use_potions?`<p>The Zone 3 entrance Tonic restores up to ${s.deep_tonic_energy} Energy when used.</p>`:''}
    <h3>Banking and shops</h3><p>${banking}</p><p>${shop}</p>${combat}<h3>Collapse</h3><p>${boss}</p>
    ${shared?'<p>Each zone has 50 shared cards. Drawn cards stay out of the deck.</p>':''}`;
}
function markDirty(){
  const dice=$('setting-dice_rules')?.valueAsNumber===1;
  const shared=$('setting-shared_decks')?.valueAsNumber===1;
  const goldPrices=dice && $('setting-shop_gold_prices')?.valueAsNumber===1;
  const coupon=$('shop-coupon-description');
  if(coupon)coupon.textContent=goldPrices
    ? 'Permanent. Reduce the gold cost of each purchase by 1.'
    : config.items.Coupon;
  const fullMove=dice && $('setting-full_energy_moves')?.valueAsNumber===1;
  showActiveSettings(dice,shared,fullMove);
  if(typeof updateLargeStudyControls==='function')updateLargeStudyControls();
  const speed=$('speed-potion-description');
  if(speed)speed.textContent=fullMove
    ? 'Single use. Double the range of your next move.'
    : config.items['Speed Potion'];
  for(const [zone,legacy] of Object.entries(config.zone_decks)){
    const row=$('zone-deck-'+zone);
    if(!row)continue;
    const monsters=dice?$('setting-deck_monsters'+zone).valueAsNumber:legacy.Monster;
    const treasures=dice?$('setting-deck_treasures'+zone).valueAsNumber:legacy.Treasure;
    const nothing=50-monsters-treasures-legacy.Item;
    row.textContent=nothing>=0
      ? `Zone ${zone} · Monster × ${monsters} · Treasure × ${treasures} · Nothing × ${nothing} · Item × ${legacy.Item}`
      : `Zone ${zone} · Monster and Treasure counts must leave room for ${legacy.Item} Item cards.`;
    const exact=exactTreasureProfiles[zone];
    const exactLine=$('exact-deck-'+zone);
    exactLine.hidden=!dice||!exact;
    if(dice&&exact)exactLine.firstElementChild.textContent='Exact treasure · '+Object.entries(exact).map(([gold,count])=>`${count} × ${gold}g`).join(' · ');
  }
  const cap=$('setting-cap');
  if(cap){
    cap.max=dice?10:limits.cap[1];
    const slider=$('slider-cap');
    if(slider)slider.max=cap.max;
  }
  try{
    const s=readSettings();
    const changed=!result||Object.keys(s).some(k=>k==='treasure_profiles'
      ? JSON.stringify(s[k])!==JSON.stringify(result.settings[k]??{}) : s[k]!==result.settings[k])
      || JSON.stringify(readMap())!==JSON.stringify(result.board.layout);
    $('dirty').textContent=changed?'Run to apply changes.':'Results are up to date.';
    const mode=dice?'Dice rules':shared?'Earlier shared decks':'Earlier independent draws';
    $('mode-summary').textContent=`${mode} · ${s.players} players · ${s.turns} rounds`;
    renderRules(s);
  }catch(e){$('dirty').textContent=e.message;}
}
function setSettings(s){
  if(Object.hasOwn(s,'treasure_profiles'))exactTreasureProfiles=structuredClone(s.treasure_profiles??{});
  for(const [key,{number,slider}]of controls){
    if(!(key in s))continue;
    number.max=Math.max(limits[key][1],s[key]);number.value=s[key];
    if(slider){slider.max=Math.max(Number(slider.max),s[key]);slider.value=s[key];}
  }
  markDirty();
}
function buildSettings(){
  const decks=$('zone-deck-spec');
  for(const zone of Object.keys(config.zone_decks)){
    const line=document.createElement('p');
    line.id='zone-deck-'+zone;
    decks.append(line);
    const exact=document.createElement('div');
    exact.id='exact-deck-'+zone;
    exact.className='button-row small';
    exact.hidden=true;
    const clear=document.createElement('button');
    clear.type='button';
    clear.textContent='Use range';
    clear.onclick=()=>{delete exactTreasureProfiles[zone];markDirty();};
    exact.append(document.createElement('span'),clear);
    decks.append(exact);
  }
  const items=document.createElement('dl');
  for(const [name,effect] of Object.entries(config.items)){
    const label=document.createElement('dt'),detail=document.createElement('dd');
    label.textContent=name;detail.textContent=effect;
    if(name==='Coupon')detail.id='shop-coupon-description';
    if(name==='Speed Potion')detail.id='speed-potion-description';
    items.append(label,detail);
  }
  decks.append(items);
  for(const [item,gear] of Object.entries(config.gear)){
    limits[gear.price] ??= [0,30,1];
    limits[gear.enabled] ??= [0,1,1];
    help[gear.price]=gear.effect;
    help[gear.enabled]='Allow the simulated player to buy '+item+'.';
  }
  help.gear_slots='Permanent gear occupies a slot. Potions use a separate inventory.';
  help.gear_priority='Sets which items shoppers prefer. Mining and deep policies also weigh prices. Mixed shoppers vary preferences across players.';
  help.potion_chance='Roll a separate chance after each encounter card, including both cards when farming.';
  help.deep_entry_tonic='Each player finds one Energy Tonic on their first discovery at the Zone 3 gate.';
  help.deep_tonic_energy='Energy restored when using the entrance Tonic, limited by the cap.';
  help.farm_shared_limit='Shared uses per site per round, in addition to the personal limit of one. Zero keeps only the personal limit.';
  help.boots_move_range='Maximum squares per 1-Energy Move with Boots. Speed Potion doubles this range.';
  help.shield_block_per_level='Energy blocked on each surviving monster’s counterattack per Shield level.';
  help.shared_decks='Players draw from the same shuffled deck in each zone. Set to 0 for the earlier independent encounter model.';
  help.dice_rules='Mine to draw. Fight with dice and bank on arriving at the Surface Exit. Requires shared zone decks.';
  help.zone2_start+=' Dice rules open all zones in round 1.';
  help.zone3_start+=' Dice rules open all zones in round 1.';
  help.mine_cost+=' In dice mode this also sets the cost of clearing an adjacent rock.';
  help.max_zone='Limit how deep this strategy will go. Retreat timing is set separately.';
  const groupOrder=['Game','Dice rules','Zone decks','Energy','Equipment','Potions','Farming','Boss','Strategy','Monsters','Knockdown','Rewards','Cards'];
  for(const group of groupOrder){
    const details=document.createElement('details');details.dataset.group=group;details.open=['Game','Energy'].includes(group);
    const summary=document.createElement('summary');summary.textContent=({'Dice rules':'Dice combat and decks','Zone decks':'Items and upgrades','Farming':'Mining','Strategy':'Bot behavior'})[group]||group;details.append(summary);
    for(const [g,key,originalLabel]of config.fields.filter(f=>f[0]===group)){
      const label=({'turns':'Rounds','players':'Players','runs':'Games','seed':'Seed','boots_price':'Boots price'})[key]||originalLabel;
      labels[key]=label;
      const [min,max,step]=limits[key];
      const field=document.createElement('div');field.className='field';
      if(key==='gear_priority'){
        const select=document.createElement('select');
        select.id='setting-'+key;
        select.setAttribute('aria-label',label);
        priorities.forEach((name,i)=>select.add(new Option(name,i)));
        field.innerHTML='<label for="setting-gear_priority">Shopping priority</label><p class="field-help">'+help[key]+'</p>';
        field.insertBefore(select,field.lastChild);
        select.onchange=markDirty;
        controls.set(key,{number:select,slider:null});
        details.append(field);
        continue;
      }
      field.innerHTML=`<div class="field-head"><label for="setting-${key}">${esc(label)}</label><input id="setting-${key}" type="number" required min="${min}" max="${max}" step="${step}" value="${config.defaults[key]}" aria-describedby="help-${key}"></div>${key==='seed'||key==='runs'?'':`<input id="slider-${key}" type="range" min="${min}" max="${max}" step="${step}" value="${config.defaults[key]}" aria-label="${esc(label)} slider">`}<p id="help-${key}" class="field-help">${help[key]||''}</p>`;
      details.append(field);
      const number=field.querySelector('input[type=number]'),slider=field.querySelector('input[type=range]');
      number.addEventListener('input',()=>{if(slider)slider.value=number.value;markDirty();});
      if(slider)slider.addEventListener('input',()=>{number.value=slider.value;markDirty();});
      controls.set(key,{number,slider});
    }
    $('settings').append(details);
  }
  $('settings').onsubmit=e=>{e.preventDefault();simulate();};
}
async function request(path,data){
  const r=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const body=await r.json();if(!r.ok)throw Error(body.error||`Request failed (${r.status})`);return body;
}
function setBusy(value){
  busy=value;['run','search','reset','add-range','load-settings','gear-original','gear-tuned','run-map','watch-map','run-route-study','load-escape-setup','run-ev','strategy-load','ruleset'].forEach(id=>$(id).disabled=value);
  $('strategy-run').disabled=value||$('ruleset').value!=='dice';
  $('run-preset-search').disabled=value||$('ruleset').value!=='dice';
  $('cave-preset').disabled=value||!caveBalance;
  document.querySelectorAll('.apply-candidate').forEach(e=>e.disabled=value);
  $('activity').hidden=!value;
  if(typeof updateLargeStudyControls==='function')updateLargeStudyControls();
}
async function job(kind,payload,onStart){
  if(busy)throw Error('Wait for the current experiment or cancel it first.');
  const phases={search:'Starting target search',presets:'Starting preset search',study:'Starting route comparison',audit:'Starting +EV audit',balance:'Starting matched strategy study','large-study':'Starting Large Study'};
  setBusy(true);notice('');$('phase').textContent=phases[kind]??'Simulating expeditions';$('progress').removeAttribute('value');$('progress-text').textContent='';
  try{
    const created=await request('/api/'+kind,payload);activeJob=created.id;
    onStart?.(created);
    while(true){
      await new Promise(resolve=>setTimeout(resolve,250));
      const status=await request('/api/jobs/'+activeJob);
      if(status.state==='complete')return status.result;
      if(status.state==='error')throw Error(status.error);
      if(status.state==='cancelled')throw Error(kind==='large-study'?'Study paused. Resume it from Saved study.':'Experiment cancelled. Previous results are preserved.');
      const p=status.progress;$('phase').textContent=p.phase;
      if(p.total>1){$('progress').value=100*p.done/p.total;$('progress-text').textContent=`${p.done} / ${p.total}`;}
    }
  }finally{activeJob=null;$('cancel').textContent='Cancel experiment';setBusy(false);}
}
$('cancel').onclick=async()=>{if(activeJob){$('cancel').disabled=true;try{await request('/api/cancel',{id:activeJob});}catch(e){notice(e.message,true);}finally{$('cancel').disabled=false;}}};
async function simulate(){
  if(busy)return false;
  stopReplay();
  try{
    const settings=readSettings();
    const next=await job('simulate',{settings,board:readMap()});
    previous=result;result=next;renderResults();markDirty();
    notice('');
    return true;
  }catch(e){notice(e.message,true);return false;}
}
$('run').onclick=simulate;
function applyTestPreset(){
  setSettings({...config.legacy_defaults,...testPreset.settings});
  setMap(testPreset.board,'test');
}
$('reset').onclick=()=>{applyTestPreset();notice('Test preset loaded. Run to refresh results.');};
$('ruleset').onchange=()=>{
  const mode=$('ruleset').value;
  if(mode==='dice'){
    applyTestPreset();
  }else{
    const shared=mode==='decks';
    const {seed,runs,players,turns}=readSettings();
    setSettings({...config.legacy_defaults,seed,runs,players,turns,
      ...(shared?{shared_decks:1,dark_cost:1,rough_cost:1,potion_chance:0}:{}),
      zone2_start:Math.min(turns+1,config.legacy_defaults.zone2_start),
      zone3_start:Math.min(turns+1,config.legacy_defaults.zone3_start),
      retreat_start:Math.min(turns,config.legacy_defaults.retreat_start)});
  }
  notice('Ruleset loaded. Run to refresh results.');
};

let strategyStudy;
const percent=(value)=>value==null?'—':fmt(value*100)+'%';
function rangeText(ci, format=fmt){
  return ci[0]==null?'—':`${format(ci[0])} to ${format(ci[1])}`;
}
const signedScore=(score)=>score==null?'—':(score>0?'+':'')+fmt(score,2);

function scoreCell(score, ci, format=fmt){
  return `${format(score)}<small>95% ${rangeText(ci,format)}</small>`;
}
function funnelCell(stage, last=false){
  const round=last||stage.round==null?'':` · round ${fmt(stage.round)}`;
  return `<progress class="route-progress" max="1" value="${stage.rate}" aria-label="${percent(stage.rate)}"></progress><small>${percent(stage.rate)} · ${stage.count} seats${round}</small>`;
}
function goalLabel(tile){
  return `(${tile[0]}, ${tile[1]})`;
}
function renderStrategyStudy(){
  const comparison=strategyStudy.comparisons[Number($('strategy-lineup').value)];
  const fixed=comparison.fixed;
  const adaptive=comparison.adaptive;
  const policy=$('strategy-funnel-policy').value;
  const middle=fixed[1].score>fixed[0].score && fixed[0].score>fixed[2].score;
  const deepUpside=fixed.every(row=>row.winning_score!=null) &&
    fixed[2].winning_score>Math.max(fixed[0].winning_score,fixed[1].winning_score);
  $('strategy-context').textContent=`${strategyStudy.games} matched games per policy · seed ${strategyStudy.seed} · ${strategyStudy.rounds} rounds · ${strategyStudy.whole_moves?'whole-Energy moves':'adjacent moves'} · ${strategyStudy.gold_shops?'gold':'card-count'} prices`;
  $('strategy-verdict').textContent=
    `Fixed baseline: ${middle?'Zone 1 is in the middle by average score.':'The average-score order differs from the Zone 2 → Zone 1 → Zone 3 target.'} ${deepUpside?'Zone 3 has the highest average winning score.':'Zone 3’s winning-score advantage was not observed.'}`;
  $('strategy-score-rows').innerHTML=fixed.map((row,i)=>{
    const peer=adaptive[i];
    return `<tr><td>${esc(row.route)}<small>${row.players} seat results per policy</small></td><td>${scoreCell(row.score,row.score_ci)}</td><td>${scoreCell(peer.score,peer.score_ci)}</td><td>${scoreCell(peer.delta,peer.delta_ci,signedScore)}</td><td>${percent(row.win)} / ${percent(peer.win)}<small>95% ${rangeText(row.win_ci,percent)} / ${rangeText(peer.win_ci,percent)}</small></td><td>${row.p90} / ${peer.p90}</td><td>${fmt(row.winning_score)} / ${fmt(peer.winning_score)}</td></tr>`;
  }).join('');
  $('strategy-funnel-rows').innerHTML=comparison[policy].map(row=>
    `<tr><td>${esc(row.route)}<small>${percent(row.escaped)} finished on Surface overall</small></td>${['entered','mined','banked','surface'].map(stage=>`<td>${funnelCell(row.funnel[stage],stage==='surface')}</td>`).join('')}</tr>`
  ).join('');
  const reasons=Object.entries(comparison.switch_reasons).sort((a,b)=>b[1]-a[1]);
  $('strategy-reasons').textContent=reasons.length
    ? reasons.map(([reason,count])=>`${reason} (${count})`).join(' · ')
    : 'No goal changes recorded in this lineup.';
  $('strategy-decision-rows').innerHTML=comparison.examples.map(row=>
    `<tr><td>${row.seed} · ${row.seat} · ${row.round}</td><td>${goalLabel(row.before)}</td><td>${goalLabel(row.after)}</td><td>${esc(row.reason)}</td></tr>`
  ).join('');
  $('strategy-gear-rows').innerHTML=strategyStudy.gear.map(row=>{
    const direct=row.item==='Boots'?`${fmt(row.boots_saved,2)} walking`:row.item==='Shield'?`${fmt(row.shield_saved,2)} blocked`:'—';
    return `<tr><td>${esc(row.route)} · ${esc(row.item)}</td><td>${percent(row.buy_rate)}<small>${row.buy_round==null?'—':`round ${fmt(row.buy_round)}`}</small></td><td>${fmt(row.gold_paid,2)}</td><td>${direct}<small>${signedScore(row.combat_energy_saved)} combat Energy saved per attempt</small></td><td>${signedScore(row.score_delta)}<small>${fmt(row.score,2)} vs ${fmt(row.control_score,2)} · 95% ±${fmt(row.delta_margin_95,2)}</small></td><td>${percent(row.win)} vs ${percent(row.control_win)}</td></tr>`;
  }).join('');
}
$('strategy-load').onclick=()=>{applyTestPreset();notice('Five-seat test preset loaded.');};
$('strategy-run').onclick=async()=>{
  try{
    const games=$('strategy-games');
    if(!games.checkValidity())throw Error('Enter 5–200 games per lineup.');
    strategyStudy=await job('balance',{settings:readSettings(),board:readMap(),balance:{games:games.valueAsNumber}});
    $('strategy-lineup').replaceChildren(...strategyStudy.comparisons.map((row,i)=>new Option(row.label,i)));
    $('strategy-results').hidden=false;
    $('strategy-export').disabled=false;
    renderStrategyStudy();
  }catch(e){notice(e.message,true);}
};
$('strategy-lineup').onchange=renderStrategyStudy;
$('strategy-funnel-policy').onchange=renderStrategyStudy;
$('strategy-export').onclick=()=>
  download('strategy-balance.json',JSON.stringify(strategyStudy,null,2),'application/json');

function metricCard(label,value,detail,featured=false,secondary=false){return `<article class="metric${featured?' featured':''}${secondary?' secondary':''}"><p class="label">${label}</p><p class="value">${value}</p><p class="detail">${detail}</p></article>`;}
function renderZoneActivity(development, players, games, shared) {
  const fields=['Zone','Entered','Entry round','Mined','First mine round'];
  if(shared)fields.push('Drawn / game','P95 drawn','Left / game','Empty decks');
  $('zone-head').innerHTML='<tr>'+fields.map(label=>`<th scope="col">${label}</th>`).join('')+'</tr>';
  $('zone-activity').innerHTML=development.zones.map(zone=>{
    const row=[`Zone ${zone.zone}`,percent(zone.entered/players),fmt(zone.entry_round),
      percent(zone.mined/players),fmt(zone.mine_round)];
    if(shared)row.push(fmt(zone.draws),fmt(zone.p95_draws,0),fmt(zone.left),`${zone.exhausted} / ${games}`);
    return `<tr>${row.map(value=>`<td>${value}</td>`).join('')}</tr>`;
  }).join('');
  $('zone-note').textContent=shared
    ? 'Rounds are averages among players who reached the milestone. P95 drawn is the 95th percentile across games. Each deck starts with 50.'
    : 'Rounds are averages among players who reached the milestone.';
}
function renderEquipment(development, settings, players) {
  $('go-strategy').hidden=!settings.dice_rules;
  if(settings.dice_rules){
    $('equipment-head').innerHTML='<tr><th>Item</th><th>Bought</th><th>Used</th><th>First purchase</th><th>Gold paid</th></tr>';
    $('equipment-chart').innerHTML=development.gear.map(item=>
      `<tr><td>${esc(item.item)}</td><td>${percent(item.bought/players)}</td><td>${percent(item.used/players)}</td><td>${item.round==null?'—':'Round '+fmt(item.round)}</td><td>${fmt(item.gold)}</td></tr>`
    ).join('');
    return;
  }
  $('equipment-head').innerHTML='<tr><th>Item</th><th>Listed price</th><th>Owned</th><th>Used</th></tr>';
  $('equipment-chart').innerHTML=result.equipment_rates.map(item=>
    `<tr><td>${esc(item.label)}</td><td>${settings[config.gear[item.label].price]}</td><td>${fmt(item.percent)}%</td><td>${fmt(item.used_percent)}%</td></tr>`
  ).join('');
}
function renderResults(){
  const {metrics:m,development:d,settings:s}=result;
  const {scored,surface_zero,underground,boss}=d.outcomes;
  const players=m.player_runs;
  $('metrics').innerHTML=[
    metricCard('Score per player',fmt(m.avg_score,2),`95% ${rangeText(m.score_ci,value=>fmt(value,2))} · zeros included`,true),
    metricCard('Finished on Surface',percent((scored+surface_zero)/players),`${underground} stranded · ${boss} killed by boss`),
    metricCard('First deposit',d.first_bank_median==null?'—':`Round ${fmt(d.first_bank_median,Number.isInteger(d.first_bank_median)?0:1)}`,'Median among players who banked'),
    metricCard('Finished with gold',percent(scored/players),`${surface_zero} finished on Surface with zero gold`),
  ].join('');
  const mode=s.dice_rules?'Dice':s.shared_decks?'Shared decks':'Independent draws';
  $('run-info').textContent=`${fmt(m.games,0)} games × ${s.players} players · ${s.turns} rounds · seed ${s.seed} · ${mode} · default bots`;
  $('deck-item-stats').textContent=Object.entries(m.item_counts??{})
    .filter(([,count])=>count>0).map(([name,count])=>name+' ×'+count).join(' · ');
  const drawn=Object.values(m.card_counts).reduce((sum,count)=>sum+count,0);
  $('card-stats').innerHTML=Object.entries(m.card_counts).map(([name,count])=>
    `<tr><td>${esc(name)}</td><td>${fmt(count,0)}</td><td>${drawn?percent(count/drawn):'—'}</td></tr>`
  ).join('');
  $('potion-stats').innerHTML=result.potion_rates.filter(item=>item.found||item.used).map(item=>
    `<tr><td>${esc(item.label)}</td><td>${fmt(item.found,0)}</td><td>${fmt(item.used,0)}</td></tr>`
  ).join('')||'<tr><td colspan="3">No potions found or used.</td></tr>';
  const costs=[
    ['Walking Energy',d.energy.walking],['Mining Energy',d.energy.mining],
    ['Combat Energy',d.energy.combat],['Collapse Energy',d.energy.collapse],
    ['Gold spent at shops',m.avg_equipment_spent],['Gold lost to knockdowns',m.avg_loot_penalty],
    ['Gold lost to collapse',m.avg_boss_loot_penalty],['Gold stranded in hand',m.avg_unbanked],
    ['Banked gold disqualified',d.unqualified_bank],
  ];
  $('budget-rows').innerHTML=costs.map(([label,value])=>`<tr><th scope="row">${label}</th><td>${fmt(value,2)}</td></tr>`).join('');
  renderZoneActivity(d,players,Math.ceil(m.games),s.shared_decks);
  renderEquipment(d,s,players);
  renderMapComparison();
  renderRouteDiagnostics();
  barChart('score-chart',result.histogram.map(h=>({label:h.low===h.high?String(h.low):`${h.low}–${h.high}`,value:h.count})),{unit:'Players',color:'#527c68'});
  lineChart('escape-chart',d.first_bank_timeline.map((count,i)=>({x:i+1,y:100*count/players})),{unit:'Players who banked (%)',max:100,color:'#527c68',xLabel:'Round'});
  lineChart('energy-chart',result.timeline.map(p=>({x:p.turn,y:p.energy})),{unit:'Mean Energy',max:s.cap,color:'#7393a0',xLabel:'Round'});
  barChart('collapse-chart',result.collapse_rates.map(p=>({label:`Zone ${p.zone}`,value:p.percent})),{unit:'Games (%)',max:100,color:'#b35d43'});
  $('boss-example').innerHTML=result.boss_example.filter(e=>e.die).map(e=>{
    const event=e.collapse===1?'Entrance sealed':e.collapse?`Zone ${e.collapse} collapsed`:`Held in Zone ${e.threatened}`;
    return `<span class="boss-event"><b>Round ${e.turn} · ${e.die}</b><br>${event}</span>`;
  }).join('')||'No boss rolls.';
  $('run-comparison').hidden=!previous;
  if(previous){
    const rows=[['Score per player','avg_score',2,''],['Finished on Surface','escape_rate',1,'%'],['Reached Zone 3','zone3_rate',1,'%'],['Gold spent per player','avg_equipment_spent',2,''],['Knockdowns per player','avg_knockdowns',2,'']];
    $('compare-previous').textContent=`Previous · seed ${previous.settings.seed}`;
    $('compare-current').textContent=`Current · seed ${s.seed}`;
    $('compare-rows').innerHTML=rows.map(([label,key,digits,unit])=>`<tr><th scope="row">${label}</th><td>${fmt(previous.metrics[key],digits)}${unit}</td><td>${fmt(m[key],digits)}${unit}</td></tr>`).join('');
  }
  $('sample-picker').innerHTML=result.samples.map((p,i)=>`<option value="${i}">Game ${p.game}, player ${p.player} · ${p.score} gold · ${playerOutcome(p)}</option>`).join('');
  $('export-results').disabled=!result.players.length;
  renderSample();
}
function plotFrame(unit,max){
  const W=520,H=230,L=48,R=15,T=22,B=40,PW=W-L-R,PH=H-T-B;
  let content=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(unit)} chart"><text x="${L}" y="11" class="axis-label">${esc(unit)}</text>`;
  for(let i=0;i<=4;i++){const y=T+PH-i*PH/4;content+=`<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#e8e9e0"/><text x="${L-8}" y="${y+3}" text-anchor="end">${fmt(max*i/4,max>10?0:1)}</text>`;}
  return {content,W,H,L,R,T,B,PW,PH};
}
function barChart(id,data,{unit,max,color}){
  max=max||Math.max(1,...data.map(d=>d.value))*1.1;
  const f=plotFrame(unit,max);let svg=f.content;
  const width=f.PW/data.length;
  data.forEach((d,i)=>{const x=f.L+i*width+width*.17,h=d.value/max*f.PH,y=f.T+f.PH-h;
    svg+=`<rect x="${x}" y="${y}" width="${width*.66}" height="${h}" rx="3" fill="${color}"><title>${esc(d.label)}: ${fmt(d.value,unit.includes('%')?1:0)} ${esc(unit)}</title></rect>`;
    if(data.length<=6||i%2===0)svg+=`<text x="${x+width*.33}" y="${f.T+f.PH+20}" text-anchor="middle">${esc(d.label)}</text>`;
    if(d.value&&data.length<=6)svg+=`<text x="${x+width*.33}" y="${Math.max(f.T+5,y-6)}" text-anchor="middle">${fmt(d.value,unit.includes('%')?1:0)}${unit.includes('%')?'%':''}</text>`;
  });
  $(id).innerHTML=svg+'</svg>';
}
function lineChart(id,data,{unit,max,color,target=null,dots=false,xLabel='Round'}){
  const valid=data.filter(p=>p.y!==null);
  max=Math.max(max||0,1,...valid.map(p=>p.y),target||0)* (max?1:1.12);
  const f=plotFrame(unit,max);let svg=f.content;
  const xmax=Math.max(2,...data.map(p=>p.x)),xmin=Math.min(1,...data.map(p=>p.x));
  const px=x=>f.L+(x-xmin)/(xmax-xmin)*f.PW,py=y=>f.T+f.PH-y/max*f.PH;
  if(target!==null)svg+=`<line x1="${f.L}" y1="${py(target)}" x2="${f.W-f.R}" y2="${py(target)}" stroke="#b35d43" stroke-dasharray="5 4"/><text x="${f.W-f.R}" y="${py(target)-5}" text-anchor="end">Target ${fmt(target)}</text>`;
  if(!dots){let segment=[];const flush=()=>{if(segment.length)svg+=`<polyline points="${segment.join(' ')}" fill="none" stroke="${color}" stroke-width="2.5"/>`;segment=[];};for(const p of data){if(p.y===null)flush();else segment.push(`${px(p.x)},${py(p.y)}`);}flush();}
  for(const p of valid)svg+=`<circle cx="${px(p.x)}" cy="${py(p.y)}" r="${dots?3.5:2.4}" fill="${color}" opacity=".85"><title>${dots?'Candidate':'Turn'} ${p.x}: ${fmt(p.y,2)} ${esc(unit)}</title></circle>`;
  for(let i=0;i<=4;i++){const x=xmin+(xmax-xmin)*i/4;svg+=`<text x="${px(x)}" y="${f.T+f.PH+20}" text-anchor="middle">${fmt(x,0)}</text>`;}
  svg+=`<text class="axis-label" x="${f.W-f.R}" y="${f.H-3}" text-anchor="end">${dots?'Candidate':esc(xLabel)}</text>`;
  $(id).innerHTML=svg+'</svg>';
}
function addRange(name='retreat_start',low=5,high=14,step=1,checked=true){
  const row=document.createElement('div');row.className='range-row';
  row.innerHTML=`<input type="checkbox" ${checked?'checked':''} aria-label="Include this rule in search"><label>Rule<select class="range-name"></select></label><label>Min<input type="number" class="range-min" value="${low}" step="1"></label><label>Max<input type="number" class="range-max" value="${high}" step="1"></label><label>Step<input type="number" class="range-step" value="${step}" min="1" step="1"></label><button class="remove-range" aria-label="Remove this search rule">×</button>`;
  const select=row.querySelector('select');
  const groups=new Map();
  for(const key of config.tunable){
    const group=controls.get(key).number.closest('details').dataset.group;
    if(!groups.has(group))groups.set(group,[]);
    groups.get(group).push(key);
  }
  for(const [name,keys] of [...groups].sort(([a],[b])=>a.localeCompare(b))){
    const group=document.createElement('optgroup');
    group.label=name;
    group.append(...keys.sort((a,b)=>labels[a].localeCompare(labels[b])).map(k=>new Option(labels[k],k)));
    select.append(group);
  }
  select.value=name;
  row.querySelector('.remove-range').onclick=()=>row.remove();
  select.onchange=e=>{const n=e.target.value,cur=Math.round(Number(controls.get(n).number.value)),bounds=limits[n];row.querySelector('.range-min').value=Math.max(Math.ceil(bounds[0]),cur-2);row.querySelector('.range-max').value=Math.min(Math.floor(bounds[1]),cur+2);};
  $('ranges').append(row);
}
$('add-range').onclick=()=>{if($('ranges').children.length>=4)return notice('Use at most four search rules.',true);addRange('boots_price',1,6);markDirty();};
function refreshTargetMetrics(dice,shared){
  const select=$('target-metric');
  if(!config?.target_details||!select.options.length)return;
  for(const option of select.options){
    const requires=config.target_details[option.value].requires;
    option.disabled=requires==='dice'&&!dice||requires==='shared'&&!shared;
    option.hidden=option.disabled;
  }
  for(const group of select.querySelectorAll('optgroup'))group.hidden=[...group.children].every(option=>option.disabled);
  if(select.selectedOptions[0]?.disabled){
    select.value='escape_rate';
    select.onchange();
  }
}
function buildManualSearch(){
  const select=$('target-metric'),groups=new Map();
  for(const [metric,detail] of Object.entries(config.target_details)){
    if(!groups.has(detail.group)){
      const group=document.createElement('optgroup');
      group.label=detail.group;
      groups.set(detail.group,group);
      select.append(group);
    }
    const [label,unit]=config.metrics[metric];
    groups.get(detail.group).append(new Option(`${label} (${unit})`,metric));
  }
  select.onchange=()=>{
    const detail=config.target_details[select.value];
    const [,unit,min,max]=config.metrics[select.value];
    $('target-value').value=detail.target;
    $('target-value').min=min;
    $('target-tolerance').value=detail.tolerance;
    $('target-direction').value=detail.mode;
    $('target-help').textContent=detail.help||`Tolerance uses ${unit==='%'?'percentage points':unit}.`;
    if(max===null)$('target-value').removeAttribute('max');else $('target-value').max=max;
  };
  select.value='escape_rate';
  select.onchange();
}
$('search').onclick=async()=>{
  try{
    const settings=readSettings(),ranges={};
    for(const row of $('ranges').children){
      if(!row.querySelector('[type=checkbox]').checked)continue;
      const select=row.querySelector('.range-name');
      if(select.selectedOptions[0]?.disabled)throw Error('Choose an active rule. To vary a zone’s Treasure count or range, clear its exact-value profile in Rules first.');
      const name=select.value;
      if(name in ranges)throw Error('Choose each search rule only once.');
      const values=[...row.querySelectorAll('input[type=number]')];
      if(values.some(v=>v.value===''||!v.checkValidity()))throw Error('Each range needs valid minimum, maximum and step values.');
      ranges[name]={min:Number(values[0].value),max:Number(values[1].value),step:Number(values[2].value)};
    }
    const ids=['target-value','target-tolerance','candidate-budget','candidate-trials','confirmation-trials'];
    for(const id of ids)if($(id).value===''||!$(id).checkValidity())throw Error('Check the target and sample-size values.');
    const search={metric:$('target-metric').value,mode:$('target-direction').value,target:Number($('target-value').value),tolerance:Number($('target-tolerance').value),budget:Number($('candidate-budget').value),trials:Number($('candidate-trials').value),confirmation:Number($('confirmation-trials').value),ranges};
    searchResult=await job('search',{settings,search,board:readMap()});renderSearch();notice('Target search finished. Review the fresh-seed estimates before applying a result.');
  }catch(e){notice(e.message,true);}
};
function renderSearch(){
  const s=searchResult,unit=config.metrics[s.metric][1];
  const measured=s.recommendations.some(row=>row.validation_value!==null);
  const trialUnit=s.settings.shared_decks?'matches':'players';
  const sample=stats=>fmt(stats[s.settings.shared_decks?'games':'player_runs'],0);
  const validationNote=s.validation_baseline?` · Fresh baseline ${fmt(s.validation_baseline[s.metric],2)} ${unit} (${sample(s.validation_baseline)} ${trialUnit})`:'';
  $('search-results').hidden=false;
  $('search-outcome').textContent=s.matched?'Found settings within your tolerance.':measured?'Closest tested result fell outside the target.':'No finalist produced a measurable result.';
  $('search-meta').textContent=`Tested ${s.searched} of ${fmt(s.possible,0)} combinations · ${sample(s.baseline)} ${trialUnit} per candidate · ${s.recommendations.length} checked on fresh seeds${validationNote}${s.skipped?` · ${s.skipped} skipped: ${s.first_problem}`:''}`;
  lineChart('candidate-chart',s.candidates.map((r,i)=>({x:i+1,y:r.value})),{unit:config.metrics[s.metric][0]+` (${unit})`,color:'#527c68',target:s.target,dots:true});
  $('recommendations').innerHTML=s.recommendations.map((r,i)=>{
    const ci=s.metric==='escape_rate'?r.validation.escape_ci:s.metric==='avg_score'?r.validation.score_ci:null;
    const available=r.validation_value!==null;
    return `<tr><td>${Object.entries(r.changes).map(([k,v])=>`${esc(labels[k])} <b>${v}</b>`).join('<br>')}</td><td>${fmt(r.value,2)} ${esc(unit)}</td><td><b>${available?`${fmt(r.validation_value,2)} ${esc(unit)}`:'No observation'}</b>${ci?`<small>95% interval ${fmt(ci[0],2)}–${fmt(ci[1],2)}</small>`:''}<small>${sample(r.validation)} ${trialUnit} · Surface ${fmt(r.validation.escape_rate)}% · Score ${fmt(r.validation.avg_score,2)} · Zone 3 mined and qualified ${fmt(r.validation.zone3_bank_rate)}%</small></td><td>${available?`${fmt(r.validation_error,2)} ${esc(unit)}`:'—'}${available&&r.validation_error<=s.tolerance?'<small class="pill">Within tolerance</small>':''}</td><td><button class="apply-candidate" data-candidate="${i}">Apply & run</button></td></tr>`;
  }).join('');
  document.querySelectorAll('#recommendations .apply-candidate').forEach(button=>button.onclick=async()=>{
    const row=searchResult.recommendations[Number(button.dataset.candidate)];
    setMap(searchResult.board);setSettings({...searchResult.settings,...row.changes});tab('overview');await simulate();
  });
}
function presetSelection(){
  const [,variants,objective]=config.search_presets[$('search-preset').value];
  $('preset-variants').textContent=variants;
  $('preset-objective').textContent=objective;
}
function describePresetCandidate(row,baseline){
  const settings=Object.entries(row.changes).map(([k,v])=>`${esc(labels[k])} ${fmt(v,0)}`);
  if(settings.length)return settings.join('<br>');
  const moves=[];
  row.board.rows.forEach((line,y)=>Array.from(line).forEach((mark,x)=>{
    const old=baseline.board.rows[y][x];
    if(old!==mark)moves.push(`(${x+1}, ${y+1}) ${old} → ${mark}`);
  }));
  return esc(row.label)+(moves.length?`<small>${moves.map(esc).join(' · ')}</small>`:'');
}
function renderPresetResult(result){
  const {baseline,finalists}=result;
  $('preset-results').hidden=false;
  $('preset-outcome').textContent=config.search_presets[result.preset][0];
  $('preset-meta').textContent=`${result.screened} setups screened at ${result.screening_games} games per matchup. Current setup and ${finalists.length} finalists checked on ${result.holdout_games} fresh games per matchup starting at seed ${result.validation_seed}.`;
  $('preset-ranks').innerHTML=[baseline,...finalists].map((row,i)=>{
    const delta=row.holdout.penalty-baseline.holdout.penalty;
    const signed=(delta>0?'+':'')+fmt(delta,3);
    return `<tr><td>${describePresetCandidate(row,baseline)}</td><td>${fmt(row.screening.penalty,3)}</td><td>${fmt(row.holdout.penalty,3)}</td><td>${i?signed:'—'}</td><td>${i?`<button type="button" class="apply-candidate" data-finalist="${i-1}">Apply &amp; run</button>`:'—'}</td></tr>`;
  }).join('');
  $('preset-ranks').querySelectorAll('[data-finalist]').forEach(button=>button.onclick=async()=>{
    const row=finalists[Number(button.dataset.finalist)];
    setMap(row.board);
    setSettings({...result.settings,...row.changes});
    tab('overview');
    await simulate();
  });
  $('preset-all-screened').innerHTML=[...result.screening].sort((a,b)=>a.penalty-b.penalty)
    .map(row=>`<tr><td>${describePresetCandidate(row,baseline)}</td><td>${fmt(row.penalty,3)}</td></tr>`).join('');
  const picker=$('preset-detail-picker');
  picker.replaceChildren(...finalists.map((row,i)=>new Option(
    `Finalist ${i+1} · ${Object.entries(row.changes).map(([k,v])=>`${labels[k]} ${v}`).join(', ')||row.label}`,i)));
  picker.onchange=()=>renderPresetDetails(baseline,finalists[Number(picker.value)]);
  picker.onchange();
}
function renderPresetDetails(baseline,candidate){
  const pair=(i)=>[baseline.holdout.scenarios[i],candidate.holdout.scenarios[i]];
  const title=s=>`${s.adaptive?'Adaptive':'Fixed'} · ${s.label}`;
  const joined=(values,format)=>values.map(value=>format(value)).join(' / ');
  $('preset-route-details').innerHTML=baseline.holdout.scenarios.map((_,i)=>
    pair(i).map((s,j)=>`<tr><td>${j?'':esc(title(s))}</td><td>${j?'Finalist':'Current'}</td><td>${joined(s.routes.map(r=>r.score),fmt)}</td>
      <td>${joined(s.routes.map(r=>r.win),percent)}</td><td>${joined(s.actual_mined,percent)}</td>
      <td>${percent(s.routes[2].funnel.banked.rate)}</td><td>${fmt(s.routes[2].winning_score)}</td></tr>`).join('')).join('');
  $('preset-extra-details').innerHTML=baseline.holdout.scenarios.map((_,i)=>{
    const [base,trial]=pair(i);
    const data=[
      ['Zone 2 score spread (standard deviation)', s=>fmt(s.score_spread2)],
      ['Zone 2 banked after mining', s=>percent(s.routes[1].funnel.banked.rate)],
      ['Zone 1 farm uses per seat', s=>fmt(s.shallow_farm,2)],
      ['All farm uses per seat', s=>fmt(s.farm,2)],
      ['Regular mines per seat (Z1 / Z2 / Z3)', s=>joined(s.mines,n=>fmt(n,2))],
      ['95th-percentile cards drawn (Z1 / Z2 / Z3)', s=>s.p95_draws.join(' / ')],
      ['Deck exhausted (Z1 / Z2 / Z3)', s=>joined(s.depleted,percent)],
      ['Bought Boots / Sword / Shield', s=>joined(Object.values(s.buyers),percent)],
      ['Moves extended by Boots per seat', s=>fmt(s.long_boot_moves,2)],
      ['Bonus Sword damage per seat', s=>fmt(s.sword_damage,2)],
      ['Energy blocked by Shields per seat', s=>fmt(s.shield_block,2)],
      ['Shop spend per seat', s=>fmt(s.spend,2)],
      ['Knockdowns per seat', s=>fmt(s.knockdowns,2)],
      ['Energy spent on combat per seat', s=>fmt(s.combat_energy,2)],
      ['Boss ejections per seat', s=>fmt(s.ejections,2)],
      ['At least one collapse', s=>percent(s.collapse)],
      ['Estimated mean minutes per match', s=>fmt(s.minutes)],
      ['Estimated 95th-percentile seconds per turn', s=>fmt(s.p95_turn,0)],
    ];
    return `<h3 class="preset-matchup">${esc(title(base))}</h3><table><thead><tr><th scope="col">Metric</th><th scope="col">Current</th><th scope="col">Finalist</th></tr></thead>
      <tbody>${data.map(([label,format])=>`<tr><th scope="row">${label}</th><td>${format(base)}</td><td>${format(trial)}</td></tr>`).join('')}</tbody></table>`;
  }).join('');
}
$('run-preset-search').onclick=async()=>{
  try{
    const screening=$('preset-screening'),holdout=$('preset-holdout');
    if(!screening.value||!holdout.value||!screening.checkValidity()||!holdout.checkValidity()){
      throw Error('Choose 3–40 screening and 3–80 fresh games per matchup.');
    }
    const presets={preset:$('search-preset').value,screening:screening.valueAsNumber,holdout:holdout.valueAsNumber};
    renderPresetResult(await job('presets',{settings:readSettings(),board:readMap(),presets}));
    notice('Preset search finished.');
  }catch(e){notice(e.message,true);}
};
function buildPresetSearch(){
  const select=$('search-preset');
  for(const [key,[name]] of Object.entries(config.search_presets))select.add(new Option(name,key));
  select.onchange=presetSelection;
  presetSelection();
}
function playerOutcome(player){
  if(player.killed)return 'Killed by boss';
  if(!player.escaped)return 'Stranded';
  return result.settings.dice_rules?'Finished on Surface':'Extracted';
}
function renderSample(){
  if(!result)return;
  stopReplay();
  const p=result.samples[Number($('sample-picker').value)||0];
  $('export-log').disabled=!p.rows.length;
  $('replay').max=p.rows.length-1;$('replay').value=p.rows.length-1;
  const gear=[...p.equipment];
  if(p.sword)gear.push('Sword '+p.sword);
  if(p.shield)gear.push('Shield '+p.shield);
  $('sample-summary').innerHTML=`<b>${playerOutcome(p)}</b> · ${p.score} gold scored
    <p class="small muted">${p.first_bank_round==null?'No deposit':`First bank: round ${p.first_bank_round}`} · ${p.knockdowns} knockdowns · ${p.encounters} cards</p>
    ${gear.length?`<p class="small muted">${esc(gear.join(', '))} · ${p.equipment_spent} gold spent</p>`:''}`;
  const start=(p.game-1)*result.settings.players;
  const standings=result.players.slice(start,start+result.settings.players)
    .sort((a,b)=>b.escaped-a.escaped||b.score-a.score||a.player-b.player);
  $('game-standings').innerHTML=standings.map(player=>
    `<li>Player ${player.player} · ${player.score} score · ${playerOutcome(player)}${player.winner?' · Winner':''}</li>`
  ).join('');
  $('turn-rows').innerHTML=p.rows.map(r=>`<tr><td>${r.turn} / ${r.step}</td><td>${r.action}</td><td>(${r.position_in}) → (${r.position_out})</td><td>${r.distance_home??'—'}</td><td>${esc(r.card)}</td><td>${r.end_energy}</td><td>${r.loot_out}</td><td>${r.bank}</td></tr>`).join('');
  renderReplay();
}
function renderReplay(){
  if(!result)return;
  const p=result.samples[Number($('sample-picker').value)||0],index=Number($('replay').value),r=p.rows[Math.max(0,index)];
  const start=result.board.start;
  const position=index<0?start:r.position_out;
  const played=p.rows.slice(0,index+1);
  const cleared=new Set(played.filter(row=>row.rock_cleared).map(row=>row.rock_cleared.join(',')));
  const visited=new Set([start.join(',')]);
  for(const row of played){
    for(const tile of [row.position_in,...(row.move_path??[]),row.position_out])visited.add(tile.join(','));
  }
  const gateTonicAvailable=result.settings.deep_entry_tonic&&!played.some(row=>row.gate_tonic);
  const board=$('board');board.innerHTML='';
  for(let y=9;y>=0;y--)for(let x=0;x<6;x++){
    const zone=y===0?0:Math.floor((y-1)/3)+1,current=x===position[0]&&y===position[1];
    const mark=result.board.layout.rows[y][x];
    const farm=mark==='F',gate=result.board.gates[y]===x,closed=index>=0&&r.collapsed.includes(zone);
    const shops=result.board.shops;
    const shop=shops.some(p=>p[0]===x&&p[1]===y);
    const blacksmith=result.settings.dice_rules&&zone>=2&&(shop||gate&&!shops.some(p=>p[1]>=3*zone-2&&p[1]<=3*zone));
    const rock=mark==='#'&&!cleared.has([x,y].join(',')),mine=mark==='M';
    const cache=farm&&result.settings.deep_cache_loot&&result.board.farms['3']?.join(',')===[x,y].join(',');
    const tonic=gateTonicAvailable&&y===7&&gate&&!closed;
    const tile=document.createElement('div');
    tile.className=`tile z${zone}${current?' current':''}${rock?' rock':''}${closed?' collapsed':''}${index>=0&&r.boss_zone===zone&&zone>0?' boss-zone':''}`;
    tile.textContent=current&&index>=0&&r.killed?'†':closed?'×':current?'@':rock?'#':farm?'F':mine?'M':blacksmith?'B':shop?'S':tonic?'T':gate?'↕':visited.has(`${x},${y}`)?'·':'.';
    tile.title=`(${x},${y}) · ${zone?'Zone '+zone:'Surface'}${farm?(cache?' · Farm and deep cache':' · Farm'):''}${mine?' · Regular mine':''}${shop?' · Shop':''}${gate?' · Gate':''}${rock?' · Rock':''}${closed?' · Collapsed':''}${current?' · Player':''}`;
    if(tonic)tile.title+=' · Unclaimed Energy Tonic';
    if(blacksmith)tile.title+=' · Level '+zone+' Blacksmith';
    board.append(tile);
    if(x===5&&Object.hasOwn(result.board.gates,y)){
      const sealed=closed||(index>=0&&r.collapsed.includes(zone-1));
      addZoneWall(board,zone,result.board.gates[y],sealed);
    }
  }
  if(index<0){$('step-detail').textContent='Start on Surface.';return;}
  const moved=r.action==='Delve'||r.action==='Retreat';
  const steps=r.move_steps??1;
  const headline=moved?`Move · ${steps} ${steps===1?'square':'squares'}`:r.action;
  const notes=[];
  if(r.card!=='—')notes.push(r.card);
  if(r.banked_now)notes.push(`Deposited ${r.banked_now} gold`);
  if(r.loot_spent||r.bank_spent)notes.push(`Paid ${r.loot_spent+(r.bank_spent??0)} gold`);
  if(r.loot_penalty)notes.push(`Lost ${r.loot_penalty} carried gold`);
  if(r.knockdown==='Yes')notes.push('Knocked down');
  if(r.gate_tonic)notes.push('Found entrance tonic');
  if(r.potions_used.length)notes.push(`Used ${r.potions_used.join(', ')}`);
  if(r.cache_loot)notes.push(`Found ${r.cache_loot} gold in the cache`);
  const facts=[];
  if(r.move_path?.length)facts.push(`Path: ${r.move_path.map(tile=>`(${tile})`).join(' → ')}`);
  if(r.drawn?.length)facts.push(`Draws: ${r.drawn.join(', ')}`);
  if(r.deck_remaining)facts.push(`Cards left (Zones 1–3): ${Object.values(r.deck_remaining).join(' / ')}`);
  if(r.collapsed.length)facts.push(`Closed zones: ${r.collapsed.join(', ')}`);
  for(const fight of r.combat_events??[]){
    for(const hit of fight.exchanges??[]){
      facts.push(`${fight.target}: d6 ${hit.roll} + ${hit.weapon+hit.bow+hit.grenade} bonuses → ${hit.damage} damage, ${hit.hp_left} HP left. Counterattack: ${hit.hit} Energy, ${hit.shield_absorbed} blocked.`);
    }
  }
  const details=facts.length?`<details><summary>Action details</summary><ul>${facts.map(fact=>`<li>${esc(fact)}</li>`).join('')}</ul></details>`:'';
  $('step-detail').innerHTML=`<b>Round ${r.turn} · ${esc(headline)}</b>
    <p>(${r.position_in}) → (${r.position_out}) · ${r.distance_home??'No path'}${r.distance_home==null?'':' steps home'}</p>
    <p>Energy ${r.available} → ${r.end_energy} · Carried ${r.loot_out} · Banked ${r.bank}</p>
    ${notes.length?`<p>${esc(notes.join(' · '))}</p>`:''}${details}`;
}
$('sample-picker').onchange=renderSample;
$('replay').min=-1;
$('replay').oninput=()=>{stopReplay();renderReplay();};
function download(name,text,type){const blob=new Blob([text],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csv(rows){
  return '\ufeff'+rows.map(row=>row.map(value=>{
    const field=value!=null&&typeof value==='object'?JSON.stringify(value):String(value??'');
    return '"'+field.replaceAll('"','""')+'"';
  }).join(',')).join('\r\n');
}
$('export-results').onclick=()=>{if(!result)return;const keys=Object.keys(result.players[0]);download('balance-results.csv',csv([keys,...result.players.map(p=>keys.map(k=>p[k]))]),'text/csv');};
$('export-log').onclick=()=>{
  if(!result)return;
  const rows=result.samples[Number($('sample-picker').value)||0].rows;
  const keys=[...new Set(rows.flatMap(row=>Object.keys(row)))];
  download('expedition-log.csv',csv([keys,...rows.map(row=>keys.map(key=>row[key]))]),'text/csv');
};
$('save-settings').onclick=async()=>{
  try{
    const board=(await request('/api/map',{board:readMap()})).layout;
    download('balance-settings.json',JSON.stringify({version:4,settings:readSettings(),board},null,2),'application/json');
  }catch(e){notice(e.message,true);}
};
function runGearPreset(tuned){
  if(busy||!config)return;
  const prices=tuned?config.gear_balance_prices:Object.fromEntries(Object.values(config.gear).map(item=>[item.price,config.defaults[item.price]]));
  const switches=Object.fromEntries(Object.values(config.gear).map(item=>[item.enabled,1]));
  const legacyTerrain=readSettings().shared_decks
    ? {dark_cost:config.legacy_defaults.dark_cost,rough_cost:config.legacy_defaults.rough_cost,potion_chance:config.legacy_defaults.potion_chance}
    : {};
  setSettings({...legacyTerrain,...prices,...switches,shared_decks:0,dice_rules:0,gear_priority:4,gear_slots:3});
  simulate();
}
$('gear-original').onclick=()=>runGearPreset(false);
$('gear-tuned').onclick=()=>runGearPreset(true);
$('load-settings').onchange=async e=>{
  try{
    const file=e.target.files[0];if(!file)return;
    if(file.size>64000)throw Error('Settings file is too large.');
    const data=JSON.parse(await file.text());
    if(![1,2,3,4].includes(data.version)||!data.settings||typeof data.settings!=='object')throw Error('Choose a saved balance-settings.json file.');
    const migrated=Object.hasOwn(data.settings,'steps_per_turn');delete data.settings.steps_per_turn;
    if(Object.keys(data.settings).some(k=>k!=='treasure_profiles'&&!controls.has(k)))throw Error('Unknown settings in file.');
    const merged={...config.legacy_defaults,deep_entry_tonic:0,...data.settings};
    if(merged.dice_rules && !Object.hasOwn(data.settings,'start_energy')){
      merged.start_energy=merged.gain;
      merged.farm_cost=merged.mine_cost;
    }
    for(const [key,value]of Object.entries(merged)){
      if(key==='treasure_profiles'){
        if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Invalid exact treasure profiles.');
        continue;
      }
      if(typeof value!=='number'||!Number.isFinite(value))throw Error('Settings must contain finite numbers.');
      const [min,max,step]=limits[key];
      if(value<min||(key==='seed'?value>max:value>1000000)||(Number.isInteger(step)&&!Number.isInteger(value)))throw Error('Invalid value for '+labels[key]+'.');
    }
    const board=(await request('/api/map',{board:data.board??config.board.layout})).layout;
    setMap(board);
    setSettings(merged);notice((migrated?'Old fixed step limit removed; new gear/farm/boss defaults added. ':'')+'Settings and map loaded. Run simulations to update results.');
  }catch(err){notice(err.message,true);}finally{e.target.value='';}
};
let replayTimer=null;
function stopReplay(){
  clearInterval(replayTimer);
  replayTimer=null;
  $('replay-play').textContent='Play route';
}
function advanceReplay(){
  const replay=$('replay');
  if(Number(replay.value)>=Number(replay.max)){stopReplay();return;}
  replay.value=Number(replay.value)+1;
  renderReplay();
}
function playReplay(){
  if(!result)return;
  if(replayTimer){stopReplay();return;}
  const replay=$('replay');
  if(Number(replay.value)>=Number(replay.max))replay.value=-1;
  renderReplay();
  $('replay-play').textContent='Pause route';
  replayTimer=setInterval(advanceReplay,230);
}
$('replay-play').onclick=playReplay;
$('replay-next').onclick=()=>{stopReplay();advanceReplay();};

const gateLabels=['Surface → 1','Zone 1 → 2','Zone 2 → 3'];
const layouts={
  compact:{rows:['..S...','......','..M.M.','.....F','..S...','..M.M.','.....F','..S...','..M.M.','.....F'],gates:[2,2,2]},
  switchback:{rows:['....S.','......','#.M.M.','....SF','......','.M.M.#','FS....','......','#####M','F..M..'],gates:[4,1,4]}
};
let mapVersion=0,mapTimer;
function readMap(){
  return {
    rows:$('map-rows').value.trim().split(/\r?\n/).map(row=>row.trim().toUpperCase()),
    gates:gateLabels.map((_,i)=>Number($('map-gate-'+i)?.value??0)),
    shop_detours:$('shop-detours').checked
  };
}
function setMap(layout,preset=''){
  $('map-rows').value=layout.rows.join('\n');
  layout.gates.forEach((x,i)=>{$('map-gate-'+i).value=x;});
  $('shop-detours').checked=Boolean(layout.shop_detours);
  $('map-preset').value=preset;
  updateMap(false);
}
function addZoneWall(grid,zone,gateColumn,sealed=false,editable=false){
  const divider=document.createElement('div');
  divider.className='zone-wall';
  divider.setAttribute('role',editable?'group':'img');
  const boundary=(zone===1?'Surface':'Zone '+(zone-1))+' to Zone '+zone;
  divider.setAttribute('aria-label',sealed
    ? boundary+' is sealed'
    : boundary+' has one crossing at column '+(gateColumn+1));
  for(let column=0;column<6;column++){
    const section=document.createElement(editable?'button':'span');
    const gate=column===gateColumn;
    section.className=gate&&!sealed?'wall-opening':'wall-block';
    if(editable){
      section.type='button';
      section.dataset.tile=`gate-${zone}-${column}`;
      section.setAttribute('aria-label',`Move ${boundary} gateway to column ${column+1}`);
      section.setAttribute('aria-pressed',String(gate));
      section.title=section.getAttribute('aria-label');
      section.onclick=()=>{
        $('map-gate-'+(zone-1)).value=column;
        updateMap();
      };
    }else section.setAttribute('aria-hidden','true');
    section.textContent=gate?(sealed?'×':'↕'):'';
    divider.append(section);
  }
  grid.append(divider);
}
function drawMap(layout,route=[]){
  const grid=$('map-grid');
  const focusKey=grid.contains(document.activeElement)?document.activeElement.dataset.tile:null;
  const routeTiles=new Set(route.map(point=>point.join(',')));
  grid.replaceChildren();
  for(let y=9;y>=0;y--)for(let x=0;x<6;x++){
    const zone=y===0?0:Math.floor((y-1)/3)+1;
    const mark=layout.rows[y]?.[x]??'.';
    const boundary=[1,4,7].indexOf(y);
    const gate=boundary>=0&&layout.gates[boundary]===x;
    const onRoute=routeTiles.has([x,y].join(','));
    const tile=document.createElement('button');
    tile.type='button';
    tile.dataset.tile=[x,y].join(',');
    tile.className=`tile z${zone}${mark==='#'?' rock':''}${onRoute?' route':''}`;
    tile.textContent=mark!=='.'?mark:gate?'↕':onRoute?':':'.';
    const names={F:'farm',M:'regular mine',S:'shop','#':'rock','.':'floor'};
    tile.setAttribute('aria-label',`Column ${x+1}, depth ${y}, ${names[mark]??'invalid tile'}${gate?', gate':''}`);
    tile.title=tile.getAttribute('aria-label');
    tile.onclick=()=>paintMap(x,y);
    grid.append(tile);
    if(x===5&&boundary>=0)addZoneWall(grid,zone,layout.gates[boundary],false,true);
  }
  if(focusKey)Array.from(grid.children).find(tile=>tile.dataset.tile===focusKey)?.focus({preventScroll:true});
}
function paintMap(x,y){
  const layout=readMap(),brush=$('map-brush').value;
  if(layout.rows.length!==10||layout.rows.some(row=>row.length!==6)){
    $('map-status').textContent='Fix the text layout before painting tiles.';
    return;
  }
  if((brush==='F'||brush==='M')&&y===0){$('map-status').textContent='Choose an underground tile.';return;}
  const rows=layout.rows.map(row=>[...row]);
  rows[y][x]=brush;
  $('map-rows').value=rows.map(row=>row.join('')).join('\n');
  updateMap();
  Array.from($('map-grid').children).find(tile=>tile.dataset.tile===[x,y].join(','))?.focus({preventScroll:true});
}
function updateMap(custom=true){
  if(custom)$('map-preset').value='';
  const layout=readMap(),version=++mapVersion;
  clearTimeout(mapTimer);
  drawMap(layout);
  markDirty();
  $('map-status').textContent='Checking connections…';
  $('map-distances').replaceChildren();
  $('map-route-distance').textContent='';
  mapTimer=setTimeout(async()=>{
    const status=$('map-status');
    try{
      const board=await request('/api/map',{board:layout});
      if(version!==mapVersion)return;
      drawMap(layout,board.route);
      status.classList.remove('invalid');
      status.textContent='All walkable tiles connect to Surface.';
      const count=[1,2,3].map(z=>board.farm_distances.filter(f=>f.zone===z).length);
      $('map-route-distance').textContent=`Farms by zone ${count.join(' / ')}. Highlighted route crosses all gates and visits the first farm in each zone that has one.`;
      $('map-distances').innerHTML=[1,2,3].map(zone=>{
        const farms=board.farm_distances.filter(d=>d.zone===zone);
        return farms.length?farms.map(d=>`<tr><td>Z${zone} · column ${d.tile[0]+1}, depth ${d.tile[1]}</td><td>${d.gate_to_farm}</td><td>${d.farm_to_gate??'—'}</td><td>${d.farm_detour??'—'}</td><td>${d.farm_to_shop??'—'}</td><td>${d.farm_to_surface}</td></tr>`).join('')
          :`<tr><td colspan="6">Zone ${zone} · No farms</td></tr>`;
      }).join('');
    }catch(e){
      if(version!==mapVersion)return;
      status.classList.add('invalid');
      status.textContent=e.message;
    }
  },180);
}
function renderMapComparison(){
  $('map-comparison').hidden=!previous;
  if(!previous)return;
  const rows=[
    ['Longest farm return in deepest farm zone',r=>r.board.deepest_return_steps==null?'—':r.board.deepest_return_steps+' steps'],
    ['Mean walking energy',r=>fmt(r.metrics.avg_movement_energy,1)],
    ['Mean walking steps',r=>fmt(r.metrics.avg_movement_steps,1)],
    ['Reached Zone 3',r=>fmt(r.metrics.zone3_rate)+'%'],
    ['Finished on Surface',r=>fmt(r.metrics.escape_rate)+'%'],
    ['Banked loot per player',r=>fmt(r.metrics.avg_score,2)]
  ];
  $('map-compare-rows').innerHTML=rows.map(([label,get])=>`<tr><td>${label}</td><td>${get(previous)}</td><td>${get(result)}</td></tr>`).join('');
}
function renderRouteDiagnostics(){
  const {diagnostics:d,metrics:m,settings:s}=result;
  $('route-diagnostics').hidden=false;
  $('route-diagnostic-context').textContent=`${fmt(m.player_runs,0)} players · seed ${s.seed} · ${s.adaptive_retreat?'energy-aware retreat':'fixed retreat on turn '+s.retreat_start}`;
  $('route-gates').innerHTML=result.development.zones.map(zone=>{
    const entered=`${zone.entered} (${percent(zone.entered/m.player_runs)})`;
    return `<tr><td>Zone ${zone.zone}</td><td>${entered}</td><td>${fmt(zone.entry_round)}</td><td>${d.stranded[zone.zone]}</td><td>${d.boss_deaths[zone.zone]}</td></tr>`;
  }).join('');
  $('route-activity').textContent=`Per player: ${fmt(d.farm_turns,2)} rounds mining · ${fmt(d.shop_turns,2)} rounds shopping.`;
  $('route-waits').textContent=Object.entries(d.waits).filter(([,count])=>count)
    .map(([reason,count])=>`${reason}: ${count} waits`).join(' · ');
}
function renderRouteStudy(study){
  if(study.kind==='map'){renderMapStudy(study);return;}
  const gear=study.kind==='gear',farm=study.kind==='farm',retreat=study.kind==='retreat',depth=study.kind==='depth';
  const columns=['Condition',...(farm?['Extra farm steps']:[]),'Walking energy / player',
    'Zone 3 reach',...(depth?['Cache claimed']:[]),'Voluntary escape','Banked loot / player',
    ...(retreat||depth?['Banked loot / escapee','Killed by boss']:[]),
    ...(gear?['Used item','Walking energy saved / player']:[]),...(farm?['']:[])];
  $('route-study-head').innerHTML='<tr>'+columns.map(col=>`<th>${col}</th>`).join('')+'</tr>';
  $('route-study-context').textContent=`${fmt(study.games,0)} games per condition · ${fmt(study.players,0)} players · seed ${study.seed}${gear?' · '+study.item:''}.`;
  $('route-study-rows').replaceChildren();
  for(const row of study.rows){
    const tr=document.createElement('tr');
    const name=document.createElement('td');
    name.textContent=row.label;
    tr.append(name);
    if(row.unavailable){
      const explanation=document.createElement('td');
      explanation.colSpan=columns.length-1;
      explanation.textContent='No valid farm tile gives this detour with these gates, shops and rocks.';
      tr.append(explanation);
    }else{
      const m=row.metrics;
      const values=[...(farm?[`${row.farm_detour} at column ${row.farm[0]+1}, depth ${row.farm[1]}`]:[]),
        fmt(m.avg_movement_energy),fmt(m.zone3_rate)+'%',...(depth?[fmt(m.cache_claim_rate)+'%']:[]),
        fmt(m.voluntary_escape_rate)+'%',fmt(m.avg_score,2),
        ...(retreat||depth?[fmt(m.avg_score_survivors,2),fmt(m.boss_death_rate)+'%']:[]),
        ...(gear?[fmt(row.gear.used_percent)+'%',fmt(row.gear.walking_energy_saved,2)]:[])];
      for(const value of values){
        const cell=document.createElement('td');cell.textContent=value;tr.append(cell);
      }
      if(farm){
        const cell=document.createElement('td'),button=document.createElement('button');
        button.textContent='Load map';button.onclick=()=>setMap(row.layout);
        cell.append(button);tr.append(cell);
      }
    }
    $('route-study-rows').append(tr);
  }
  $('route-study-result').hidden=false;
}
function renderMapStudy(study){
  const headings=['Layout','Steps home','Escape-first escape','Late escape',
    'Escape-first banked loot','Late banked loot','Boss deaths (escape-first / late)',''];
  $('route-study-head').innerHTML='<tr>'+headings.map(head=>`<th>${head}</th>`).join('')+'</tr>';
  $('route-study-context').textContent=`${study.tested} layouts screened · target ${study.target}% for escape-first players · ${fmt(study.players,0)} players per policy on fresh seed ${study.seed}. Escape-first uses ${study.slack} turns of return slack. Late players start retreat on turn ${study.late_turn}. Banked loot includes zeroes for losses.`;
  $('route-study-rows').replaceChildren();
  for(const row of study.rows){
    const tr=document.createElement('tr');
    const values=[row.label,row.return_steps??'—',fmt(row.careful.escape_rate)+'%',fmt(row.late.escape_rate)+'%',
      fmt(row.careful.avg_score,2),fmt(row.late.avg_score,2),
      fmt(row.careful.boss_death_rate)+'% / '+fmt(row.late.boss_death_rate)+'%'];
    for(const [index,value] of values.entries()){
      const cell=document.createElement('td');cell.textContent=value;
      if(index===4||index===5){
        const survivor=document.createElement('small');
        survivor.textContent=fmt((index===4?row.careful:row.late).avg_score_survivors,2)+' per escapee';
        cell.append(survivor);
      }
      tr.append(cell);
    }
    const cell=document.createElement('td'),button=document.createElement('button');
    button.textContent='Load '+row.label;button.onclick=()=>setMap(row.layout);
    cell.append(button);tr.append(cell);
    $('route-study-rows').append(tr);
  }
  $('route-study-result').hidden=false;
}
function buildRouteStudy(){
  $('load-escape-setup').onclick=()=>{
    try{
      const {runs,players,seed}=readSettings();
      const setup=config.escape_test_setup;
      setMap(setup.board);
      setSettings({...config.legacy_defaults,...setup.settings,runs,players,seed});
      $('route-study-kind').value='retreat';
      $('route-study-kind').onchange();
      notice('Loaded the test layout with a turn-11 monster that advances on 3+. Compare both retreat policies or run the map.');
    }catch(e){notice(e.message,true);}
  };
  for(const item of Object.keys(config.gear))$('route-study-item').add(new Option(item,item));
  $('route-study-item').value='Flashlight';
  const update=()=>{
    const kind=$('route-study-kind').value;
    const map=kind==='map';
    const games=$('route-study-games');
    if(map&&games.max!=='250'){games.max=250;games.value=40;}
    if(!map&&games.max==='250'){games.max=1000;games.value=250;}
    $('map-study-controls').hidden=!map;
    $('route-study-zone-label').hidden=kind!=='farm';
    $('route-study-item-label').hidden=kind!=='gear';
    const helpText={
      map:'Vary gate columns, farms, shops, and rocks. Each zone boundary keeps one opening. The best layouts are rerun on a fresh seed against both retreat policies.',
      depth:'Compare stopping at Zone 2 with attempting Zone 3, with and without the one-time cache. Change the cache payout under Rewards.',
      farm:'Compare the current farm with 2, 4 and 6 extra walking steps between gates. Gates, shops, rocks and other farms stay fixed.',
      retreat:'Compare the fixed retreat turn against a return estimate using current gear, energy, and the configured slack. The estimate excludes potions and future collapse.',
      gear:'Toggle just one item. Direct walking energy saved is measured on actual steps with the same gear and potion use, minus the selected item.'
    };
    $('route-study-help').textContent=helpText[kind];
  };
  $('route-study-kind').onchange=update;
  update();
  $('run-route-study').onclick=async()=>{
    if(busy)return;
    const input=$('route-study-games');
    if(!input.value||!input.checkValidity()){notice('Enter 1–'+input.max+' games per condition.',true);return;}
    try{
      const study={kind:$('route-study-kind').value,games:Number(input.value),
                   zone:Number($('route-study-zone').value),item:$('route-study-item').value};
      if(study.kind==='map'){
        const target=$('map-study-target'),count=$('map-study-count');
        if(!target.value||!count.value||!target.checkValidity()||!count.checkValidity()){
          throw Error('Enter a 0–100% target and 4–96 layouts.');
        }
        study.target=Number(target.value);study.maps=Number(count.value);
      }
      const comparison=await job('study',{settings:readSettings(),board:readMap(),study});
      renderRouteStudy(comparison);
      notice('Route comparison completed.');
    }catch(e){notice(e.message,true);}
  };
}
function buildMap(){
  gateLabels.forEach((name,i)=>{
    const label=document.createElement('label');
    label.textContent=name;
    const select=document.createElement('select');select.id='map-gate-'+i;
    for(let column=0;column<6;column++)select.add(new Option('Column '+(column+1),column));
    select.onchange=()=>updateMap();label.append(select);$('map-gates').append(label);
  });
  $('map-rows').oninput=()=>updateMap();
  $('map-clear-farms').onclick=()=>{
    $('map-rows').value=$('map-rows').value.replace(/f/gi,'.');
    updateMap();
  };
  $('shop-detours').onchange=()=>updateMap();
  $('map-preset').onchange=()=>{
    const key=$('map-preset').value;
    if(!key)return;
    const layout=key==='test'?testPreset.board:key==='default'?config.board.layout:layouts[key];
    setMap({...layout,shop_detours:$('shop-detours').checked},key);
  };
  $('run-map').onclick=simulate;
  $('watch-map').onclick=async()=>{
    if(!await simulate())return;
    tab('explorer');
    $('replay').value=-1;
    playReplay();
    $('board').scrollIntoView({block:'center'});
  };
  setMap(config.board.layout,'default');
  buildRouteStudy();
}
function renderAudit(report){
  const signed=(value,digits)=>`${value>0?'+':''}${fmt(value,digits)}`;
  const flagged=report.rows.filter(row=>row.signal==='Review for abuse').length;
  $('ev-summary').textContent=`${fmt(report.players,0)} players in ${fmt(report.games,0)} games · Seed ${report.seed} · Baseline banked ${fmt(report.baseline_score,2)} per player · ${flagged} actions flagged for review.`;
  $('ev-rows').innerHTML=report.rows.map(row=>`<tr>
    <td><strong>${esc(row.label)}</strong><small>Versus ${esc(row.alternative.toLowerCase())}</small></td>
    <td>${fmt(row.coverage)}% of players<small>${fmt(row.uses_per_player,2)} uses per player · ${fmt(row.pairs,0)} pairs</small></td>
    <td>${signed(row.ev,2)} loot<small>${row.interval?`95% interval ${signed(row.interval[0],2)} to ${signed(row.interval[1],2)}`:'Insufficient games for an interval'}<br>${fmt(row.action_score,2)} vs ${fmt(row.alternative_score,2)} banked</small></td>
    <td>${signed(row.escape_delta,1)} pp</td>
    <td><span class="${row.signal==='Review for abuse'?'pill':''}">${esc(row.signal)}</span></td>
  </tr>`).join('');
  if(!report.rows.length)$('ev-rows').innerHTML='<tr><td colspan="5">No auditable actions occurred. Check the energy budget and retreat settings.</td></tr>';
  $('ev-report').hidden=false;
}
$('run-ev').onclick=async()=>{
  if(busy)return;
  const games=$('ev-games'),minimum=$('ev-minimum');
  if(!games.value||!games.checkValidity()||!minimum.value||!minimum.checkValidity()){
    notice('Enter 1–500 games and a nonnegative minimum loot gain.',true);
    return;
  }
  try{
    const report=await job('audit',{settings:readSettings(),board:readMap(),
      audit:{games:Number(games.value),minimum_ev:Number(minimum.value)}});
    renderAudit(report);
    notice('Action audit complete.');
  }catch(e){notice(e.message,true);}
};
async function loadBalanceReport(){
  try{
    const report=await request('/cave_balance.json');
    const choices=$('cave-preset-variant');
    choices.replaceChildren(new Option('Strategy parity',report.selected));
    const alternative=report.confirmation
      .filter(row=>row.label!==report.selected&&row.summary.deep_lead>0)
      .sort((a,b)=>b.summary.viability_ratio-a.summary.viability_ratio)[0];
    if(alternative)choices.add(new Option('Deep rewards and gear variety',alternative.label));
    caveBalance=report;
    renderBalancePreset();
    $('cave-preset-table').hidden=false;
    $('cave-preset-report').hidden=false;
    $('cave-preset').disabled=busy;
  }catch(e){$('cave-preset-context').textContent='The confirmed balance report is unavailable.';}
}
function selectedBalanceVariant(){
  return caveBalance.confirmation.find(row=>row.label===$('cave-preset-variant').value);
}
function renderBalancePreset(){
  const {summary,settings}=selectedBalanceVariant();
  const nothing=100-settings.p_treasure-settings.p_monster-settings.p_enhance;
  $('cave-preset-context').textContent=`${caveBalance.screened} screening trials · Average across two maps and two fresh seeds · ${fmt(caveBalance.confirmation_players,0)} players per condition · ${fmt(nothing,0)}% configured Nothing.`;
  $('cave-preset-rows').replaceChildren(...Object.entries(summary.scores).map(([name,score])=>{
    const row=document.createElement('tr');
    for(const value of [name,fmt(score,2),fmt(summary.survivor_scores[name],2),fmt(summary.escape_by_policy[name])+'%']){
      const cell=document.createElement('td');cell.textContent=value;row.append(cell);
    }
    return row;
  }));
}
$('cave-preset-variant').onchange=renderBalancePreset;
$('cave-preset').onclick=()=>{
  if(busy||!caveBalance)return;
  try{
    const {runs,players,seed}=readSettings();
    setMap(caveBalance.preset_board);
    setSettings({...config.legacy_defaults,deep_entry_tonic:0,...config.escape_test_setup.settings,...selectedBalanceVariant().settings,
      ...caveBalance.policies[$('cave-preset-policy').value],runs,players,seed});
    notice(`Loaded the confirmed settings on ${caveBalance.preset_map}.`);
  }catch(e){notice(e.message,true);}
};
async function init(){
  try{
    [config,testPreset]=await Promise.all([request('/api/config'),request('/api/balance-preset')]);
    buildSettings();
    buildMap();
    buildPresetSearch();
    buildLargeStudy();
    buildManualSearch();
    addRange('retreat_start',5,14);
    addRange('gain',2,10,2);
    applyTestPreset();
    $('earlier-rules').addEventListener('toggle',()=>{if($('earlier-rules').open&&!caveBalance)loadBalanceReport();});
    await simulate();
  }catch(error){notice('Could not load simulator. '+error.message,true);}
}
init();
