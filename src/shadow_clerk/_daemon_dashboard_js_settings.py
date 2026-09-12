"""Shadow-clerk daemon: ダッシュボード JavaScript (設定モーダル)

panels から切り出したもの。CFG_FIELDS とそのレンダラ・保存処理。
**連結順は panels より前。** panels の GL_COL_OPTS が top-level で LANG_OPTS を
参照するので、後ろに置くと const の死角 (TDZ) に入る。
"""

_JS_TEMPLATE_SETTINGS = """\
const LANG_OPTS=['ja','en','zh','ko','fr','de','es','pt','ru'];
const CFG_FIELDS=[
  {type:'section',label:I18N['cfg.section.general']},
  {key:'ui_language',label:I18N['cfg.ui_language'],type:'select',opts:['ja','en']},
  {key:'output_directory',label:I18N['cfg.output_directory'],type:'text',ph:I18N['cfg.output_directory_ph']},
  {type:'section',label:I18N['cfg.section.audio']},
  {key:'mic_device',label:I18N['cfg.mic_device'],type:'device_select'},
  {key:'monitor_device',label:I18N['cfg.monitor_device'],type:'device_select'},
  {type:'device_refresh',id:'cfgDeviceRefreshBtn'},
  {type:'section',label:I18N['cfg.section.transcription']},
  {key:'default_language',label:I18N['cfg.default_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'default_model',label:I18N['cfg.default_model'],type:'select',opts:['tiny','base','small','medium','large-v3']},
  {key:'initial_prompt',label:I18N['cfg.initial_prompt'],type:'text',ph:I18N['cfg.initial_prompt_ph']},
  {key:'whisper_beam_size',label:I18N['cfg.whisper_beam_size'],type:'select',opts:['1','2','3','5']},
  {key:'whisper_compute_type',label:I18N['cfg.whisper_compute_type'],type:'select',opts:['int8','float16','float32']},
  {key:'whisper_device',label:I18N['cfg.whisper_device'],type:'select',opts:['cpu','cuda']},
  {key:'japanese_asr_model',label:I18N['cfg.japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'voice_command_key',label:I18N['cfg.voice_command_key'],type:'select',opts:['menu','f23','ctrl_r','ctrl_l','alt_r','alt_l','shift_r','shift_l']},
  {key:'wake_word',label:I18N['cfg.wake_word'],type:'text',ph:I18N['cfg.wake_word_ph']},
  {type:'section',label:I18N['cfg.section.interim']},
  {key:'interim_transcription',label:I18N['cfg.interim_transcription'],type:'bool'},
  {key:'interim_model',label:I18N['cfg.interim_model'],type:'select',opts:['tiny','base','small','medium']},
  {key:'interim_japanese_asr_model',label:I18N['cfg.interim_japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'interim_translation',label:I18N['cfg.interim_translation'],type:'bool'},
  {key:'interim_translation_provider',label:I18N['cfg.interim_translation_provider'],type:'select',opts:['','api','libretranslate','claude'],
    warn:{when:'claude',msgKey:'cfg.interim_translation_provider_claude_warn'}},
  {type:'section',label:I18N['cfg.section.translation']},
  {key:'translate_language',label:I18N['cfg.translate_language'],type:'select',opts:LANG_OPTS},
  {key:'auto_translate',label:I18N['cfg.auto_translate'],type:'bool'},
  {key:'translation_provider',label:I18N['cfg.translation_provider'],type:'select',opts:['','claude','api','libretranslate']},
  {key:'libretranslate_endpoint',label:I18N['cfg.libretranslate_endpoint'],type:'text',ph:'http://localhost:5000'},
  {key:'libretranslate_api_key',label:I18N['cfg.libretranslate_api_key'],type:'text',ph:''},
  {key:'libretranslate_spell_check',label:I18N['cfg.libretranslate_spell_check'],type:'bool'},
  {key:'spell_check_model',label:I18N['cfg.spell_check_model'],type:'text',ph:'sonoisa/t5-base-japanese-spell-checker'},
  {key:'translation_hiragana_step',label:I18N['cfg.translation_hiragana_step'],type:'bool',def:true},
  {type:'section',label:I18N['cfg.section.summary']},
  {key:'auto_summary',label:I18N['cfg.auto_summary'],type:'bool'},
  {key:'summary_source',label:I18N['cfg.summary_source'],type:'select',opts:['auto','transcript','translate']},
  {key:'summary_language',label:I18N['cfg.summary_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'summary_hiragana_step',label:I18N['cfg.summary_hiragana_step'],type:'bool',def:true},
  {key:'summary_length',label:I18N['cfg.summary_length'],type:'select',opts:['half','1page','2pages','3pages','4pages','5pages']},
  {type:'section',label:I18N['cfg.section.api']},
  {key:'llm_provider',label:I18N['cfg.llm_provider'],type:'select',opts:['claude','api']},
  {key:'api_endpoint',label:I18N['cfg.api_endpoint'],type:'text',ph:'https://...'},
  {key:'api_model',label:I18N['cfg.api_model'],type:'api_model'},
  {key:'api_key_env',label:I18N['cfg.api_key_env'],type:'text',ph:'SHADOW_CLERK_API_KEY'},
  {key:'api_disable_thinking',label:I18N['cfg.api_disable_thinking'],type:'bool',def:false},
  {type:'section',label:I18N['cfg.section.ai_console']},
  {type:'skill'},   // 配布ボタン。Welcome モーダルと同じ行を出す
  {key:'auto_analyze',label:I18N['cfg.auto_analyze'],type:'bool'},
  {key:'forbid_analyze',label:I18N['cfg.forbid_analyze'],type:'forbid'},
  {key:'ai_assistant_command',label:I18N['cfg.ai_assistant_command'],type:'text',ph:'claude'},
  {key:'ai_assistant_args',label:I18N['cfg.ai_assistant_args'],type:'text',ph:I18N['cfg.ai_assistant_args_ph']},
  {key:'ai_assistant_init_prompt',label:I18N['cfg.ai_assistant_init_prompt'],type:'text',ph:I18N['cfg.ai_assistant_init_prompt_ph']},
  {key:'ai_assistant_workdir',label:I18N['cfg.ai_assistant_workdir'],type:'text',ph:PATH_HINTS.ai_assistant_workdir,
    warn:{when:'',msgKey:'cfg.ai_assistant_workdir_warn'}},
  {type:'section',label:I18N['cfg.section.gcal']},
  {key:'gcal_integration',label:I18N['cfg.gcal_integration'],type:'bool'},
  {key:'gcal_credentials_file',label:I18N['cfg.gcal_credentials_file'],type:'text',ph:PATH_HINTS.gcal_credentials_file},
  {key:'gcal_calendar_id',label:I18N['cfg.gcal_calendar_id'],type:'text',ph:'primary'},
  {key:'gcal_buffer_minutes',label:I18N['cfg.gcal_buffer_minutes'],type:'select',num:true,opts:['0','1','2','3','5','10']},
  {key:'gcal_end_buffer_minutes',label:I18N['cfg.gcal_end_buffer_minutes'],type:'select',num:true,opts:['0','1','2','3','5']},
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
  CFG_FIELDS.forEach(f=>{
    if(f.type==='section'){
      const h=document.createElement('div');h.className='cfg-section';h.textContent=f.label;b.appendChild(h);return;
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
    const lbl=document.createElement('label');lbl.textContent=f.label;b.appendChild(lbl);
    let el;const v=(cfgData[f.key]!==undefined)?cfgData[f.key]:f.def;
    if(f.type==='bool'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      ['true','false'].forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      el.value=v?'true':'false';
    }else if(f.type==='select'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      f.opts.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      if(v!==null&&v!==undefined)el.value=String(v);
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
  document.getElementById('cfgSaved').style.display='none';
  const jaEl=document.getElementById('cfg_japanese_asr_model');
  if(jaEl)jaEl.onchange=updateCfgDisabled;
  const ijaEl=document.getElementById('cfg_interim_japanese_asr_model');
  if(ijaEl)ijaEl.onchange=updateCfgDisabled;
  renderCfgSkillRows();
  updateCfgDisabled();
  document.getElementById('cfgModal').classList.add('open');
  if(cfgData.api_endpoint){fetchApiModels();}
  loadAudioDevices(cfgData);
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
    else if(f.type==='number'){const n=parseInt(el.value,10);d[f.key]=isNaN(n)?cfgData[f.key]:n;}
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
"""
