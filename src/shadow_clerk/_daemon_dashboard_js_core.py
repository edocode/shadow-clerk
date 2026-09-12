"""Shadow-clerk daemon: ダッシュボード JavaScript (part A)"""

_JS_TEMPLATE_CORE = """\
/*I18N_JSON*/
/*PATH_HINTS_JSON*/
/* --- TranscriptName 構築ヘルパー（regex なし・fileInfo を使用） --- */
const TN={
  filename(dt,name){return 'transcript-'+dt+(name?'@'+name:'')+'.txt';},
  summaryFilename(dt,name){return 'summary-'+dt+(name?'@'+name:'')+'.md';},
};
/* --- URL ハッシュ同期（選択ファイル名を #filename で保持） --- */
function _hashFile(){const h=location.hash.replace(/^#/,'');if(!h)return null;try{return decodeURIComponent(h);}catch(e){return h;}}
function _setHashFile(f){const nh=f?('#'+encodeURIComponent(f)):'';if((location.hash||'')===nh)return;if(nh)history.replaceState(null,'',nh);else history.replaceState(null,'',location.pathname+location.search);}
let fileInfo={}; // /api/files の file_info をキャッシュ
// 各 load 関数は世代カウンタで最新リクエストの応答だけを描画する（切替直後の
// 遅延応答でパネルを上書きしないため）。**宣言をここに置くのは TDZ 対策。**
// load 関数と同じ panels に置くと、その手前で走る初期化行が let の死角に入り、
// `Cannot access '_sGen'` で初期化行ごと止まって全ペインが空になっていた
let _tGen=0,_rGen=0,_sGen=0,_adGen=0,_anGen=0;
let curFile='', activeFile='';
let leftTab='dates'; // 左ペインのアクティブタブ
let meetingActive=false, translating=false, muteMic=false, muteMonitor=false, pttActive=false;
let audioBackend='';
/* 中央ペインの見せ方。AI は T/R を伏せて AI 分析だけを出す */
const PANEL_MODES=['T|R','T','R','AI'];
let panelMode=0;
try{const _pm=parseInt(localStorage.getItem('panelMode')||'0',10);
    if(_pm>=0&&_pm<PANEL_MODES.length)panelMode=_pm;}catch(e){}
let meetingGroups={}, curGroup=null; // 会議グループ管理
const as={tp:true,rp:true,sp:true,logc:true};
['tp','rp','sp','logc'].forEach(id=>{
  document.getElementById(id).addEventListener('scroll',function(){
    as[id]=this.scrollTop+this.clientHeight>=this.scrollHeight-30;
  });
});
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
// onclick 属性内のシングルクォート JS 文字列に埋め込む値用。
// ブラウザは属性値を HTML デコードしてから JS として解釈するため、
// escAttr だけでは ' が生き残り文字列が壊れる（XSS になり得る）。escJs → escAttr の順で適用する。
// 外部ドキュメントへのリンク。URL 自体が i18n にあるので言語で切り替わる
function docLink(urlKey,textKey){
  return `<a href="${escAttr(I18N[urlKey])}" target="_blank" rel="noopener">`
    +`${esc(I18N[textKey])}</a>`;
}
function escJs(s){return s.replace(/\\\\/g,'\\\\\\\\').replace(/'/g,"\\\\'");}
function fmtLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln" data-ts="'+escAttr(m[1])+'" data-raw="'+escAttr(t)+'"><span class="ln-text"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</span></div>';}
  return '<div class="ln" data-raw="'+escAttr(t)+'"><span class="ln-text">'+esc(t)+'</span></div>';
}
function fmtTranscriptLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln" data-ts="'+escAttr(m[1])+'" data-raw="'+escAttr(t)+'"><input type="checkbox" class="ln-cb" onchange="onSelChange()"><span class="ln-text"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</span></div>';}
  return '<div class="ln" data-raw="'+escAttr(t)+'"><span class="ln-text">'+esc(t)+'</span></div>';
}
function addLines(id,text,fmt){
  const el=document.getElementById(id);
  // Windows の transcript ファイルは CRLF で保存されるため、行末の \\r を除去
  text.split('\\n').forEach(l=>{const s=l.replace(/\\r$/,'');if(s.trim())el.insertAdjacentHTML('beforeend',fmt(s));});
  if(as[id])el.scrollTop=el.scrollHeight;
}
/* --- Selection management --- */
function getSelectedLines(){return Array.from(document.querySelectorAll('#tp .ln-cb:checked')).map(cb=>cb.closest('.ln'));}
function onSelChange(){
  const sel=getSelectedLines();const n=sel.length;
  const bar=document.getElementById('selActions');
  const cnt=document.getElementById('selCount');
  const btnExt=document.getElementById('btnExtract');
  if(n>0){
    bar.classList.add('show');
    cnt.textContent=(I18N['dash.selected_count']||'{count} selected').replace('{count}',n);
  }else{bar.classList.remove('show');}
  btnExt.style.display=(n===0||n===2)?'':'none';
}
function deselectAll(){
  document.querySelectorAll('#tp .ln-cb:checked').forEach(cb=>{cb.checked=false;});
  onSelChange();
}
/* --- Meeting toggle --- */
function updateMeetingBtn(session){
  meetingActive=!!session;
  const btn=document.getElementById('btnMeeting');
  if(meetingActive){
    btn.textContent='\\u25A0 '+I18N['dash.meeting_toggle_end'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.meeting_toggle_start'];
    btn.className='pri';
  }
}
function togMeeting(){cmd(meetingActive?'end_meeting':'start_meeting');}
/* --- Translation toggle --- */
function updateTranslateBtn(active){
  translating=active;
  const btn=document.getElementById('btnTranslate');
  if(translating){
    btn.textContent='\\u25A0 '+I18N['dash.translate_stop'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.translate_start'];
    btn.className='pri';
  }
}
function _curFileArg(){
  const fi=fileInfo[curFile];
  return fi?(fi.dt+(fi.name?'@'+fi.name:'')):'';
}
async function togTranslate(){
  if(translating){cmd('translate_stop');updateTranslateBtn(false);return;}
  const dateArg=curFile&&curFile!==activeFile?_curFileArg():'';
  cmd('translate_start'+(dateArg?' '+dateArg:''));updateTranslateBtn(true);
}
async function regenTranslate(){
  if(!confirm(I18N['dash.translate_regen_confirm']))return;
  const el=document.getElementById('rp');if(el)el.innerHTML='';
  const dateArg=_curFileArg();
  cmd('translate_regenerate'+(dateArg?' '+dateArg:''));
  updateTranslateBtn(true);
}

/* --- Mute toggles --- */
function updateMuteBtn(type,muted,available){
  const btn=document.getElementById(type==='mic'?'btnMuteMic':'btnMuteMonitor');
  if(available===false){btn.classList.remove('off');btn.classList.add('unavail');btn.title=I18N[type==='mic'?'dash.mic_unavailable':'dash.monitor_unavailable']||'Unavailable';return;}
  btn.classList.remove('unavail');
  if(muted){btn.classList.add('off');btn.title=I18N[type==='mic'?'dash.unmute_mic':'dash.unmute_monitor'];}
  else{btn.classList.remove('off');btn.title=I18N[type==='mic'?'dash.mute_mic':'dash.mute_monitor'];}
}
function togMute(type){
  const btn=document.getElementById(type==='mic'?'btnMuteMic':'btnMuteMonitor');
  if(btn.classList.contains('unavail')){showTroubleshoot(type);return;}
  if(type==='mic'){muteMic=!muteMic;cmd(muteMic?'mute_mic':'unmute_mic');updateMuteBtn('mic',muteMic);}
  else{muteMonitor=!muteMonitor;cmd(muteMonitor?'mute_monitor':'unmute_monitor');updateMuteBtn('monitor',muteMonitor);}
}
function showTroubleshoot(type){
  const title=I18N[type==='mic'?'dash.mic_unavailable':'dash.monitor_unavailable']||'Unavailable';
  const isMic=type==='mic';
  const T=k=>I18N[k]||k;
  let html='<b>'+T(isMic?'dash.ts_mic_title':'dash.ts_monitor_title')+'</b><br><br>';
  html+='<b>'+T('dash.ts_possible_causes')+'</b><ol>';
  html+='<li>'+T(isMic?'dash.ts_mic_cause1':'dash.ts_monitor_cause1')+'</li>';
  html+='<li>'+T('dash.ts_cause_service')+'</li>';
  html+='</ol>';
  html+='<b>'+T('dash.ts_fix_steps')+'</b><ol>';
  let restartCmd='';
  if(audioBackend==='pipewire'){restartCmd='systemctl --user restart pipewire pipewire-pulse';}
  else if(audioBackend==='pulseaudio'){restartCmd='systemctl --user restart pulseaudio';}
  if(restartCmd){html+='<li>'+T('dash.ts_restart_service')+'<br><code>'+restartCmd+'</code></li>';}
  html+='<li>'+T('dash.ts_list_devices')+'<br><code>clerk-daemon --list-devices</code></li>';
  const opt=isMic?'--mic':'--monitor';
  html+='<li>'+T('dash.ts_restart_clerk').replace('{opt}',opt)+'</li>';
  html+='</ol>';
  document.getElementById('tsTitle').textContent=title;
  document.getElementById('tsBody').innerHTML=html;
  document.getElementById('troubleshootModal').classList.add('open');
}
function closeTroubleshoot(){document.getElementById('troubleshootModal').classList.remove('open');}
/* --- PTT toggle --- */
function updatePTT(active){
  pttActive=active;
  const btn=document.getElementById('btnPTT');
  if(active){btn.style.background='var(--red)';btn.style.color='#fff';}
  else{btn.style.background='';btn.style.color='';}
}
function togPTT(){
  pttActive=!pttActive;
  cmd(pttActive?'ptt_on':'ptt_off');
  updatePTT(pttActive);
}
/* --- 読む面の文字サイズ (小|中|大) --- */
/* 変えるのは --fs だけ。ヘッダやボタンまで大きくすると折り返して行が増え、
   肝心の読む面が狭くなる。中 = これまでの 12px */
const FONT_SIZES=[['dash.font_s','11px'],['dash.font_m','12px'],['dash.font_l','15px']];
let fontStep=1;
try{const _fs=parseInt(localStorage.getItem('fontStep')||'1',10);
    if(_fs>=0&&_fs<FONT_SIZES.length)fontStep=_fs;}catch(e){}
function applyFontSize(){
  const [key,px]=FONT_SIZES[fontStep];
  document.documentElement.style.setProperty('--fs',px);
  const b=document.getElementById('togFont');
  if(b)b.textContent=I18N[key]||key;
  // 1文字の幅が変わる。コンソールは幅から列数を出しているので測り直す
  scheduleConsoleCols();
}
function cycleFont(){
  fontStep=(fontStep+1)%FONT_SIZES.length;
  try{localStorage.setItem('fontStep',String(fontStep));}catch(e){}
  applyFontSize();
}

/* --- Panel cycling (T|R -> T -> R -> AI) --- S は sumChevron で個別に開閉 */
function applyPanelMode(){
  const t=document.getElementById('pnlT'),r=document.getElementById('pnlR'),
        btn=document.getElementById('togTR');
  if(!t||!r||!btn)return;
  const ai=panelMode===3;
  t.classList.toggle('hidden',ai||panelMode===2);
  r.classList.toggle('hidden',ai||panelMode===1);
  btn.textContent=PANEL_MODES[panelMode];
  // AI のときは S ペインが唯一の中身。畳んだままだと画面が空になる。
  // 畳む取っ手も伏せる——押せてしまうと、押した先に何も残らない
  if(ai){openSumPane();switchSumTab('ai');}
  const ch=document.getElementById('sumChevron');
  if(ch)ch.style.display=ai?'none':'';
  updateSumSplit();
}
function cyclePanel(){
  panelMode=(panelMode+1)%PANEL_MODES.length;
  try{localStorage.setItem('panelMode',String(panelMode));}catch(e){}
  applyPanelMode();
}
/* --- Logs toggle --- */
function togLogs(){
  const lp=document.getElementById('logp'),arr=document.getElementById('logArrow');
  lp.classList.toggle('collapsed');
  arr.textContent=lp.classList.contains('collapsed')?'▲':'▼';
  // 畳んでいる間は #consolec が display:none で幅を測れない。開いたところで
  // 測り直さないと、子は既定の列数のままになる
  if(!lp.classList.contains('collapsed')&&logTab==='console'){
    scheduleConsoleCols();scrollConsoleBottom();
  }
}
/* --- Status fetch --- */
async function fetchStatus(){
  try{const d=await(await fetch('/api/status')).json();
    const s=document.getElementById('langSel');if(s&&d.language)s.value=d.language;
    updateMeetingBtn(d.session);
    updateTranslateBtn(d.translating);
    muteMic=d.mute_mic;muteMonitor=d.mute_monitor;if(d.backend)audioBackend=d.backend;
    updateMuteBtn('mic',muteMic,d.use_mic);updateMuteBtn('monitor',muteMonitor,d.use_monitor);
    if(d.ptt!==undefined)updatePTT(d.ptt);
    // console の SSE は状態が変わったときしか飛ばない。後から開いた
    // ページでも分析ボタンが開始/停止を正しく出せるよう、ここで揃える
    if(d.console_running!==undefined)updateConsoleStatus(d.console_running);
    const ai=document.getElementById('asrInfo');
    if(ai&&d.asr_backend){ai.textContent=d.asr_backend==='whisper'?'Whisper: '+d.asr_model_id:d.asr_backend;}
    if(d.gcal_enabled){const b=document.getElementById('btnGcal');if(b)b.style.display='';}
  }catch(e){}
}
const es=new EventSource('/api/events');
es.addEventListener('transcript',e=>{
  const d=JSON.parse(e.data);
  if(!curFile||curFile===d.file){addLines('tp',d.diff,fmtTranscriptLine);document.getElementById('tf').textContent=d.file;}
});
es.addEventListener('translation',e=>{
  const d=JSON.parse(e.data);
  // 表示中ファイルの翻訳のみ反映（他ファイルの自動翻訳が閲覧中パネルに混入しないように）
  // d.file は翻訳ファイル名 (transcript-...-en.txt)。curFile の stem + '-' で照合する
  if(curFile&&!d.file.startsWith(curFile.replace(/\\.txt$/,'-')))return;
  const el=document.getElementById('rp');
  const msg=el.querySelector('.translating-msg');if(msg)msg.remove();
  addLines('rp',d.diff,fmtLine);document.getElementById('rf').textContent=d.file;
});
es.addEventListener('advice',e=>{
  try{const d=JSON.parse(e.data);
    if(curFile&&!_sameStem(d.file,curFile))return;
    _renderGenerated('adp','adf',d,'dash.no_advice');
  }catch(ex){}
});
es.addEventListener('analysis',e=>{
  try{const d=JSON.parse(e.data);
    if(curFile&&!_sameStem(d.file,curFile))return;
    _renderGenerated('anp','anf',d,'dash.no_analysis');
  }catch(ex){}
});
/* advice-<stem>.md / analysis-<stem>.md と transcript-<stem>.txt の stem を比べる */
function _sameStem(generated,transcript){
  const g=generated.replace(/^(advice|analysis)-/,'').replace(/\\.md$/,'');
  const t=transcript.replace(/^transcript-/,'').replace(/\\.txt$/,'');
  return g===t;
}
/* 下端追従は「行を足したあと」に判定すると scrollHeight が既に伸びていて
   条件が必ず偽になる。更新の前に捕まえておく */
function nearBottom(el){return el.scrollTop+el.clientHeight>=el.scrollHeight-40;}
/* 生成物 (advice / analysis) の描画。サーバが Markdown を HTML に起こして
   送ってくる（生 HTML はレンダラ側で実体参照に落ちている） */
function _renderGenerated(paneId,labelId,d,emptyKey){
  const el=document.getElementById(paneId);if(!el)return;
  const wasBottom=nearBottom(el);
  el.innerHTML=(d.html&&d.html.trim())
    ?'<div class="md-body">'+d.html+'</div>'
    :'<div style="color:var(--muted);font-size:12px;padding:8px">'+esc(I18N[emptyKey]||'')+'</div>';
  const lbl=document.getElementById(labelId);if(lbl)lbl.textContent=d.file||'';
  if(wasBottom)el.scrollTop=el.scrollHeight;
}
es.addEventListener('log',e=>{
  const d=JSON.parse(e.data);const el=document.getElementById('logc');
  const c=d.line.includes('ERROR')?'e':d.line.includes('WARNING')?'w':'';
  el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(d.line)+'</div>');
  if(as.logc)el.scrollTop=el.scrollHeight;
});
es.addEventListener('session',e=>{
  try{const d=JSON.parse(e.data);updateMeetingBtn(d.content||null);}catch(ex){}
  loadFiles();
});
es.addEventListener('ptt',e=>{
  try{const d=JSON.parse(e.data);updatePTT(d.active);}catch(ex){}
});
es.addEventListener('asr_status',e=>{
  try{const d=JSON.parse(e.data);const ai=document.getElementById('asrInfo');
  if(ai&&d.asr_backend){ai.textContent=d.asr_backend==='whisper'?'Whisper: '+d.asr_model_id:d.asr_backend;}}catch(ex){}
});
es.addEventListener('interim_transcript',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('interim-monitor');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.text);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_translation',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('itp');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.translated);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_clear',e=>{
  const el=document.getElementById('interim-monitor');
  if(el)el.innerHTML='';
  document.getElementById('interim-area').style.display='none';
  const itp=document.getElementById('itp');
  if(itp)itp.innerHTML='';
});
/* --- 入力レベルバー（ミュートボタンとは別要素。updateMuteBtn の10秒ごと
   上書きと1Hzの本更新が競合しないようにする） --- */
const LV_NOISE = {mic: [], monitor: []};
const LV_SILENT = {mic: [], monitor: []};
es.addEventListener('level', e => {
  const d = JSON.parse(e.data);
  for (const label of ['mic', 'monitor']) updateLevel(label, d[label]);
});
function updateLevel(label, v){
  const bar = document.getElementById('lv_' + label);
  if(!bar) return;
  const fill = bar.firstElementChild;
  if(!v){
    // キャプチャ断絶（バックエンド再接続・デバイス設定変更等）。窓の連続性が
    // 途切れるので両方の履歴をリセットする。リセットせずに続けると、断絶を
    // 挟んだ寄せ集めの30サンプルが「30秒間ずっと無音」と誤認される
    LV_NOISE[label].length = 0; LV_SILENT[label].length = 0;
    fill.style.width = '0%'; bar.className = 'lv'; bar.title = ''; return;
  }
  // 対数スケール。16bit PCM の目安で rms=100(静かな部屋の床) を0%、
  // rms=20000(大声・クリップ間際) を100%とし、その中間 rms≈1414 が50%になる
  // ように圧縮する（以前は 20*log10(rms)-10 で rms≈316000 まで到達しないと
  // 満杯にならず、16bit の実用域では上四分の一が常に埋まらなかった）
  const pct = v.rms <= 100 ? 0 : Math.min(100, (Math.log10(v.rms) - 2) / 2.301 * 100);
  fill.style.width = pct.toFixed(0) + '%';
  // 定常ノイズ: 10秒すべてが「音量はあるが crest が低い」
  const noiseHist = LV_NOISE[label];
  noiseHist.push(v.rms >= 100 && v.crest < 2);
  if(noiseHist.length > 10) noiseHist.shift();
  const noisy = noiseHist.length === 10 && noiseHist.every(Boolean);
  // 完全無音: 30秒すべてが厳密にゼロ。生きたマイクはノイズフロアを持つので
  // 黙っているだけならゼロにはならない。この理屈は mic にしか成立しない
  // ――sink monitor は再生中の音を折り返すだけなので、何も再生されていない
  // （会議前後・相手側が無言・資料を読んでいる間 等、1日の大半）だけで
  // rms=peak=0 が何十秒も続くのが monitor の正常な待機状態であり、故障では
  // ない。monitor にも同じ判定を適用すると speaker バーが1日のほとんど赤に
  // なり、本当にヘッドセットの電源が切れているときの赤が「いつもの赤」に
  // 埋もれてしまう（オオカミ少年化）。そのため無音検出は mic 限定とする
  // （monitor は steady-noise / fallback の警告とバー表示自体は維持する）。
  const silHist = LV_SILENT[label];
  let silent = false;
  if(label === 'mic'){
    silHist.push(v.rms === 0 && v.peak === 0);
    if(silHist.length > 30) silHist.shift();
    silent = silHist.length === 30 && silHist.every(Boolean);
  } else {
    silHist.length = 0;
  }
  // 警告はバー本体（コンテナ）の背景・枠線で示す。塗り(<i>)は無音時に幅0%に
  // なり見た目が変化しないため、塗りに乗せると無音警告が視認不能になる
  // （fix round 1 finding 1）。silent は noisy より深刻な状態なので、両方の
  // 条件が成立した場合は silent を優先する（定義上ほぼ排他だが念のため）。
  // lv-fallback は box-shadow を使うので border-color/background を使う
  // lv-noise/lv-silent と衝突せず、両方同時に成立しても互いを隠さない
  bar.className = 'lv' + (v.fallback ? ' lv-fallback' : '')
                + (silent ? ' lv-silent' : noisy ? ' lv-noise' : '');
  // どのデバイスを測っているかは常にツールチップに出す。fallback 時は
  // 指定した名前と実際に使われているデバイスの両方を出す（fix round 1
  // finding 3: Step 0a で用意した読める表示名がそれまで一度も使われていなかった）
  const deviceInfo = v.fallback
    ? I18N['dash.level_fallback'] + ': ' + v.requested + ' -> ' + v.device
    : v.device;
  bar.title = (silent ? I18N['dash.level_silent'] + ' ' : '')
            + (noisy ? I18N['dash.level_noise'] + ' ' : '')
            + (label === 'mic' ? I18N['dash.level_mic'] : I18N['dash.level_monitor'])
            + ': ' + deviceInfo;
}
function _todayYestStr(){
  const nd=new Date();
  const fd=d=>`${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
  const yd=new Date(nd);yd.setDate(yd.getDate()-1);
  return [fd(nd),fd(yd)];
}
async function loadFiles(){
  try{const r=await fetch('/api/files'),d=await r.json(),s=document.getElementById('fsel'),p=s.value;
  s.innerHTML='';activeFile=d.active||'';
  fileInfo=d.file_info||{};
  meetingGroups=d.groups||{};
  // ヘッダー fsel: 今日・前日 + アクティブ + 直前選択ファイルと同じ日のファイル
  const [tod,yes]=_todayYestStr();
  const prevDt=(p?(d.file_info[p]?.dt||''):'').substring(0,8);
  const shown=new Set(d.files.filter(f=>{
    const dt=fileInfo[f]?.dt||'';
    return dt.startsWith(tod)||dt.startsWith(yes)||f===d.active||(prevDt&&dt.startsWith(prevDt));
  }));
  d.files.forEach(f=>{
    if(!shown.has(f))return;
    const o=document.createElement('option');o.value=f;
    o.textContent=(fileInfo[f]?.label||f)+(f===d.active?' ★':'');s.appendChild(o);
  });
  s.value=(p&&shown.has(p))?p:(d.active||'');
  // URL ハッシュが別のファイルを指しているなら、そちらを復元する側に任せる
  const hf=_hashFile();
  const restoring=!!(hf&&fileInfo[hf]&&hf!==s.value);
  if(curFile!==s.value){
    // 選択中ファイルが消えた（リネーム・削除等）→ パネルも新しい選択に合わせて再読込。
    // 初回 (p が空) でも読む。以前は if(p) で弾いていたが、ハッシュがあると
    // 初期化行の読み込みも飛ぶため、ページを開き直しただけで全ペインが空になった
    // （ハッシュはファイルを選ぶたびに書かれるので、普通に使うと必ず残る）
    curFile=s.value;
    if(!restoring){loadT(curFile);loadR(curFile);loadS(curFile);loadAdvice(curFile);loadAnalysis(curFile);}
  }
  populateYearSelect();
  if(restoring)selectMtgFile(hf);
  if(leftTab==='meetings') renderMtgPane();
  else if(leftTab==='dates') renderDatePane();
  }catch(e){}
}
function populateYearSelect(){
  const sel=document.getElementById('srYear');if(!sel)return;
  const cur=sel.value;
  const years=[...new Set(Object.values(fileInfo).map(fi=>(fi.dt||'').substring(0,4)).filter(Boolean))].sort().reverse();
  sel.innerHTML=`<option value="">${I18N['dash.search_year']||'年'}</option>`;
  years.forEach(y=>{const o=document.createElement('option');o.value=y;o.textContent=y;sel.appendChild(o);});
  if(cur)sel.value=cur;
}
function initSearchSelects(){
  const mo=document.getElementById('srMonth');
  const dy=document.getElementById('srDay');
  const hr=document.getElementById('srHour');
  if(!mo||!dy||!hr)return;
  for(let i=1;i<=12;i++){const o=document.createElement('option');o.value=String(i).padStart(2,'0');o.textContent=String(i).padStart(2,'0');mo.appendChild(o);}
  for(let i=1;i<=31;i++){const o=document.createElement('option');o.value=String(i).padStart(2,'0');o.textContent=String(i).padStart(2,'0');dy.appendChild(o);}
  for(let i=0;i<=23;i++){const o=document.createElement('option');o.value=String(i).padStart(2,'0');o.textContent=String(i).padStart(2,'0');hr.appendChild(o);}
}
// 開閉はブラウザ側に覚えさせる。毎回たたみ直すのは手間で、かつ
// 開いているかどうかは会議ごとではなく人ごとの好み
function _rememberPane(key,collapsed){
  try{localStorage.setItem(key,collapsed?'1':'0');}catch(e){}
}
function _restorePane(key,id,chId,openMark,closeMark){
  let v;try{v=localStorage.getItem(key);}catch(e){return;}
  if(v===null)return;                       // 記憶が無ければ HTML の初期状態のまま
  const p=document.getElementById(id);if(!p)return;
  const collapsed=v==='1';
  p.classList.toggle('collapsed',collapsed);
  const ch=document.getElementById(chId);
  if(ch)ch.innerHTML=collapsed?closeMark:openMark;
  return collapsed;
}
function restorePanes(){
  _restorePane('mtgPaneCollapsed','pnlM','meetingChevron','&#x25C4;','&#x25BA;');
  const c=_restorePane('sumPaneCollapsed','pnlS','sumChevron','&#x25BA;','&#x25C4;');
  if(c===false)updateSumSplit();            // 畳んでいる間は測れないので開いた側だけ
}
function togMtgPane(){
  const p=document.getElementById('pnlM');if(!p)return;
  const collapsed=p.classList.toggle('collapsed');
  const ch=document.getElementById('meetingChevron');
  if(ch)ch.innerHTML=collapsed?'&#x25BA;':'&#x25C4;';
  _rememberPane('mtgPaneCollapsed',collapsed);
}
function togSumPane(){
  const p=document.getElementById('pnlS');if(!p)return;
  const collapsed=p.classList.toggle('collapsed');
  const ch=document.getElementById('sumChevron');
  if(ch)ch.innerHTML=collapsed?'&#x25C4;':'&#x25BA;';
  _rememberPane('sumPaneCollapsed',collapsed);
  // 畳んでいる間は大きさを測れない。開いたところで分割を挟み直す
  if(!collapsed)updateSumSplit();
}
function openSumPane(){
  const p=document.getElementById('pnlS');if(!p||!p.classList.contains('collapsed'))return;
  p.classList.remove('collapsed');
  const ch=document.getElementById('sumChevron');
  if(ch)ch.innerHTML='&#x25BA;';
  _rememberPane('sumPaneCollapsed',false);
}

/* --- Summary パネル タブ切替 --- */
let sumTab='summary';
function switchSumTab(tab){
  sumTab=tab;
  const map={summary:['tabSummary','sumWrap'],ai:['tabAi','aiWrap']};
  Object.keys(map).forEach(t=>{
    const [btnId,wrapId]=map[t];
    const btn=document.getElementById(btnId),wrap=document.getElementById(wrapId);
    if(btn)btn.classList.toggle('active',t===tab);
    if(wrap)wrap.style.display=(t===tab)?'flex':'none';
  });
  // 表示に切り替わるまで aiWrap の大きさは 0 で測れない。ここでも挟み直す
  if(tab==='ai')updateSumSplit();
}

/* --- 左ペイン タブ切替 --- */
function switchLeftTab(tab){
  leftTab=tab;
  ['dates','meetings','search'].forEach(t=>{
    const id=t.charAt(0).toUpperCase()+t.slice(1);
    const btn=document.getElementById('tab'+id);
    let pane;
    if(t==='dates') pane=document.getElementById('datePane');
    else if(t==='meetings') pane=document.getElementById('meetingContent');
    else pane=document.getElementById('searchPane');
    if(t===tab){
      if(btn) btn.classList.add('active');
      if(pane) pane.style.display=(t==='meetings')?'flex':'';
    }else{
      if(btn) btn.classList.remove('active');
      if(pane) pane.style.display='none';
    }
  });
  if(tab==='dates') renderDatePane();
  else if(tab==='meetings') renderMtgPane();
}
function _badges(fi){
  let b='';
  if(fi?.has_translation)b+='<span class="badge-t">T</span>';
  if(fi?.has_summary)b+='<span class="badge-s">S</span>';
  // AI 分析。提案と確定事項のどちらかがあれば付ける——一覧で「分析が残っている
  // 会議」を探せるようにするためで、内訳は開けば分かる
  if(fi?.has_advice||fi?.has_analysis)b+='<span class="badge-a" title="'
    +escAttr(I18N['dash.badge_ai']||'')+'">A</span>';
  return b;
}
/* 会議ごとの起動ディレクトリを開くボタン。会議ファイル (@名前あり) にだけ出す */
function _wdBtn(f){
  if(!/^transcript-\\d+@/.test(f))return '';
  return `<button class="mg-wd" title="${escAttr(I18N['dash.workdir_btn_title']||'')}" onclick="event.stopPropagation();openWorkdirModal('${escAttr(escJs(f))}')">⚙</button>`;
}
function renderDatePane(){
  const dp=document.getElementById('datePane');if(!dp)return;
  const files=Object.entries(fileInfo)
    .filter(([,fi])=>fi.meeting_group===null)
    .sort((a,b)=>b[0].localeCompare(a[0]));
  if(!files.length){
    dp.innerHTML=`<div style="color:var(--muted);font-size:12px;padding:8px">${esc(I18N['dash.dates_empty']||'No daily transcripts.')}</div>`;
    return;
  }
  dp.innerHTML=files.map(([f])=>{
    const fi=fileInfo[f];
    return `<div class="mg-file${f===curFile?' active':''}" onclick="selectMtgFile('${escAttr(escJs(f))}')" title="${escAttr(f)}"><span class="mg-file-label">${esc((fi?.label||f))}</span>${_badges(fi)}${_wdBtn(f)}</div>`;
  }).join('');
}
"""
