"""Shadow-clerk daemon: ダッシュボード JavaScript（ブラウザの読み上げ）

talk mode で Claude が話す練習言語の文（/api/say の lang 付き）と、AI分析 の 🔊 の例文を、このタブの
speechSynthesis で読む。VOICEVOX は日本語の声なので、英語などはブラウザの声のほうがお手本になる。
"""

_JS_TEMPLATE_SPEECH = r"""
/* --- ブラウザの読み上げ: daemon は最後に名乗ったタブ1つにだけ talk_speak を送る --- */
const SPEECH_TAB='t'+Math.random().toString(36).slice(2,12);
let _speechLast=0;
function speechOk(){return typeof speechSynthesis!=='undefined'&&typeof SpeechSynthesisUtterance!=='undefined';}
/* Chrome は利用者の操作が一度も無いページでは speak を拒む（not-allowed）。そのあいだは名乗らない */
function speechActivated(){const ua=navigator.userActivation;return !ua||ua.hasBeenActive;}
function speechLangs(){
  const s=new Set();
  speechSynthesis.getVoices().forEach(v=>{const l=String(v.lang||'').split(/[-_]/)[0].toLowerCase();if(l)s.add(l);});
  return [...s].sort();
}
function _speechPost(path,body){
  return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).catch(()=>{});
}
function speechReady(){
  if(!speechOk()||!speechActivated())return;
  const langs=speechLangs();if(!langs.length)return;
  _speechLast=Date.now();
  _speechPost('/api/talk-speech/ready',{tab:SPEECH_TAB,langs});
}
function _speechVoice(lang){
  return speechSynthesis.getVoices().find(v=>String(v.lang||'').toLowerCase().split(/[-_]/)[0]===lang)||null;
}
/* Chrome は参照の切れた utterance を読み終える前に GC し、onend が来なくなる。読み終えるまでここに持っておく */
const _speechLive=new Set();
/* lang の声が無ければ既定の声で読む */
function speakText(text,lang,onDone){
  const u=new SpeechSynthesisUtterance(text);
  if(lang){u.lang=lang;const v=_speechVoice(lang);if(v)u.voice=v;}
  u.onend=u.onerror=()=>{_speechLive.delete(u);if(onDone)onDone();};
  _speechLive.add(u);
  speechSynthesis.speak(u);
}
function onTalkSpeak(d){
  if(d.tab!==SPEECH_TAB)return;
  speakText(d.text,d.lang,()=>_speechPost('/api/talk-speech/done',{id:d.id}));
}
function onTalkSpeakCancel(d){if(d.tab===SPEECH_TAB)speechSynthesis.cancel();}
function initSpeech(src){
  if(!speechOk())return;
  src.addEventListener('talk_speak',e=>{try{onTalkSpeak(JSON.parse(e.data));}catch(ex){}});
  src.addEventListener('talk_speak_cancel',e=>{try{onTalkSpeakCancel(JSON.parse(e.data));}catch(ex){}});
  /* 背景のタブはタイマーが1分に1回まで間引かれ、daemon の 60 秒の期限と競る。発言が届くたびにも名乗り直す */
  src.addEventListener('transcript',()=>{if(Date.now()-_speechLast>10000)speechReady();});
  speechSynthesis.addEventListener('voiceschanged',speechReady);
  ['pointerdown','keydown'].forEach(k=>window.addEventListener(k,speechReady,{once:true}));
  /* 閉じるタブは名乗りを取り下げる。残すと、閉じたタブに送った文が期限まで鳴らない */
  window.addEventListener('pagehide',()=>{
    try{navigator.sendBeacon('/api/talk-speech/ready',JSON.stringify({tab:SPEECH_TAB,langs:[]}));}catch(e){}
  });
  speechReady();
  setInterval(speechReady,30000);
}
/* --- AI分析 の 🔊 の例文: クリックで、いま聞き取っている言語の発音で読む（auto なら言語を指定しない） --- */
function sayLang(){const s=document.getElementById('langSel');const v=s?s.value:'';return v&&v!=='auto'?v:'';}
function decorateSay(root){
  if(!root||!speechOk())return;
  root.querySelectorAll('p,li,blockquote').forEach(el=>{
    const text=String(el.textContent||'').trim();
    if(!text.startsWith('🔊'))return;
    el.classList.add('say');el.title=I18N['dash.say_title']||'';
    el.onclick=e=>{e.stopPropagation();speakText(text.replace(/^🔊\s*/u,''),sayLang());};
  });
}
initSpeech(es);
"""
