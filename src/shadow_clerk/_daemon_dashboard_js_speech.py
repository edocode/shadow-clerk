"""Shadow-clerk daemon: ダッシュボード JavaScript（ブラウザの読み上げ）

talk mode で Claude が話す練習言語の文（/api/say の lang 付き）と、AI分析 の 🔊 の例文を、このタブの
speechSynthesis で読む。VOICEVOX は日本語の声なので、英語などはブラウザの声のほうがお手本になる。
"""
from __future__ import annotations

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
/* --- AI分析 の 🔊 の例文: クリックで読む。言語は行頭の 🔊[en] で決める。
   無ければいま聞き取っている言語（練習の前後は ja / auto に戻っているので、かな・漢字の無い文は en とみなす）。
   🔊[en|I see a cheap ship.] 問題1 は「問題1」とだけ見せて | の後ろを読む（聞き取りの出題。綴りを見せない） --- */
const SAY_TAG=/^🔊\s*(?:\[([a-z]{2,3})(?:\|([^\]]+))?\]\s*)?/u;
/* 聞き直しの通知: 英文のキー（cyrb53）と、talk の PTY に送る一行。制御文字は空白にし、200 字で切る */
function cyrb53(str){let h1=0xdeadbeef,h2=0x41c6ce57;
  for(let i=0;i<str.length;i++){const c=str.charCodeAt(i);h1=Math.imul(h1^c,2654435761);h2=Math.imul(h2^c,1597334677);}
  h1=Math.imul(h1^(h1>>>16),2246822507);h1^=Math.imul(h2^(h2>>>13),3266489909);
  h2=Math.imul(h2^(h2>>>16),2246822507);h2^=Math.imul(h1^(h1>>>13),3266489909);
  return (4294967296*(2097151&h2)+(h1>>>0)).toString(36);}
function replayKey(text){return cyrb53(String(text));}
function replayNote(text,count){
  const t=Array.from(String(text).replace(/[\u0000-\u001f\u007f]/g,' ').replace(/\s+/g,' ').trim()).slice(0,200).join('').trim();
  return t?`[練習] 聞き直し: 「${t}」（この文は${count}回目）`:null;}
/* talk の PTY へ本文・Enter の順に送る。Enter は本文と同時に届くと送信にならないので 200 ms 空ける。前の送信が終わってから次 */
let _talkSendQ=Promise.resolve();
function _postTalk(data){
  return fetch('/api/console/input',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({role:'talk',data})}).catch(()=>{});}
function sendTalkConsole(text){
  const run=()=>_postTalk(text).then(()=>new Promise(r=>setTimeout(r,200))).then(()=>_postTalk('\r'));
  _talkSendQ=_talkSendQ.then(run,run);return _talkSendQ;}
/* 押した回数を英文ごとに数える（ページを読み直すと 0 に戻る）。talk が動いているときだけ送る */
const replayCounts=new Map();
function noteReplay(text){
  if(!replayNote(text,1))return null;
  const key=replayKey(text),n=(replayCounts.get(key)||0)+1;
  replayCounts.set(key,n);
  if(typeof talkActive!=='undefined'&&talkActive)sendTalkConsole(replayNote(text,n));
  return n;}
function sayLang(text,tag){
  if(tag)return tag;
  const s=document.getElementById('langSel');const v=s&&s.value!=='auto'?s.value:'';
  return (!v||v==='ja')&&!/[\p{sc=Hiragana}\p{sc=Katakana}\p{sc=Han}]/u.test(text)?'en':v;
}
/* 表示からは [en] と [en|読む文] を消す。先頭のテキストノードにある */
function _dropSayTag(el){
  const w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
  for(let n=w.nextNode();n;n=w.nextNode()){if(n.nodeValue.trim()){n.nodeValue=n.nodeValue.replace(/\[[a-z]{2,3}(?:\|[^\]]*)?\]\s*/,' ');return;}}
}
function decorateSay(root){
  if(!root||!speechOk())return;
  /* 引用の中の段落のように入れ子で両方当たるので、タグを消す前に全部読み取る */
  const hits=[...root.querySelectorAll('p,li,blockquote')].map(el=>{
    const t=String(el.textContent||'').trim(),m=t.match(SAY_TAG);
    return m&&{el,text:m[2]||t.slice(m[0].length),tag:m[1]};
  }).filter(Boolean);
  hits.forEach(({el,text,tag})=>{
    if(tag)_dropSayTag(el);
    el.classList.add('say');el.title=I18N['dash.say_title']||'';
    el.onclick=e=>{e.stopPropagation();speakText(text,sayLang(text,tag));noteReplay(text);};
  });
}
initSpeech(es);
"""
