"""Shadow-clerk daemon: ダッシュボード JavaScript (設定モーダル)

panels から切り出したもの。CFG_FIELDS とそのレンダラ・保存処理。
**連結順は panels より前。** panels の GL_COL_OPTS が top-level で LANG_OPTS を
参照するので、後ろに置くと const の死角 (TDZ) に入る。
"""
from __future__ import annotations

_JS_TEMPLATE_SETTINGS = """\
const LANG_OPTS=['ja','en','zh','ko','fr','de','es','pt','ru'];
const CFG_FIELDS=[
  {type:'section',tab:'general',label:I18N['cfg.section.general']},
  {key:'ui_language',simple:1,label:I18N['cfg.ui_language'],type:'select',opts:['ja','en']},
  {key:'output_directory',simple:1,label:I18N['cfg.output_directory'],type:'text',ph:I18N['cfg.output_directory_ph']},
  {type:'section',tab:'general',label:I18N['cfg.section.audio']},
  {key:'mic_device',simple:1,label:I18N['cfg.mic_device'],type:'device_select'},
  {key:'monitor_device',simple:1,label:I18N['cfg.monitor_device'],type:'device_select'},
  {type:'device_refresh',simple:1,id:'cfgDeviceRefreshBtn'},
  {type:'section',tab:'transcription',label:I18N['cfg.section.transcription']},
  {key:'default_language',simple:1,label:I18N['cfg.default_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'default_model',simple:1,label:I18N['cfg.default_model'],type:'select',opts:['tiny','base','small','medium','large-v3']},
  {key:'initial_prompt',label:I18N['cfg.initial_prompt'],type:'text',ph:I18N['cfg.initial_prompt_ph']},
  {key:'whisper_beam_size',label:I18N['cfg.whisper_beam_size'],type:'select',opts:['1','2','3','5']},
  {key:'whisper_compute_type',label:I18N['cfg.whisper_compute_type'],type:'select',opts:['int8','float16','float32']},
  {key:'whisper_device',label:I18N['cfg.whisper_device'],type:'select',opts:['cpu','cuda']},
  {key:'whisper_vad_filter',simple:1,label:I18N['cfg.whisper_vad_filter'],type:'bool',def:true},
  {key:'whisper_vad_threshold',when:{k:'whisper_vad_filter'},label:I18N['cfg.whisper_vad_threshold'],type:'select',opts:['0.2','0.35','0.5']},
  {key:'speaker_diarization',simple:1,label:I18N['cfg.speaker_diarization'],type:'bool'},
  {key:'speaker_enrollment',label:I18N['cfg.speaker_enrollment'],type:'bool'},
  {key:'diarization_threshold',when:{k:'speaker_diarization'},label:I18N['cfg.diarization_threshold'],type:'select',opts:['0.50','0.55','0.60','0.65','0.70','0.75','0.80']},
  {key:'diarization_min_sec',when:{k:'speaker_diarization'},label:I18N['cfg.diarization_min_sec'],type:'select',opts:['1.0','1.5','2.0','2.5','3.0']},
  {key:'voiceprint_max_samples',label:I18N['cfg.voiceprint_max_samples'],type:'number'},
  {key:'voiceprint_min_sec',label:I18N['cfg.voiceprint_min_sec'],type:'number',float:true},
  {key:'voiceprint_cluster_min_samples',label:I18N['cfg.voiceprint_cluster_min_samples'],type:'number'},
  {key:'voiceprint_cluster_distance',label:I18N['cfg.voiceprint_cluster_distance'],type:'number',float:true},
  {key:'voiceprint_main_similarity',label:I18N['cfg.voiceprint_main_similarity'],type:'number',float:true},
  {key:'voiceprint_outlier_max',label:I18N['cfg.voiceprint_outlier_max'],type:'number'},
  {key:'voiceprint_outlier_ratio',label:I18N['cfg.voiceprint_outlier_ratio'],type:'number',float:true},
  {key:'voiceprint_high',label:I18N['cfg.voiceprint_high'],type:'number',float:true},
  {key:'voiceprint_low',label:I18N['cfg.voiceprint_low'],type:'number',float:true},
  {key:'voiceprint_margin',label:I18N['cfg.voiceprint_margin'],type:'number',float:true},
  {key:'voiceprint_non_attendee_penalty',label:I18N['cfg.voiceprint_non_attendee_penalty'],type:'number',float:true},
  {key:'voiceprint_min_utterances',label:I18N['cfg.voiceprint_min_utterances'],type:'number'},
  {key:'self_group',label:I18N['cfg.self_group'],type:'text',ph:I18N['cfg.self_group_ph']},
  {key:'self_name',label:I18N['cfg.self_name'],type:'text',ph:I18N['cfg.self_name_ph']},
  {key:'asr_engine',label:I18N['cfg.asr_engine'],type:'select',opts:['whisper','moonshine']},
  {key:'japanese_asr_model',simple:1,label:I18N['cfg.japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'english_asr_model',simple:1,label:I18N['cfg.english_asr_model'],type:'select',opts:['default','moonshine','small.en','medium.en','large-v3-turbo','distil-large-v3']},
  {key:'reazonspeech_model',simple:1,when:{k:'japanese_asr_model',v:'reazonspeech-k2'},label:I18N['cfg.reazonspeech_model'],type:'select',opts:['ja','ja-en']},
  {key:'voice_command_key',label:I18N['cfg.voice_command_key'],type:'select',opts:['menu','f23','ctrl_r','ctrl_l','alt_r','alt_l','shift_r','shift_l']},
  {key:'wake_word',label:I18N['cfg.wake_word'],type:'text',ph:I18N['cfg.wake_word_ph']},
  {type:'section',tab:'transcription',label:I18N['cfg.section.interim']},
  {key:'interim_transcription',label:I18N['cfg.interim_transcription'],type:'bool'},
  {key:'interim_model',when:{k:'interim_transcription'},label:I18N['cfg.interim_model'],type:'select',opts:['tiny','base','small','medium']},
  {key:'interim_asr_engine',when:{k:'interim_transcription'},label:I18N['cfg.interim_asr_engine'],type:'select',opts:['whisper','moonshine']},
  {key:'interim_japanese_asr_model',when:{k:'interim_transcription'},label:I18N['cfg.interim_japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'interim_translation',when:{k:'interim_transcription'},label:I18N['cfg.interim_translation'],type:'bool'},
  {key:'interim_translation_provider',when:{k:'interim_transcription'},label:I18N['cfg.interim_translation_provider'],type:'select',opts:['','api','libretranslate','claude'],
    warn:{when:'claude',msgKey:'cfg.interim_translation_provider_claude_warn'}},
  {type:'section',tab:'translation',label:I18N['cfg.section.translation']},
  {key:'translate_language',simple:1,label:I18N['cfg.translate_language'],type:'select',opts:LANG_OPTS},
  {key:'auto_translate',simple:1,label:I18N['cfg.auto_translate'],type:'bool'},
  {key:'translation_provider',simple:1,label:I18N['cfg.translation_provider'],type:'select',opts:['','claude','api','libretranslate']},
  {key:'translation_claude_model',when:{k:'translation_provider',v:'claude'},label:I18N['cfg.translation_claude_model'],type:'select',opts:['','haiku','sonnet','opus']},
  {key:'libretranslate_endpoint',simple:1,when:{k:'translation_provider',v:'libretranslate'},label:I18N['cfg.libretranslate_endpoint'],type:'text',ph:'http://localhost:5000'},
  {key:'libretranslate_api_key',when:{k:'translation_provider',v:'libretranslate'},label:I18N['cfg.libretranslate_api_key'],type:'text',ph:''},
  {key:'libretranslate_spell_check',label:I18N['cfg.libretranslate_spell_check'],type:'bool'},
  {key:'spell_check_model',label:I18N['cfg.spell_check_model'],type:'text',ph:'sonoisa/t5-base-japanese-spell-checker'},
  {key:'translation_hiragana_step',label:I18N['cfg.translation_hiragana_step'],type:'bool',def:true},
  {type:'section',tab:'translation',label:I18N['cfg.section.summary']},
  {key:'auto_summary',simple:1,label:I18N['cfg.auto_summary'],type:'bool'},
  {key:'summary_source',label:I18N['cfg.summary_source'],type:'select',opts:['auto','transcript','translate']},
  {key:'summary_language',label:I18N['cfg.summary_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'summary_hiragana_step',label:I18N['cfg.summary_hiragana_step'],type:'bool',def:true},
  {key:'summary_length',simple:1,label:I18N['cfg.summary_length'],type:'select',opts:['half','1page','2pages','3pages','4pages','5pages']},
  {type:'section',tab:'ai',label:I18N['cfg.section.api']},
  {key:'llm_provider',simple:1,label:I18N['cfg.llm_provider'],type:'select',opts:['claude','api']},
  {key:'claude_cli_model',when:{k:'llm_provider',v:'claude'},label:I18N['cfg.claude_cli_model'],type:'select',opts:['haiku','sonnet','opus']},
  {key:'api_endpoint',simple:1,when:{k:'llm_provider',v:'api'},label:I18N['cfg.api_endpoint'],type:'text',ph:'https://...'},
  {key:'api_model',simple:1,when:{k:'llm_provider',v:'api'},label:I18N['cfg.api_model'],type:'api_model'},
  {key:'api_key_env',when:{k:'llm_provider',v:'api'},label:I18N['cfg.api_key_env'],type:'text',ph:'SHADOW_CLERK_API_KEY'},
  {key:'api_disable_thinking',when:{k:'llm_provider',v:'api'},label:I18N['cfg.api_disable_thinking'],type:'bool',def:false},
  {type:'section',tab:'ai',label:I18N['cfg.section.ai_console']},
  {type:'skill',simple:1},   // 配布ボタン。Welcome モーダルと同じ行を出す
  {key:'auto_analyze',label:I18N['cfg.auto_analyze'],type:'bool'},
  {key:'forbid_analyze',label:I18N['cfg.forbid_analyze'],type:'forbid'},
  {key:'ai_assistant_command',label:I18N['cfg.ai_assistant_command'],type:'text',ph:'claude'},
  {key:'ai_assistant_args',label:I18N['cfg.ai_assistant_args'],type:'text',ph:I18N['cfg.ai_assistant_args_ph']},
  {key:'ai_assistant_init_prompt',label:I18N['cfg.ai_assistant_init_prompt'],type:'text',ph:I18N['cfg.ai_assistant_init_prompt_ph']},
  {key:'ai_assistant_workdir',label:I18N['cfg.ai_assistant_workdir'],type:'text',ph:PATH_HINTS.ai_assistant_workdir,
    warn:{when:'',msgKey:'cfg.ai_assistant_workdir_warn'}},
  {type:'section',tab:'talk',label:I18N['cfg.section.talk']},
  {key:'talk_filler_sec',label:I18N['cfg.talk_filler_sec'],type:'select',num:true,opts:['0','5','8','10','15','20']},
  {type:'section',tab:'talk',label:I18N['cfg.section.pronounce']},
  {key:'pronounce_enabled',label:I18N['cfg.pronounce_enabled'],type:'bool'},
  {key:'pronounce_model',when:{k:'pronounce_enabled'},label:I18N['cfg.pronounce_model'],type:'text',ph:'facebook/wav2vec2-xlsr-53-espeak-cv-ft'},
  {key:'pronounce_device',when:{k:'pronounce_enabled'},label:I18N['cfg.pronounce_device'],type:'select',opts:['cpu','cuda']},
  {key:'pronounce_idle_unload_sec',when:{k:'pronounce_enabled'},label:I18N['cfg.pronounce_idle_unload_sec'],type:'number'},
  {key:'pronounce_threads',when:{k:'pronounce_enabled'},label:I18N['cfg.pronounce_threads'],type:'number'},
  {type:'section',tab:'integrations',label:I18N['cfg.section.gcal']},
  {type:'doc',simple:1,when:{k:'gcal_integration'},urlKey:'cfg.gcal_setup_url',textKey:'cfg.gcal_setup_link'},
  {key:'gcal_integration',simple:1,label:I18N['cfg.gcal_integration'],type:'bool'},
  {key:'gcal_credentials_file',simple:1,when:{k:'gcal_integration'},label:I18N['cfg.gcal_credentials_file'],type:'text',ph:PATH_HINTS.gcal_credentials_file},
  {key:'gcal_calendar_id',simple:1,when:{k:'gcal_integration'},label:I18N['cfg.gcal_calendar_id'],type:'text',ph:'primary'},
  {key:'gcal_buffer_minutes',when:{k:'gcal_integration'},label:I18N['cfg.gcal_buffer_minutes'],type:'select',num:true,opts:['0','1','2','3','5','10']},
  {key:'gcal_end_buffer_minutes',when:{k:'gcal_integration'},label:I18N['cfg.gcal_end_buffer_minutes'],type:'select',num:true,opts:['0','1','2','3','5']},
];
let cfgData={};
/* 分析しない話題。定型はチェックボックス、それ以外は自由入力に振り分ける */
const FORBID_PRESETS=['cfg.forbid_preset.evaluation','cfg.forbid_preset.compensation',
  'cfg.forbid_preset.private','cfg.forbid_preset.hiring','cfg.forbid_preset.legal'];
async function loadForbidAnalyze(box, free){
  let items=[];
  try{items=(await(await fetch('/api/forbid-analyze')).json()).items||[];}catch(e){return;}
  const boxes=[...box.querySelectorAll('input[type=checkbox]')];
  const preset=new Set(boxes.map(cb=>cb.dataset.forbid));
  boxes.forEach(cb=>{cb.checked=items.includes(cb.dataset.forbid);});
  free.value=items.filter(v=>!preset.has(v)).join('\\n');
}
async function saveForbidAnalyze(){
  const box=document.getElementById('cfg_forbid_analyze');
  const free=document.getElementById('cfg_forbid_free');
  if(!box||!free)return;
  const items=[...box.querySelectorAll('input[type=checkbox]')]
    .filter(cb=>cb.checked).map(cb=>cb.dataset.forbid)
    .concat(free.value.split('\\n').map(v=>v.trim()).filter(Boolean));
  try{await fetch('/api/forbid-analyze',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({items})});}catch(e){}
}
async function openCfg(){
  try{cfgData=await(await fetch('/api/config')).json();}catch(e){return;}
  const b=document.getElementById('cfgBody');b.innerHTML='';
  const pw=document.getElementById('cfgPathWarn');pw.textContent='';pw.style.display='none';
  cfgMode=cfgLoadMode();cfgTab=0;cfgGroups=[];cfgFieldByKey={};
  cfgEmptyEls=[];
  cfgPanelEls=CFG_TAB_IDS.map(()=>{const p=document.createElement('div');p.className='cfg-panel';
    const e=document.createElement('div');e.className='cfg-empty';e.textContent=I18N['cfg.tab_empty'];
    p.appendChild(e);cfgEmptyEls.push(e);b.appendChild(p);return p;});
  let grp=null;
  CFG_FIELDS.forEach(f=>{
    if(f.type==='section'){
      const h=document.createElement('div');h.className='cfg-section';h.textContent=f.label;
      const tab=CFG_TAB_IDS.indexOf(f.tab);cfgPanelEls[tab].appendChild(h);
      grp={tab,head:h,rows:[]};cfgGroups.push(grp);return;
    }
    // 1 項目 = 1 行 (.cfg-row)。モード・親の値に応じて hidden を切り替える
    const b=document.createElement('div');b.className='cfg-row';
    cfgPanelEls[grp.tab].appendChild(b);grp.rows.push({f,node:b});
    if(f.key)cfgFieldByKey[f.key]=f;
    if(f.type==='doc'){
      // key を持たない全幅の行。saveCfg() は 'cfg_'+undefined を探すので自然に無視される
      const d=document.createElement('div');d.className='cfg-doc';
      d.innerHTML=docLink(f.urlKey,f.textKey);
      b.appendChild(d);
      return;
    }
    if(f.type==='skill'){
      // key を持たない全幅の行。saveCfg() は 'cfg_'+undefined を探すので自然に無視される
      const d=document.createElement('div');d.className='cfg-skill';d.id='cfgSkillRows';
      d.textContent=I18N['cfg.skill_install'];
      b.appendChild(d);
      return;
    }
    if(f.type==='device_refresh'){
      // key を持たないアクション行。saveCfg() は 'cfg_'+undefined を探すため自然に無視される
      b.appendChild(document.createElement('label'));
      const btn=document.createElement('button');btn.type='button';btn.id=f.id;
      btn.textContent=I18N['cfg.device_refresh'];btn.title=I18N['cfg.device_refresh_title'];
      btn.style.cssText='width:auto;padding:4px 10px;cursor:pointer;';
      btn.onclick=refreshAudioDevices;
      b.appendChild(btn);
      return;
    }
    const lbl=document.createElement('label');lbl.textContent=f.label;if(f.when)lbl.className='cfg-child-label';b.appendChild(lbl);
    let el;const v=(cfgData[f.key]!==undefined)?cfgData[f.key]:f.def;
    if(f.type==='bool'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      ['true','false'].forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      el.value=v?'true':'false';
    }else if(f.type==='select'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      // config に一覧外の値があれば選択肢に足す（保存で消さないため）。JSON の 1.0 は 1 で届くので数値でも突き合わせる
      const hit=(v===null||v===undefined)?undefined:f.opts.find(o=>String(o)===String(v)||(v!==''&&o!==''&&!isNaN(o)&&Number(o)===Number(v)));
      const opts=(v===null||v===undefined||hit!==undefined)?f.opts:[...f.opts,String(v)];
      opts.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      if(v!==null&&v!==undefined)el.value=String(hit!==undefined?hit:v);
    }else if(f.type==='device_select'){
      // 実際の選択肢は非同期の loadAudioDevices() が /api/audio-devices 取得後に差し替える。
      // ここでは自動＋現在値だけの仮の選択肢を出しておく（保存直後クリック等でも値が保持される）。
      // 取得完了まで disabled にする — CLI 固定中かどうか判定できるまで保存させないための安全策。
      // これを外すと、取得待ちの一瞬に保存された場合、固定中の config を null で上書きしてしまう。
      el=document.createElement('select');el.id='cfg_'+f.key;el.disabled=true;
      const auto=document.createElement('option');auto.value='';auto.textContent=I18N['cfg.device_auto'];el.appendChild(auto);
      if(v){const cur=document.createElement('option');cur.value=String(v);cur.textContent=String(v);cur.selected=true;el.appendChild(cur);}
    }else if(f.type==='api_model'){
      el=document.createElement('div');el.style.display='flex';el.style.gap='4px';el.style.alignItems='center';el.style.width='100%';
      const sel=document.createElement('select');sel.id='cfg_'+f.key;sel.style.flex='1';sel.style.width='auto';
      const cur=document.createElement('option');cur.value=(v===null||v===undefined)?'':String(v);
      cur.textContent=(v===null||v===undefined)?'(not set)':String(v);sel.appendChild(cur);
      el.appendChild(sel);
      const btn=document.createElement('button');btn.textContent='\\u21BB';btn.title='Fetch models';
      btn.style.cssText='padding:2px 8px;cursor:pointer;width:auto;flex-shrink:0;';
      btn.onclick=async()=>{
        btn.disabled=true;btn.textContent='...';
        try{const d=await(await fetch('/api/models')).json();
          if(d.error){alert(d.error);return;}
          const prev=sel.value;sel.innerHTML='';
          const empty=document.createElement('option');empty.value='';empty.textContent='(not set)';sel.appendChild(empty);
          d.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
          if(prev)sel.value=prev;
        }catch(e){alert('Failed to fetch models');}
        finally{btn.disabled=false;btn.textContent='\\u21BB';}
      };el.appendChild(btn);
    }else if(f.type==='forbid'){
      // 定型はチェックボックス、それ以外は自由入力。保存先は config.yaml では
      // なく forbid-ai-analyze.txt なので、saveCfg とは別経路で送る
      el=document.createElement('div');el.id='cfg_'+f.key;
      el.style.cssText='display:flex;flex-direction:column;gap:4px;width:100%;';
      FORBID_PRESETS.forEach(key=>{
        const lab=document.createElement('label');
        lab.style.cssText='display:flex;gap:6px;align-items:center;font-weight:normal;';
        const cb=document.createElement('input');cb.type='checkbox';
        cb.style.cssText='width:auto;margin:0;';cb.dataset.forbid=I18N[key]||key;
        lab.appendChild(cb);lab.appendChild(document.createTextNode(I18N[key]||key));
        el.appendChild(lab);
      });
      const free=document.createElement('textarea');free.id='cfg_forbid_free';
      free.rows=3;free.placeholder=I18N['cfg.forbid_analyze_free']||'';
      el.appendChild(free);
      const hint=document.createElement('div');hint.className='cfg-warn';
      hint.style.display='block';hint.textContent=I18N['cfg.forbid_analyze_hint']||'';
      el.appendChild(hint);
      loadForbidAnalyze(el, free);
    }else if(f.type==='json'){
      el=document.createElement('textarea');el.id='cfg_'+f.key;
      el.value=JSON.stringify(v||[],null,2);
    }else{
      el=document.createElement('input');el.type='text';el.id='cfg_'+f.key;
      el.value=(v===null||v===undefined)?'':String(v);
      if(f.ph)el.placeholder=f.ph;
    }
    b.appendChild(el);
    if(f.warn){
      const w=document.createElement('div');w.className='cfg-warn';
      w.id='cfg_warn_'+f.key;
      w.textContent=I18N[f.warn.msgKey]||f.warn.msgKey;
      const isWarnValue=()=>{
        const cur=el.tagName==='SELECT'?el.value:(el.querySelector&&el.querySelector('select')?el.querySelector('select').value:el.value);
        return String(cur)===String(f.warn.when);
      };
      w.style.display=isWarnValue()?'block':'none';
      el.addEventListener('change',()=>{w.style.display=isWarnValue()?'block':'none';});
      b.appendChild(w);
    }
  });
  b.addEventListener('change',cfgApply);
  cfgRenderTabs();
  document.getElementById('cfgSaved').style.display='none';
  const jaEl=document.getElementById('cfg_japanese_asr_model');
  if(jaEl)jaEl.onchange=updateCfgDisabled;
  const ijaEl=document.getElementById('cfg_interim_japanese_asr_model');
  if(ijaEl)ijaEl.onchange=updateCfgDisabled;
  renderCfgSkillRows();
  updateCfgDisabled();
  cfgApply();
  loadCfgPresets();
  document.getElementById('cfgModal').classList.add('open');
  if(cfgData.api_endpoint){fetchApiModels();}
  loadAudioDevices(cfgData);
}
/* --- 設定モーダル: タブ・Simple/Advanced・親子表示 --- */
const CFG_TAB_IDS=['general','transcription','translation','ai','talk','integrations'];
let cfgMode='simple',cfgTab=0,cfgGroups=[],cfgPanelEls=[],cfgEmptyEls=[],cfgFieldByKey={};
function cfgLoadMode(){try{return localStorage.getItem('cfgMode')==='advanced'?'advanced':'simple';}catch(e){return 'simple';}}
function setCfgMode(m){cfgMode=m;try{localStorage.setItem('cfgMode',m);}catch(e){}cfgApply();}
function cfgRenderTabs(){
  const t=document.getElementById('cfgTabs');t.innerHTML='';
  CFG_TAB_IDS.forEach((id,i)=>{
    const btn=document.createElement('button');btn.type='button';
    btn.innerHTML=`${esc(I18N['cfg.tab.'+id])}<span class="cfg-count"></span>`;
    btn.onclick=()=>cfgShowTab(i);t.appendChild(btn);
  });
  cfgShowTab(cfgTab);
}
function cfgShowTab(i){
  cfgTab=i;
  cfgPanelEls.forEach((p,j)=>{p.hidden=j!==i;});
  document.querySelectorAll('#cfgTabs button').forEach((t,j)=>t.setAttribute('aria-selected',String(j===i)));
}
// 現在の入力値。親キーの条件判定に使う（保存前の DOM 値をそのまま見る）
function cfgCur(k){
  const f=cfgFieldByKey[k];const el=document.getElementById('cfg_'+k);if(!f||!el)return undefined;
  if(f.type==='bool')return el.value==='true';
  if(f.type==='api_model')return el.querySelector('select').value;
  return el.value;
}
function cfgCond(w){
  if(!w)return true;
  const v=cfgCur(w.k);
  return w.v===undefined?!!v:String(v)===w.v;
}
// 表示条件 = (Advanced または simple 指定) かつ 親の条件を満たす。隠すだけで値は保持される
function cfgApply(){
  document.querySelectorAll('#cfgModeBox button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.mode===cfgMode)));
  const cnt=CFG_TAB_IDS.map(()=>0);let on=0,total=0;
  cfgGroups.forEach(g=>{
    let any=false;
    g.rows.forEach(r=>{
      const vis=(cfgMode==='advanced'||!!r.f.simple)&&cfgCond(r.f.when);
      r.node.hidden=!vis;
      if(vis){any=true;cnt[g.tab]++;}
      if(r.f.key){total++;if(vis)on++;}
    });
    g.head.hidden=!any;
  });
  cfgEmptyEls.forEach((e,i)=>{e.hidden=cnt[i]>0;});
  document.querySelectorAll('#cfgTabs .cfg-count').forEach((s,i)=>{s.textContent=cnt[i];});
  document.getElementById('cfgHint').textContent=`${I18N['cfg.shown_count']} ${on} / ${total}`;
}
async function fetchApiModels(){
  const sel=document.getElementById('cfg_api_model');if(!sel)return;
  try{const d=await(await fetch('/api/models')).json();
    if(d.error||!d.models.length)return;
    const prev=sel.value;sel.innerHTML='';
    const empty=document.createElement('option');empty.value='';empty.textContent='(not set)';sel.appendChild(empty);
    d.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
    if(prev)sel.value=prev;
  }catch(e){}
}
function closeCfg(){document.getElementById('cfgModal').classList.remove('open');}
async function saveCfg(){
  const d={};
  CFG_FIELDS.forEach(f=>{
    if(f.type==='forbid')return;   // 保存先が config.yaml ではない
    const el=document.getElementById('cfg_'+f.key);if(!el)return;
    if(f.type==='bool'){d[f.key]=el.value==='true';}
    else if(f.type==='json'){try{d[f.key]=JSON.parse(el.value);}catch(e){d[f.key]=cfgData[f.key];}}
    else if(f.type==='number'){const n=f.float?parseFloat(el.value):parseInt(el.value,10);d[f.key]=isNaN(n)?cfgData[f.key]:n;}
    else if(f.type==='device_select'){
      // CLI 固定中は disabled になっており、送ると null で上書きしてしまうため送らない
      if(el.disabled)return;
      d[f.key]=el.value||null;
    }
    else if(f.type==='select'&&f.num){const sv=el.value;const n=parseInt(sv,10);d[f.key]=isNaN(n)?null:n;}
    else if(f.type==='select'){const sv=el.value;const autoKeys=['default_language','summary_source','summary_language'];d[f.key]=(sv===''||(sv==='auto'&&autoKeys.includes(f.key)))?null:sv;}
    else{const v=el.value.trim();d[f.key]=(v===''||v==='null')?null:v;}
  });
  await saveForbidAnalyze();
  const langChanged=d.ui_language&&d.ui_language!==cfgData.ui_language;
  try{const res=await(await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(d)})).json();
    if(langChanged){location.reload();return;}
    // 存在しないパスは保存を通したうえで知らせる。黙って既定値に落ちると
    // 「設定したのに効かない」の理由がユーザーから見えない
    const w=document.getElementById('cfgPathWarn');
    const msgs=(res&&res.warnings)||[];
    w.textContent=msgs.join(' / ');w.style.display=msgs.length?'block':'none';
    const s=document.getElementById('cfgSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
async function renderCfgSkillRows(){
  const d=document.getElementById('cfgSkillRows');if(!d)return;
  const st=await _skillStatus();if(!st)return;
  d.innerHTML=`<div class="wc-h" style="margin-top:0">${esc(I18N['cfg.skill_install'])}</div>`
    +_skillRows(st.targets);
}
function updateCfgDisabled(){
  const ija=document.getElementById('cfg_interim_japanese_asr_model');
  const iIsK2=ija&&ija.value==='reazonspeech-k2';
  const im=document.getElementById('cfg_interim_model');
  if(im){im.disabled=iIsK2;im.style.opacity=iIsK2?'0.5':'1';}
}
/* --- 設定プリセット --- */
let _cfgPresets=[];
async function loadCfgPresets(){
  try{
    const d=await(await fetch('/api/config-presets')).json();
    _cfgPresets=d.presets||[];
  }catch(e){_cfgPresets=[];}
  const sel=document.getElementById('cfgPresetSel');if(!sel)return;
  sel.innerHTML='<option value="">'+esc(I18N['cfg.preset_select'])+'</option>';
  _cfgPresets.forEach(p=>{const o=document.createElement('option');o.value=p.name;o.textContent=p.name;sel.appendChild(o);});
}
function loadCfgPreset(){
  const sel=document.getElementById('cfgPresetSel');
  if(!sel||!sel.value)return;
  const preset=_cfgPresets.find(p=>p.name===sel.value);
  if(!preset||!preset.config)return;
  const pc=preset.config;
  CFG_FIELDS.forEach(f=>{
    if(!f.key||f.type==='forbid')return;
    if(!(f.key in pc))return;
    const el=document.getElementById('cfg_'+f.key);if(!el)return;
    const v=pc[f.key];
    if(f.type==='bool'){el.value=v?'true':'false';}
    else if(f.type==='api_model'){const s=el.querySelector('select');if(s)s.value=(v===null||v===undefined)?'':String(v);}
    else if(el.tagName==='SELECT'){if(v!==null&&v!==undefined)el.value=String(v);}
    else if(el.tagName==='INPUT'||el.tagName==='TEXTAREA'){el.value=(v===null||v===undefined)?'':String(v);}
  });
  updateCfgDisabled();
  cfgApply();
}
function openSavePreset(){
  const sel=document.getElementById('cfgPresetSel');
  const inp=document.getElementById('cfgPresetNameInput');
  if(inp)inp.value=sel?sel.value:'';
  const delBtn=document.getElementById('cfgPresetDeleteBtn');
  if(delBtn)delBtn.style.display=(sel&&sel.value)?'':'none';
  document.getElementById('cfgPresetModal').classList.add('open');
  if(inp)inp.focus();
}
function closeSavePreset(){document.getElementById('cfgPresetModal').classList.remove('open');}
function _collectCfgFormValues(){
  const d={};
  CFG_FIELDS.forEach(f=>{
    if(!f.key||f.type==='forbid')return;
    const el=document.getElementById('cfg_'+f.key);if(!el)return;
    if(f.type==='bool'){d[f.key]=el.value==='true';}
    else if(f.type==='json'){try{d[f.key]=JSON.parse(el.value);}catch(e){}}
    else if(f.type==='device_select'){if(!el.disabled)d[f.key]=el.value||null;}
    else if(f.type==='select'&&f.num){const n=f.float?parseFloat(el.value):parseInt(el.value,10);d[f.key]=isNaN(n)?null:n;}
    else if(f.type==='api_model'){const s=el.querySelector('select');if(s)d[f.key]=s.value||null;}
    else if(f.type==='select'){d[f.key]=el.value===''?null:el.value;}
    else{const v=el.value.trim();d[f.key]=(v===''||v==='null')?null:v;}
  });
  return d;
}
async function doSavePreset(){
  const name=(document.getElementById('cfgPresetNameInput')?.value||'').trim();
  if(!name)return;
  try{
    await fetch('/api/config-presets',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name,config:_collectCfgFormValues()})});
    closeSavePreset();
    await loadCfgPresets();
    const sel=document.getElementById('cfgPresetSel');if(sel)sel.value=name;
  }catch(e){}
}
async function deleteCfgPreset(){
  const name=(document.getElementById('cfgPresetNameInput')?.value||'').trim();
  if(!name)return;
  try{
    await fetch('/api/config-presets/delete',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name})});
    closeSavePreset();
    await loadCfgPresets();
  }catch(e){}
}
"""
