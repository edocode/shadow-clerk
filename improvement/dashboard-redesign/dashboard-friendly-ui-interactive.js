const $ = s => document.querySelector(s);
const me = "あなた";

const MINUTES = {
  title: "週次定例",
  meta: "10/30（木）17:12〜17:54 ・ 参加: あなた, alice, bob",
  sections: [
    ["話し合ったこと", ["リリース日程を 11/14 に確定するかどうか", "検索画面の表示速度の改善状況"]],
    ["決まったこと", ["リリースは 11/14（金）で確定", "検索の改善は次のスプリントに回す"]],
    ["宿題", ["alice：リリースノートの下書き（11/7 まで）", "bob：負荷テストの結果共有（来週の定例まで）"]],
  ],
};
const ADVICE = [
  ["q", "要確認", "負荷テストの「目標値」が決まっていません。bob さんに数値を確認しましょう"],
  ["d", "決定", "リリース日は 11/14（金）"],
  ["a", "宿題", "alice：リリースノート下書き — 期限 11/7"],
  ["a", "宿題", "bob：負荷テスト結果 — 期限は「来週」とだけ。日付を決めておくと安心です"],
  ["w", "進行", "検索改善の話が 15 分続いています。次の議題に進んでもよさそうです"],
];
const ANALYSIS = "議題は 2 つ、決定 2 件、宿題 2 件。前回から持ち越した「通知設定の確認」はまだ話されていません。";

const SCRIPT = [
  ["other", "alice", "Let's check the release schedule first.", "まずリリース日程を確認しましょう。"],
  ["me", me, "11/14 で大丈夫そうです。", null],
  ["other", "bob", "The load test is still running, though.", "ただ、負荷テストはまだ実行中です。"],
  ["me", me, "結果はいつ頃出ますか？", null],
  ["other", "bob", "Probably by next week.", "たぶん来週までには。"],
  ["other", "alice", "I'll draft the release notes by the 7th.", "7日までにリリースノートを下書きします。"],
];

const sessions = [
  { id:"today", group:"今日", name:"今日のメモ", sub:"会議以外の会話 · 常に文字起こし", daily:true, summary:false, ai:false,
    lines:[
      ["09:02","me",me,"おはようございます",null],["09:03","other","相手A","おはようございます。昨日の件、見ておきました",null],["09:04","me",me,"ありがとうございます、助かります",null],
      ["10:00","other","相手A","では acme 社との打ち合わせを始めます",null],["10:01","other","相手B","よろしくお願いします。まず見積もりの件からですが",null],["10:02","me",me,"前回いただいた要件で金額を出しています",null],
      ["10:03","other","相手B","内訳を見せていただけますか",null],["10:04","me",me,"画面に出します。開発が7割、テストが2割です",null],["10:05","other","相手A","テストの割合は妥当だと思います",null],
      ["10:06","other","相手B","納期はもう少し早められますか？",null],["10:07","me",me,"範囲を絞れば可能です",null],["10:08","other","相手B","どの機能を後回しにできますか",null],
      ["10:09","me",me,"2週間なら前倒しできます",null],["10:10","other","相手A","管理画面は次の段階でも構いません",null],["10:11","me",me,"それなら 11/14 に出せます",null],
      ["10:12","other","相手B","社内で確認します",null],["10:13","other","相手A","支払い条件は前回どおりでお願いします",null],["10:14","me",me,"承知しました",null],
      ["10:15","other","相手A","では次回までに修正版をお送りします",null],["10:16","other","相手B","負荷テストの目標値はどうしますか",null],["10:17","me",me,"まだ決めていません。来週までに案を出します",null],
      ["10:18","other","相手B","お願いします",null],["10:19","other","相手A","次回は来週の同じ時間で",null],["10:20","me",me,"大丈夫です",null],
      ["10:21","other","相手B","議事録は共有いただけますか",null],["10:22","me",me,"今日中にお送りします",null],["10:23","other","相手A","以上です",null],
      ["10:24","other","相手B","ありがとうございました",null],
      ["12:17","claude","Claude","練習用の会議は終えました。ここで終わりにしますか？",null],["12:18","me",me,"終わります",null],
      ["13:40","other","alice","ちょっといいですか、レビューの件で",null],["13:41","me",me,"はい、どうぞ",null],["13:42","other","alice","テストの書き方を揃えたいです",null],["13:43","me",me,"雛形を作って共有しますね",null],["13:44","other","alice","助かります。金曜までにお願いします",null]] },
  { id:"eng", group:"今日", name:"英語練習", sub:"11:51 · 18分", summary:false, ai:false,
    lines:[["11:51","claude","Claude","Let's practice ordering at a cafe.","カフェでの注文を練習しましょう。"],["11:52","me",me,"I'd like a latte, please.","ラテをお願いします。"]] },
  { id:"weekly", group:"昨日", name:"週次定例", sub:"17:12 · 42分", summary:true, ai:true,
    lines:SCRIPT.map((l,i)=>[`17:${12+i*3}`,l[0],l[1],l[2],l[3]]) },
  { id:"retro", group:"昨日", name:"みんなで振り返り", sub:"13:28 · 55分", summary:true, ai:false,
    lines:[["13:28","other","alice","今回のスプリントで良かったことから話しましょう。",null],["13:30","me",me,"レビューが早く回ったのは良かったです。",null]] },
  { id:"oneon", group:"10/29（水）", name:"1on1", sub:"10:45 · 25分", summary:false, ai:false,
    lines:[["10:45","other","alice","最近どうですか？",null],["10:45","me",me,"順調です。",null]] },
];

const st = { view:"T", left:true, bottom:false, sel:new Set(), anchor:null, menu:null, gapMin:10, cur:"today", rtab:"sum", meeting:null, tr:false, talk:false, mic:true, spk:true, right:true, gen:{}, aiFor:null, step:0, sec:0, labelVariant:"start" };

function toast(m, ...acts) {
  const t=$("#toast"); t.textContent=m;
  for (let k=0;k<acts.length;k+=2) { const b=document.createElement("button"); b.textContent=acts[k]; const fn=acts[k+1]; b.onclick=()=>{ t.classList.remove("show"); fn(); }; t.appendChild(b); }
  t.classList.add("show"); clearTimeout(t._t); t._t=setTimeout(()=>t.classList.remove("show"), acts.length?6000:1800);
}
const cur = () => sessions.find(s=>s.id===st.cur);
const fmt = s => `${String(Math.floor(s/3600)).padStart(2,"0")}:${String(Math.floor(s/60)%60).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`;
const now = () => { const d=new Date(); return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; };

function renderHeader() {
  const L = st.labelVariant==="rec" ? ["⏺ 会議を録音","⏹ 録音を終了"] : ["▶ 会議を開始","⏹ 会議を終了"];
  const b=$("#meetingBtn"); b.textContent = st.meeting ? L[1] : L[0]; b.classList.toggle("stop", !!st.meeting);
  const s=$("#status"), allMuted = !st.mic && !st.spk;
  s.className = "status" + (st.meeting ? " meeting" : "") + (allMuted ? " muted-all" : "");
  $("#statusText").textContent = allMuted ? "ミュート中（文字起こししていません）"
    : st.meeting ? `会議中：${st.meeting.name}　${fmt(st.sec)}` : "文字起こし中（今日のメモ）";
  $("#trBtn").classList.toggle("on", st.tr);
  $("#talkBtn").classList.toggle("on", st.talk);
  for (const [id,on,name] of [["#micBtn",st.mic,"自分の声"],["#spkBtn",st.spk,"相手の声"]]) {
    const e=$(id); e.classList.toggle("off", !on); e.querySelector(".lbl").textContent = on ? name : name+"：ミュート";
  }
  const bn=$("#muteBanner"), msgs=[];
  if (!st.mic) msgs.push("🎤 自分の声はミュート中です。あなたの発言は文字起こしされません。");
  if (!st.spk) msgs.push("🔊 相手の声はミュート中です。相手の発言は文字起こしされません。");
  bn.textContent = msgs.join(" "); bn.classList.toggle("show", msgs.length>0);
}

function renderList() {
  let html="", g=null;
  for (const s of sessions) {
    if (s.group!==g) { g=s.group; html+=`<div class="grp">${g}</div>`; }
    const live = st.meeting && st.meeting.id===s.id || (s.daily && !st.meeting);
    html += `<div class="item ${s.id===st.cur?"act":""}" data-id="${s.id}">
      <div class="t">${s.daily?"🗒 ":""}${s.name}${live?'<span class="pill live">● 記録中</span>':""}</div>
      <div class="s">${s.sub}${s.summary?'<span class="pill sum">議事録あり</span>':""}${s.ai?'<span class="pill ai">AI アドバイスあり</span>':""}</div></div>`;
  }
  $("#list").innerHTML = html;
  document.querySelectorAll(".item").forEach(e=>e.onclick=()=>{ st.cur=e.dataset.id; st.sel.clear(); st.menu=null; renderAll(); });
}

function renderTx(newIdx) {
  const s=cur();
  $("#title").textContent = s.name;
  $("#subtitle").textContent = s.daily ? "会議を開始していない時間の会話はここに残ります" : s.sub;
  const showTr = st.view==="TR" || st.view==="R", onlyTr = st.view==="R";
  $("#colhead").classList.toggle("show", showTr);
  $("#colhead").style.gridTemplateColumns = onlyTr ? "18px 46px 70px 1fr 28px" : "";
  $("#colhead").innerHTML = `<span></span><span>時刻</span><span>話した人</span>${onlyTr?"":"<span>原文</span>"}<span class="trh">🌐 翻訳<span class="spacer"></span><button class="lbtn sm" data-cf="retr" title="翻訳を最初から作り直す">🔄 作り直す</button>${openBtn("translation")}</span>`;
  $("#txOpen").outerHTML = openBtn("transcript", "📄 文字起こしを開く", "txOpen");
  const chunks = s.daily ? findChunks(s) : [];
  const lineHtml = (l,i) => {
    const [ts,cls,who,txt,trn]=l;
    const trCell = `<span class="trn">${st.trGen ? '<span class="muted">⏳ 翻訳し直しています…</span>' : trn ?? (onlyTr ? txt : '<span class="muted">（日本語のため翻訳なし）</span>')}</span>`;
    return `<div class="ln ${onlyTr?"ro":showTr?"tr":""} ${i===newIdx?"new":""} ${st.sel.has(i)?"sel":""}" data-i="${i}"><span class="cb"></span><span class="ts">${ts}</span><span class="who ${cls}">${who}</span>${onlyTr?"":`<span>${txt}</span>`}${showTr?trCell:""}<button class="more" data-more="${i}" title="この行の操作">⋯</button>${st.menu===i?lineMenu(i):""}</div>`;
  };
  let html = "";
  if (chunks.length) chunks.forEach((c,ci)=>{
    if (ci) html += `<div class="gap"><span>${toMin(s.lines[c.from][0])-toMin(s.lines[chunks[ci-1].to][0])}分 会話なし</span></div>`;
    html += `<div class="chunk"><span>💬</span><span class="ct">${s.lines[c.from][0]}〜${s.lines[c.to][0]} の会話</span><span class="muted">${c.to-c.from+1}発言</span>${c.hint?`<span class="muted">📅 ${c.hint}</span>`:""}<span class="spacer"></span><button class="lbtn" data-chunk="${ci}">✂ 会議として切り出す</button></div>`;
    for (let i=c.from;i<=c.to;i++) html += lineHtml(s.lines[i],i);
  });
  else html = s.lines.map(lineHtml).join("");
  $("#tx").innerHTML = html || `<div class="empty"><div class="ic">🎧</div><h3>話し始めると、ここに文字が出ます</h3><p>相手の声とあなたの声を自動で聞き分けます</p></div>`;
  const sg=$("#suggest");
  const narrow = st.view==="AI" || st.view==="CON";
  sg.style.display = s.daily && chunks.length>1 && !st.sugHidden ? "" : "none";
  sg.classList.toggle("compact", narrow);
  sg.innerHTML = (narrow
    ? `💡 <span>会話のまとまりが <b>${chunks.length}つ</b></span><span class="spacer"></span><button class="lbtn sm" id="splitAllBtn">✂ 自動で分ける</button>`
    : `💡 <span>今日のメモに <b>${chunks.length}つの会話のまとまり</b> があります。会議だったものは「✂ 会議として切り出す」すると、議事録や AI のアドバイスを作れます。<br><span class="muted">一部だけ選ぶときは、行をクリック → <span class="kbd">Shift</span>+クリックで範囲選択</span></span><span class="spacer"></span><button class="lbtn" id="splitAllBtn">✂ 全体を自動で分ける</button>`) + `<button class="sg-x" id="sgClose" title="この案内を閉じる">✕</button>`;
  const sx=$("#sgClose"); if (sx) sx.onclick = () => { st.sugHidden=true; renderTx(); toast("案内を閉じました。各まとまりの「✂ 会議として切り出す」はそのまま使えます"); };
  const sb=$("#splitAllBtn"); if (sb) sb.onclick = () => { st.sel.clear(); renderTx(); openExtract("splitAll"); };
  bindTx(chunks);
  renderSelbar();
  const tx=$("#tx"); if (newIdx!==undefined) tx.scrollTop=tx.scrollHeight;
}

const toMin = ts => { const [h,m]=ts.split(":").map(Number); return h*60+m; };
const CAL = [["10:00","10:30","acme 社 打ち合わせ"]];
function findChunks(s, a=0, b=s.lines.length-1) {
  const out=[]; let from=a;
  for (let i=a;i<=b;i++) { const nx = i<b ? s.lines[i+1] : null;
    if (!nx || toMin(nx[0])-toMin(s.lines[i][0]) >= st.gapMin) { out.push({from,to:i}); from=i+1; } }
  out.forEach(c=>{ const a=s.lines[c.from][0]; const ev=CAL.find(([b,e])=>a>=b&&a<e); if (ev) c.hint=`予定「${ev[2]}」の時間帯`; });
  return out;
}
// POST /api/transcript/split-by-silence と同じ判定: gapMin 分以上の沈黙のあとが開始候補 → 1分以内の間隔で3分続けば会議 → 3分の沈黙で終了
function splitSegments(s, a, b) {
  const out=[]; let state="idle", from=null, start=0, last=null;
  for (let i=a;i<=b;i++) { const t=toMin(s.lines[i][0]), gap = last===null ? Infinity : t-last;
    if (state==="candidate" && gap>1) state="idle";
    else if (state==="active" && gap>=3) { out.push({from,to:i-1}); state="idle"; }
    if (state==="idle") { if (gap>=st.gapMin) { state="candidate"; from=i; start=t; } }
    else if (state==="candidate" && t-start>=3) state="active";
    last=t; }
  if (state==="active") out.push({from,to:b});
  out.forEach(c=>{ const a=s.lines[c.from][0]; const ev=CAL.find(([b,e])=>a>=b&&a<e); if (ev) c.hint=`予定「${ev[2]}」の時間帯`; });
  return out;
}
const lineMenu = i => `<div class="lmenu">
  <div data-lm="from">ここから下を選ぶ</div><div data-lm="speaker">👤 話した人を直す</div>
  <div data-lm="copy">📋 この行をコピー</div><div data-lm="delete" class="danger">🗑 この行を削除</div></div>`;

function bindTx(chunks) {
  document.querySelectorAll("#tx .ln").forEach(e=>e.onclick=ev=>{
    if (ev.target.closest(".more,.lmenu")) return;
    const i=+e.dataset.i;
    if (ev.shiftKey && st.anchor!==null) { const [a,b]=[Math.min(st.anchor,i),Math.max(st.anchor,i)]; for(let k=a;k<=b;k++) st.sel.add(k); }
    else { st.sel.has(i) ? st.sel.delete(i) : st.sel.add(i); st.anchor=i; }
    st.menu=null; renderTx();
  });
  document.querySelectorAll("#tx [data-more]").forEach(b=>b.onclick=ev=>{ ev.stopPropagation(); const i=+b.dataset.more; st.menu = st.menu===i?null:i; renderTx(); });
  document.querySelectorAll("#tx [data-lm]").forEach(m=>m.onclick=ev=>{ ev.stopPropagation(); const i=st.menu; st.menu=null;
    if (m.dataset.lm==="from") { st.sel.clear(); cur().lines.forEach((_,k)=>{ if(k>=i) st.sel.add(k); }); renderTx(); return; }
    st.sel=new Set([i]); selAction(m.dataset.lm); });
  document.querySelectorAll("#tx [data-chunk]").forEach(b=>b.onclick=()=>{ const c=chunks[+b.dataset.chunk];
    st.sel=new Set(); for(let k=c.from;k<=c.to;k++) st.sel.add(k); renderTx(); openExtract("extractRange"); });
}

const selIdx = () => [...st.sel].sort((a,b)=>a-b);
function renderSelbar() {
  const s=cur(), idx=selIdx(), bar=$("#selbar");
  bar.classList.toggle("show", idx.length>0);
  if (!idx.length) return;
  const contiguous = idx[idx.length-1]-idx[0]+1===idx.length;
  $("#selCount").textContent = `${idx.length}行を選択中`;
  $("#selRange").innerHTML = `${s.lines[idx[0]][0]}〜${s.lines[idx[idx.length-1]][0]}${contiguous?"":"（とびとび）"}`;
}
function previewHtml(idx) {
  const s=cur(), l=i=>`<div><span class="muted">${s.lines[i][0]}</span> <b>${s.lines[i][2]}</b> ${s.lines[i][3]}</div>`;
  return idx.length<=3 ? idx.map(l).join("") : l(idx[0])+`<div class="dots">⋮ ${idx.length-2}行 ⋮</div>`+l(idx[idx.length-1]);
}
function selAction(a) {
  const s=cur(), idx=selIdx();
  if (a==="clear") { st.sel.clear(); renderTx(); return; }
  if (a==="copy") { toast(`${idx.length}行をコピーしました`); return; }
  if (a==="speaker") { $("#spkSummary").textContent=`${idx.length}行（${s.lines[idx[0]][2]} ほか）`; $("#spkModal").classList.add("show"); return; }
  if (a==="delete") { $("#delSummary").textContent=`${idx.length}行を削除します。この操作は元に戻せません。`; $("#delPreview").innerHTML=previewHtml(idx); $("#delModal").classList.add("show"); return; }
  if (a==="extract") openExtract(idx.length ? "extractRange" : "splitAll");
}
const GROUPS = ["週次定例","みんなで振り返り","1on1","英語練習","acme 社 打ち合わせ"];
function exRange() { const idx=selIdx(); return idx.length ? [idx[0], idx[idx.length-1]] : null; }
function segsHtml(from, to) {
  const s=cur(), segs=splitSegments(s, from, to), used=segs.reduce((n,c)=>n+c.to-c.from+1,0), rest=to-from+1-used;
  if (segs.length<2) return `<div class="muted" style="font-size:11.5px">→ 2つ以上の会議に分かれないため、分けられません${segs.length?"（1つだけなら「そのまま1つの会議にする」を使います）":""}</div>`;
  return `<div class="muted" style="font-size:11.5px">→ ${segs.length}つの会議ファイルができます${rest?`。会議にならなかった短い会話（${rest}行）は今日のメモに残ります`:""}</div>` +
    segs.map(c=>`<div class="seg-i">${s.lines[c.from][0]}〜${s.lines[c.to][0]}　${c.to-c.from+1}発言${c.hint?`　<span class="muted">📅 ${c.hint}</span>`:""}</div>`).join("");
}
function renderExtract() {
  const s=cur(), r=exRange(), mode=document.querySelector("#exModal [data-mode].act")?.dataset.mode;
  document.querySelectorAll("#exModal [data-mode]").forEach(x=>x.classList.toggle("disabled", x.dataset.mode!=="splitAll" && !r));
  $("[data-segs=all]").innerHTML = segsHtml(0, s.lines.length-1);
  if (r) {
    $("[data-segs=range]").innerHTML = segsHtml(r[0], r[1]);
    const rng=[]; for (let k=r[0];k<=r[1];k++) rng.push(k);
    $("#exSummary").textContent=`範囲: ${s.lines[r[0]][0]} 〜 ${s.lines[r[1]][0]}　${rng.length}行が対象です`;
    $("#exPreview").innerHTML=previewHtml(rng);
  }
  $("#exTargetBox").style.display = mode==="extractRange" ? "" : "none";
  $("#exFoot").textContent = mode==="extractRange" ? "切り出した行は今日のメモから会議ファイルへ移ります。🗑 の「日次ファイルに戻す」で戻せます。"
    : "分けた会議は「名前なし」で作られます。名前はあとから 📂 で付けられます。";
  $("#exOk").textContent = mode==="extractRange" ? "作成" : "分ける";
}
function pickRadio(sel, el) { document.querySelectorAll(sel).forEach(x=>{ x.classList.toggle("act",x===el); x.querySelector("input[type=radio]").checked = x===el; }); }
function openExtract(mode) {
  const s=cur();
  document.querySelectorAll("#exModal .gapSel").forEach(g=>{ g.innerHTML=[1,2,3,5,10,15,20,30].map(v=>`<option ${v===st.gapMin?"selected":""}>${v}</option>`).join(""); });
  pickRadio("#exModal [data-mode]", $(`#exModal [data-mode=${mode}]`));
  pickRadio("#exModal [data-tgt]", $("#exModal [data-tgt=new]"));
  const r=exRange(), first = r ? s.lines[r[0]][0] : null;
  const ev = first && CAL.find(([b,e])=>first>=b&&first<e);
  $("#exGroup").innerHTML = GROUPS.map(g=>`<option ${ev&&ev[2]===g?"selected":""}>${g}</option>`).join("");
  document.querySelector(`#exModal [name=exn][value=${ev?"group":"adhoc"}]`).checked = true;
  $("#exName").value="";
  $("#exHint").textContent = ev ? `📅 同じ時間帯の予定「${ev[2]} ${ev[0]}〜${ev[1]}」から選びました` : "";
  $("#exTarget").innerHTML = sessions.filter(x=>!x.daily && x.id!==s.id && ["今日","昨日"].includes(x.group)).map(x=>`<option value="${x.id}">${x.name}（${x.group} ${x.sub.split(" ")[0]}）</option>`).join("");
  renderExtract();
  $("#exModal").classList.add("show");
}
document.querySelectorAll("#selbar [data-sa]").forEach(b=>b.onclick=()=>selAction(b.dataset.sa));
document.querySelectorAll("#exModal [data-mode]").forEach(r=>r.onclick=e=>{ if (e.target.tagName==="SELECT") return; pickRadio("#exModal [data-mode]", r); renderExtract(); });
document.querySelectorAll("#exModal [data-tgt]").forEach(r=>r.onclick=e=>{ if (/SELECT|INPUT/.test(e.target.tagName) && e.target.type!=="radio") { if (r.classList.contains("act")) return; } pickRadio("#exModal [data-tgt]", r); });
document.querySelectorAll("#exModal .gapSel").forEach(g=>g.onchange=()=>{ st.gapMin=+g.value; document.querySelectorAll("#exModal .gapSel").forEach(x=>x.value=g.value); renderExtract(); renderTx(); });
$("#exName").onfocus = () => { document.querySelector("#exModal [name=exn][value=newname]").checked = true; };
$("#exGroup").onfocus = () => { document.querySelector("#exModal [name=exn][value=group]").checked = true; };
$("#exCancel").onclick = () => $("#exModal").classList.remove("show");
$("#exOk").onclick = () => {
  $("#exModal").classList.remove("show");
  const s=cur(), before=s.lines.slice(), mode=document.querySelector("#exModal [data-mode].act").dataset.mode;
  const r = mode==="splitAll" ? [0, s.lines.length-1] : exRange();
  const created=[]; let appended=null;
  const mk = (name, lines) => { const d={ id:"x"+Date.now()+created.length, group:"今日", name, sub:`${lines[0][0]} · ${toMin(lines.at(-1)[0])-toMin(lines[0][0])+1}分`, summary:false, ai:false, lines }; created.push(d); return d; };
  if (mode==="extractRange") {
    const lines=s.lines.slice(r[0], r[1]+1);
    if (document.querySelector("#exModal [data-tgt].act").dataset.tgt==="existing") { appended={ d:sessions.find(x=>x.id===$("#exTarget").value), n:lines.length }; appended.d.lines.push(...lines); }
    else { const t=document.querySelector("#exModal [name=exn]:checked").value;
      mk(t==="group" ? $("#exGroup").value : t==="newname" ? ($("#exName").value||"名前なしの会議") : "名前なしの会議", lines); }
  } else { const segs=splitSegments(s, r[0], r[1]);
    if (segs.length<2) { toast("2つ以上の会議に分かれないため、分けられませんでした"); return; }
    segs.forEach(c=>mk(`名前なしの会議 ${s.lines[c.from][0]}`, s.lines.slice(c.from, c.to+1)));
    var consumed=new Set(segs.flatMap(c=>Array.from({length:c.to-c.from+1},(_,k)=>c.from+k))); }
  sessions.splice(sessions.findIndex(x=>x.daily)+1, 0, ...created);
  s.lines = s.lines.filter((_,i)=> consumed ? !consumed.has(i) : i<r[0]||i>r[1]); st.sel.clear(); renderAll();
  const dst = appended ? appended.d : created[0], msg = created.length>1 ? `${created.length}件の会議ファイルに分けました` : `「${dst.name}」に${appended?"付け足しました":"保存しました"}`;
  const open = () => { st.cur=dst.id; renderAll(); };
  // 元に戻す = 作った会議ファイルを merge-to-daily。既存ファイルへの付け足しは、そのファイルごと戻ってしまうので出さない
  if (appended) toast(msg, "開く", open);
  else toast(msg, "元に戻す", () => {
    s.lines=before; created.forEach(d=>sessions.splice(sessions.indexOf(d),1));
    st.cur=s.id; renderAll(); toast("今日のメモに戻しました"); }, "開く", open);
};
$("#spkCancel").onclick = () => $("#spkModal").classList.remove("show");
$("#spkOk").onclick = () => { const s=cur(), who=$("#spkSel").value;
  selIdx().forEach(i=>{ s.lines[i][2]=who; s.lines[i][1]= who===me?"me":"other"; });
  $("#spkModal").classList.remove("show"); st.sel.clear(); renderTx(); toast(`話した人を「${who}」に直しました`); };
$("#delCancel").onclick = () => $("#delModal").classList.remove("show");
$("#delOk").onclick = () => { const s=cur(), n=st.sel.size; s.lines=s.lines.filter((_,i)=>!st.sel.has(i)); st.sel.clear();
  $("#delModal").classList.remove("show"); renderAll(); toast(`${n}行を削除しました`); };
document.addEventListener("keydown", e => { if (e.key==="Escape" && st.sel.size) { st.sel.clear(); st.menu=null; renderTx(); } });

const EXT = { transcript:"txt", translation:"txt", summary:"md", advice:"md", analysis:"md" };
function fileName(kind, s=cur()) {
  const base = s.daily ? "20261031" : s.id==="weekly" ? "202610301712@週次定例" : `2026103${s.group==="今日"?1:0}${(s.sub.match(/\d\d:\d\d/)||["0000"])[0].replace(":","")}@${s.name}`;
  return `${kind}-${base}.${EXT[kind]}`;
}
function openBtn(kind, label="📄 開く", id="") {
  const fn=fileName(kind);
  return `<button class="lbtn sm" ${id?`id="${id}"`:""} data-open="${fn}" title="${fn} を開く">${label}<span class="fname adv-only"> ${fn}</span></button>`;
}
const CONFIRMS = {
  resum: ["議事録を作り直しますか？", "今の議事録を、文字起こしから最初から作り直します。手で直した部分は消えます。", "作り直す", () => act("regen")],
  retr: ["翻訳を作り直しますか？", "この会議の翻訳を、最初からすべて作り直します。", "作り直す", () => { st.trGen=true; renderTx(); setTimeout(()=>{ st.trGen=false; renderTx(); toast("翻訳を作り直しました"); },1600); }],
};
document.addEventListener("click", e => {
  const o=e.target.closest("[data-open]"); if (o) { toast(`${o.dataset.open} を新しいタブで開きます`); return; }
  const c=e.target.closest("[data-cf]"); if (c) { const [t,d,ok,fn]=CONFIRMS[c.dataset.cf];
    $("#cfTitle").textContent=t; $("#cfText").textContent=d; $("#cfOk").textContent=ok; $("#cfOk").onclick=()=>{ $("#cfModal").classList.remove("show"); fn(); }; $("#cfModal").classList.add("show"); }
});
function minutesHtml(s) {
  const m = s.id==="weekly" ? MINUTES : { title:s.name, meta:`${s.sub} ・ 参加: あなた, alice`, sections:[["話し合ったこと",["（デモ用の要約）"+s.lines.length+" 件の発言から作成"]],["決まったこと",["特になし"]],["宿題",["なし"]]] };
  return `<div class="rtools"><button class="lbtn" onclick="toast('議事録をコピーしました')">📋 コピー</button><button class="lbtn" onclick="toast('最新の議事録を読み込み直しました')" title="ファイルを読み込み直す">↻ 再読み込み</button><button class="lbtn" data-cf="resum">🔄 作り直す</button>${openBtn("summary")}</div>
    <div class="doc"><h3>${m.title}</h3><div class="meta">${m.meta}</div>
    ${m.sections.map(([h,items])=>`<h4>${h}</h4><ul>${items.map(i=>`<li>${i}</li>`).join("")}</ul>`).join("")}</div>`;
}

function aiPaneHtml(s) {
  const isLive = st.meeting && st.meeting.id===s.id;
  const running = st.aiFor===s.id;
  const other = st.aiFor && !running ? `<div class="hint">AI アシスタントは同時に1つだけ動きます。いまは「${sessions.find(x=>x.id===st.aiFor).name}」を見ています。押すとこの会議に切り替えます。</div>` : "";
  if (st.gen[s.id]==="ai") return `<div class="empty"><div class="spinner"></div><h3>AI アシスタントを起動しています…</h3><p>文字起こしを読み込んでいます</p></div>`;
  else if (s.ai || running) {
      const n = isLive ? Math.min(ADVICE.length, 1+Math.floor(st.step/1.5)) : ADVICE.length;
      return (running||isLive ? `<div class="astat"><span class="dot"></span>AI アシスタントが会議を見守っています<span class="spacer"></span><button class="lbtn" data-act="aistop">止める</button></div>` : `<div class="astat" style="animation:none"><span class="muted">AI アシスタントは止まっています</span><span class="spacer"></span><button class="lbtn" data-act="ai">▶ 分析を再開</button></div>${other}`)
        + `<div class="aigrid"><div class="aicol"><div class="secttl">いま気をつけること・決まったこと <span class="muted aitag">Advice</span> ${openBtn("advice")}</div>`
        + ADVICE.slice(0,n).map(([k,lab,t])=>`<div class="card"><span class="k ${k}">${lab}</span>${t}</div>`).join("")
        + `</div><div class="aicol"><div class="secttl">会議全体の分析 <span class="muted aitag">Analysis</span> ${openBtn("analysis")}</div><div class="card">${isLive && n<ADVICE.length ? '<span class="muted">会議が進むと、ここにまとめが出ます</span>' : ANALYSIS}</div></div></div>`;
  } else return `<div class="empty"><div class="ic">💡</div><h3>AI のアドバイスはまだありません</h3><p>AI アシスタントが文字起こしを読んで、<br><b>確認が必要な点・決まったこと・宿題・進行のヒント</b><br>をここに書き出します。会議中でも終わった後でも使えます。</p><button class="cta" data-act="ai">AI アシスタントに見てもらう</button>${other}</div>`;
}
function renderRight() {
  document.querySelectorAll(".rtabs button").forEach(b=>b.classList.toggle("act", b.dataset.t===st.rtab));
  const s=cur(), rb=$("#rbody"), isLive = st.meeting && st.meeting.id===s.id;
  if (st.rtab==="sum") {
    if (st.gen[s.id]==="sum") rb.innerHTML = `<div class="empty"><div class="spinner"></div><h3>議事録を作っています…</h3><p>${s.lines.length} 件の発言をまとめています</p></div>`;
    else if (s.summary) rb.innerHTML = minutesHtml(s);
    else if (isLive) rb.innerHTML = `<div class="empty"><div class="ic">⏳</div><h3>会議中です</h3><p>議事録は会議が終わったら作れます。<br>途中経過を見たいときは、今までの分だけでも作れます。</p><button class="cta ghost" data-act="sum">今までの分で作る</button></div>`;
    else rb.innerHTML = `<div class="empty"><div class="ic">📝</div><h3>まだ議事録がありません</h3><p>文字起こしから、話し合ったこと・決まったこと・宿題をまとめます。</p><button class="cta" data-act="sum">議事録を作る</button></div>`;
  } else {
    rb.innerHTML = aiPaneHtml(s);
  }
  rb.querySelectorAll("[data-act]").forEach(b=>b.onclick=()=>act(b.dataset.act));
}

function act(a) {
  const s=cur();
  if (a==="sum"||a==="regen") { st.gen[s.id]="sum"; renderRight(); setTimeout(()=>{ delete st.gen[s.id]; s.summary=true; renderAll(); toast("議事録ができました"); },1600); }
  if (a==="ai") { st.gen[s.id]="ai"; renderRight(); setTimeout(()=>{ delete st.gen[s.id]; const prev=st.aiFor && st.aiFor!==s.id && sessions.find(x=>x.id===st.aiFor); st.aiFor=s.id; s.ai=true; renderAll(); if (prev) toast(`AI アシスタントの見る会議を「${prev.name}」からこの会議に切り替えました`); },1400); }
  if (a==="aistop") { st.aiFor=null; renderAll(); toast("AI アシスタントを止めました（これまでの内容は残ります）"); }
}

function renderDrawer() {
  const d=document.querySelector(".drawer .dh button.act").dataset.d;
  const running = !!st.aiFor;
  $("#drawerStat").textContent = running ? "● AI アシスタント動作中" : "待機中";
  $("#drawerBody").innerHTML = d==="ai" ? (running ? "&gt; clerk-meeting-helper を実行中…<br>&gt; transcript を監視しています" : "AI アシスタントは止まっています。「AI のアドバイス」タブから起動できます。")
    : d==="talk" ? (st.talk ? "&gt; clerk-talk 実行中" : "Claude と会議 は止まっています。")
    : "[INFO] capture: mic ok, monitor ok<br>[INFO] model: reazonspeech-k2";
}

function renderAll() { renderHeader(); renderList(); renderTx(); renderRight(); renderDrawer();
  $("#app").classList.toggle("no-right", !st.right); $("#right").style.display = st.right ? "" : "none";
  const aim = st.view==="AI";
  $("#app").classList.toggle("aimode", aim);
  $("#app").style.gridTemplateColumns = aim ? `${st.left?"230px":"0"} 1fr 340px` : `${st.left?"230px":"0"} 1fr ${st.right?"380px":"0"}`;
  if (aim) $("#right").style.display = "";
  document.querySelector("aside").style.display = st.left ? "" : "none";
  $("#edgeL").textContent = st.left ? "◀" : "▶"; $("#edgeR").textContent = st.right ? "▶" : "◀";
  $("#drawer").classList.toggle("open", st.bottom); $("#drawerToggle").textContent = st.bottom ? "▼" : "▲";
  const mainEl=document.querySelector("main");
  mainEl.classList.toggle("aiview", st.view==="CON"); mainEl.classList.toggle("narrow", aim || st.view==="CON");
  $("#edgeR").style.display = aim ? "none" : "";
  $("#aicon").innerHTML = `<div class="ah">🤖 AI アシスタントの画面 <span class="spacer"></span><span>${!!st.aiFor?"● 動作中":"待機中"}</span></div>`
    + "&gt; clerk-meeting-helper<br>transcript を監視しています…<br><br>● 要確認: 負荷テストの目標値が未定<br>● 決定: リリース日 11/14<br><br><span style='color:#e5e7eb'>&gt; </span><span style='animation:blink 1s infinite'>▍</span>";
  renderViewMenu(); }

/* ---- events ---- */
$("#meetingBtn").onclick = () => {
  if (st.meeting) {
    const s = sessions.find(x=>x.id===st.meeting.id);
    s.sub = `${s.lines[0]?.[0] ?? now()} · ${Math.max(1,Math.round(st.sec/60))}分`;
    st.meeting=null; renderAll();
    toast("会議を終了しました。この後の会話は「今日のメモ」に残ります");
    if (!s.summary) { st.rtab="sum"; renderRight(); }
  } else {
    $("#modalTitle").textContent = st.labelVariant==="rec" ? "会議を録音" : "会議を開始";
    $("#modal").classList.add("show");
  }
};
$("#mCancel").onclick = () => $("#modal").classList.remove("show");
$("#mOk").onclick = () => {
  $("#modal").classList.remove("show");
  const id="m"+Date.now(), name=$("#mName").value||"会議";
  sessions.unshift({ id, group:"今日", name, sub:`${now()} 〜`, summary:false, ai:false, lines:[] });
  st.meeting={id,name}; st.cur=id; st.step=0; st.sec=0;
  if ($("#mAssist").checked) { st.aiFor=id; st.rtab="ai"; }
  renderAll();
};
$("#trBtn").onclick = () => { st.tr=!st.tr;
  if (st.tr && st.view==="T") { st.view="TR"; toast("翻訳を始めました。文字起こしの横に翻訳を表示します"); }
  else toast(st.tr ? "翻訳を始めました" : "翻訳を止めました（これまでの翻訳はそのまま見られます）");
  renderAll(); };
const VIEWS = [
  ["T","文字起こしだけ",'<i class="t"></i>'],
  ["TR","文字起こし＋翻訳",'<i class="t"></i><i class="r"></i>'],
  ["R","翻訳だけ",'<i class="r"></i>'],
  ["AI","議事録・AI のアドバイスを大きく",'<i class="a"></i><i class="t n"></i>'],
  ["CON","AI アシスタントの画面と作業",'<i class="c"></i><i class="t n"></i>'],
];
function setView(v) { st.view=v; if (v==="AI") { st.right=true; st.rtab="ai"; } if (v==="CON") { st.right=true; st.rtab="ai"; } renderAll(); }
function renderViewMenu() {
  const tog=(k,label,adv)=>`<div class="ptog ${st[k]?"on":""} ${adv?"adv-only":""}" data-pt="${k}"><span class="sw2"></span>${label}<span class="spacer"></span><span class="kbd">${{left:"Alt+[",right:"Alt+]",bottom:"Alt+\\"}[k]}</span></div>`;
  $("#viewMenu").innerHTML = `<div class="vm-t">真ん中に出すもの</div><div class="vgrid">`
    + VIEWS.map(([k,l,th],i)=>`<div class="vopt ${st.view===k?"act":""} ${k==="CON"?"adv-only":""}" data-v="${k}"><div class="thumb">${th}</div>${l}<span class="kbd kb">Alt+${i+1}</span></div>`).join("")
    + `</div><div class="vm-t" style="margin-top:12px">まわりのパネル</div>`
    + tog("left","左：会議の一覧") + tog("right","右：議事録・AI のアドバイス") + tog("bottom","下：AI アシスタントの画面・ログ", true)
    + `<div class="hint" style="margin:8px 4px 0">${st.tr?"":"翻訳を出すには、上の「🌐 翻訳」で翻訳を始めてください（過去の翻訳はそのまま表示できます）"}</div>`;
  document.querySelectorAll("#viewMenu [data-v]").forEach(e=>e.onclick=ev=>{ ev.stopPropagation(); setView(e.dataset.v); });
  document.querySelectorAll("#viewMenu [data-pt]").forEach(e=>e.onclick=ev=>{ ev.stopPropagation(); st[e.dataset.pt]=!st[e.dataset.pt]; renderAll(); });
}
$("#viewBtn").onclick = e => { e.stopPropagation(); $("#menu").classList.remove("open"); $("#viewMenu").classList.toggle("open"); };
$("#viewMenu").onclick = e => e.stopPropagation();
document.addEventListener("click", () => $("#viewMenu").classList.remove("open"));
$("#edgeL").onclick = () => { st.left=!st.left; renderAll(); };
$("#edgeR").onclick = () => { st.right=!st.right; renderAll(); };
document.addEventListener("keydown", e => { if (!e.altKey) return;
  const n=+e.key; if (n>=1 && n<=5) { setView(VIEWS[n-1][0]); e.preventDefault(); }
  if (e.key==="[") st.left=!st.left; if (e.key==="]") st.right=!st.right; if (e.key==="\\") st.bottom=!st.bottom;
  if ("[]\\".includes(e.key)) { renderAll(); e.preventDefault(); } });
$("#talkBtn").onclick = () => { if (st.talk) { st.talk=false; $("#talk").classList.remove("show"); renderAll(); toast("Claude との会議を終了しました"); } else openTalk(); };
$("#talkEnd").onclick = () => $("#talkBtn").click();
$("#extractBtn").onclick = () => selAction("extract");
$("#micBtn").onclick = () => { st.mic=!st.mic; renderAll(); };
$("#spkBtn").onclick = () => { st.spk=!st.spk; renderAll(); };
$("#moreBtn").onclick = e => { e.stopPropagation(); $("#menu").classList.toggle("open"); };
document.addEventListener("click", () => $("#menu").classList.remove("open"));
$("#modeSeg").onclick = e => { const m=e.target.dataset.m; if(!m) return;
  document.body.classList.toggle("simple", m==="simple");
  if (m==="simple" && st.view==="CON") { st.view="T"; st.bottom=false; renderAll(); }
  [...$("#modeSeg").children].forEach(b=>b.classList.toggle("act", b.dataset.m===m)); };
$("#themeBtn").onclick = () => { document.body.classList.toggle("light"); $("#themeBtn").textContent = document.body.classList.contains("light")?"☀":"🌙"; };
document.querySelectorAll(".rtabs button").forEach(b=>b.onclick=()=>{ st.rtab=b.dataset.t; renderRight(); });
document.querySelectorAll(".drawer .dh button[data-d]").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".drawer .dh button[data-d]").forEach(x=>x.classList.toggle("act", x===b));
  st.bottom=true; renderAll(); });
$("#drawerToggle").onclick = () => { st.bottom=!st.bottom; renderAll(); };
$("#labelVariant").onchange = e => { st.labelVariant=e.target.value; renderHeader(); };
$("#nameBtn").onclick = () => toast("「相手A」→「alice」のように名前を付けられます（デモでは省略）");
$("#demoNewLine").onclick = () => addLine(true);

/* ---- simulation ---- */
function addLine(forceOther) {
  const target = st.meeting ? sessions.find(s=>s.id===st.meeting.id) : sessions.find(s=>s.daily);
  const l = forceOther ? SCRIPT.find(x=>x[0]==="other") : SCRIPT[st.step % SCRIPT.length];
  if (!forceOther) st.step++;
  if ((l[0]==="me" && !st.mic) || (l[0]==="other" && !st.spk)) { renderRight(); return; }
  target.lines.push([now(), l[0], l[1], l[2], l[3]]);
  if (target.id===st.cur) { renderTx(target.lines.length-1); renderRight(); }
}
setInterval(() => { if (st.meeting) { st.sec++; renderHeader(); } }, 1000);
setInterval(() => { if (st.meeting) addLine(false); }, 3500);
setInterval(() => {
  $("#micLv").style.width = (st.mic ? 10+Math.random()*60 : 0)+"%";
  $("#spkLv").style.width = (st.spk ? 10+Math.random()*80 : 0)+"%";
}, 250);

const PERSONAS = ["(なし)", "やさしい先生", "辛口レビュアー", "聞き上手"];
const MODES = [
  { name:"自由に相談", desc:"議題について一緒に考える", topic:"", persona:"聞き上手", route:"self",
    talk:[["cl","こんにちは。何について話しましょうか？"],["me","今日の定例の宿題を整理したい"],["cl","宿題は 2 つです。alice さんのリリースノートと、bob さんの負荷テスト結果ですね。"]] },
  { name:"英語の練習", desc:"発音・会話を声で練習", topic:"カフェでの注文", persona:"やさしい先生", route:"self",
    talk:[["cl","Let's practice ordering at a cafe. What would you like?"],["me","I'd like a latte, please."],["cl","Great! 発音はとても自然です。「please」の最後をもう少し伸ばすとより丁寧に聞こえます。"]] },
  { name:"コードレビュー", desc:"作業ディレクトリのコードを一緒に見る", topic:"今日の変更をレビュー", persona:"辛口レビュアー", route:"self",
    talk:[["cl","作業ディレクトリの差分を見ました。3 ファイル変わっています。"],["me","気になるところはある？"],["cl","エラー時の戻り値が 1 か所だけ揃っていません。そこから見ましょう。"]] },
  { name:"会議に参加", desc:"Claude の声を会議アプリに流して同席", topic:"", persona:"(なし)", route:"app",
    talk:[["cl","皆さんこんにちは、Claude です。今日は記録と論点の整理を手伝います。"],["me","よろしく"],["cl","最初の議題はリリース日程ですね。"]] },
];
let tMode=0;
function renderTalkModes() {
  $("#tmodes").innerHTML = MODES.map((m,i)=>`<div class="tmode ${i===tMode?"act":""}" data-tm="${i}"><b>${m.name}</b><span class="muted">${m.desc}</span></div>`).join("")
    + `<div class="tmode" style="border-style:dashed;text-align:center" data-tm="new"><b>＋</b><span class="muted">新しいモードを作る</span></div>`;
  document.querySelectorAll("[data-tm]").forEach(e=>e.onclick=()=>{ if (e.dataset.tm==="new") { toast("いまの入力内容を新しいモードとして保存できます（下の「今の設定をモードとして保存」）"); return; } tMode=+e.dataset.tm; applyMode(); });
}
function applyMode() {
  const m=MODES[tMode];
  $("#tTopic").value=m.topic; $("#tPersona").value=m.persona;
  pickRadio("#talkModal [data-route]", $(`#talkModal [data-route=${m.route}]`));
  renderTalkModes();
}
function openTalk() { $("#tPersona").innerHTML=PERSONAS.map(p=>`<option>${p}</option>`).join(""); applyMode(); $("#talkModal").classList.add("show"); }
document.querySelectorAll("#talkModal [data-route]").forEach(r=>r.onclick=()=>pickRadio("#talkModal [data-route]", r));
$("#tCancel").onclick = () => $("#talkModal").classList.remove("show");
$("#tSave").onclick = () => toast("モード名を付けて保存（現行の「名前を付けて保存」と同じ）");
$("#tOk").onclick = () => {
  $("#talkModal").classList.remove("show");
  const m=MODES[tMode]; st.talk=true;
  $("#talkModeName").textContent = `— ${m.name}${$("#tTopic").value?`：${$("#tTopic").value}`:""}`;
  $("#talk").classList.add("show"); startTalk(m.talk); renderAll();
};
function startTalk(TALK) {
  const tb=$("#talkBody"); tb.innerHTML="";
  TALK.forEach(([w,t],i)=>setTimeout(()=>{ if(!st.talk) return;
    tb.insertAdjacentHTML("beforeend",`<div class="bub ${w}">${t}</div>`); tb.scrollTop=tb.scrollHeight;
    $("#listenText").textContent = w==="cl" ? "🔈 Claude が話しています…" : "聞いています… 話しかけてください";
    const d=sessions.find(s=>st.meeting ? s.id===st.meeting.id : s.daily); d.lines.push([now(), w==="cl"?"claude":"me", w==="cl"?"Claude":me, t, null]);
    if (st.cur===d.id) renderTx(d.lines.length-1);
  }, 700+i*1800));
}

renderAll();
