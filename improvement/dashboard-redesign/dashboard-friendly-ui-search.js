// 左ペイン「検索」: 現行の /api/search と同じ条件（キーワード・対象・年/月/日/時）で、結果を会議ごとにまとめて本文も見せる
const SR_DATE = { "今日":"2026-10-31", "昨日":"2026-10-30", "10/29（水）":"2026-10-29" };
const SR_TYPES = [["all","すべて"],["transcript","文字起こし"],["translation","翻訳"],["summary","議事録"]];
const SR_LIMIT = 200;
st.sq = { q:"", type:"all", y:"", m:"", d:"", h:"", dateOpen:false, results:null };

const srDt = s => { const [y,m,d]=(SR_DATE[s.group]||"").split("-"), h=s.daily?"":s.sub.slice(0,2); return { y, m, d, h }; };  // 日次ファイルは時刻を持たない
const srSummary = s => s.summary ? (s.id==="weekly" ? MINUTES.sections.flatMap(([,items])=>items) : [`（デモ用の要約）${s.lines.length} 件の発言から作成`]) : [];
// サーバーと同じ: 大文字小文字を無視した部分一致、日付だけならファイル単位、200 件で打ち切り
function srRun() {
  const q=st.sq.q.trim().toLowerCase(), t=st.sq.type, out=[];
  if (!q && !(st.sq.y||st.sq.m||st.sq.d||st.sq.h)) { st.sq.results=null; return; }
  for (const s of sessions) {
    const dt=srDt(s);
    if (["y","m","d","h"].some(k=>st.sq[k] && st.sq[k]!==dt[k])) continue;
    if (!q) { out.push({ s, type:"transcript", i:-1 }); continue; }
    const hit = (type, texts) => texts.forEach((x,i)=>{ if (x && x.toLowerCase().includes(q) && out.length<SR_LIMIT) out.push({ s, type, i, text:x }); });
    if (t==="all"||t==="transcript") hit("transcript", s.lines.map(l=>l[3]));
    if (t==="all"||t==="translation") hit("translation", s.lines.map(l=>l[4]));
    if (t==="all"||t==="summary") hit("summary", srSummary(s));
  }
  st.sq.results=out;
}
const srMark = x => { const q=st.sq.q.trim(); if (!q) return x; const i=x.toLowerCase().indexOf(q.toLowerCase());
  return i<0 ? x : `${x.slice(0,i)}<mark>${x.slice(i,i+q.length)}</mark>${x.slice(i+q.length)}`; };
const srOpt = (k, label, vals) => `<select data-sd="${k}"><option value="">${label}</option>${vals.map(v=>`<option ${st.sq[k]===v?"selected":""}>${v}</option>`).join("")}</select>`;
const pad = n => String(n).padStart(2,"0");

function searchHtml() {
  const sq=st.sq, dated=sq.y||sq.m||sq.d||sq.h;
  let html = `<div class="sr-form"><div class="sr-q"><input id="srQ" placeholder="🔍 キーワード" value="${sq.q}"><button class="lbtn" id="srGo">検索</button></div>
    <div class="sr-types">${SR_TYPES.map(([v,l])=>`<button class="sr-t ${sq.type===v?"act":""}" data-st="${v}">${l}</button>`).join("")}</div>
    <button class="sr-dt" id="srDtBtn">📅 日付で絞る${dated?`：${[sq.y&&sq.y+"年",sq.m&&+sq.m+"月",sq.d&&+sq.d+"日",sq.h&&+sq.h+"時台"].filter(Boolean).join("")}`:""} ${sq.dateOpen?"▴":"▾"}</button>
    ${sq.dateOpen ? `<div class="sr-dates">${srOpt("y","年",["2026","2025"])}${srOpt("m","月",Array.from({length:12},(_,i)=>pad(i+1)))}${srOpt("d","日",Array.from({length:31},(_,i)=>pad(i+1)))}${srOpt("h","時",Array.from({length:24},(_,i)=>pad(i)))}</div>
      <div class="sr-quick"><button class="lbtn sm" data-sq="today">今日</button><button class="lbtn sm" data-sq="month">今月</button>${dated?'<button class="lbtn sm" data-sq="clear">日付を外す</button>':""}</div>
      <div class="hint" style="margin:2px 2px 0">キーワードが空なら、その日の記録を一覧にします</div>` : ""}</div>`;
  const r=sq.results;
  if (!r) return html + `<div class="hint" style="margin:8px 4px">文字起こし・翻訳・議事録をまとめて検索します。Enter でも検索できます</div>`;
  if (!r.length) return html + `<div class="hint" style="margin:8px 4px">見つかりませんでした</div>`;
  html += `<div class="sr-count">${r.length}件${r.length>=SR_LIMIT?`（${SR_LIMIT}件で打ち切り。キーワードか日付で絞ってください）`:""}</div>`;
  const byFile=new Map(); r.forEach(x=>{ if (!byFile.has(x.s)) byFile.set(x.s, []); byFile.get(x.s).push(x); });
  for (const [s, hits] of byFile) {
    html += `<div class="sr-file" data-sid="${s.id}"><b>${s.daily?"🗒 ":""}${s.name}</b><span class="muted">${s.group}${s.daily?"":" "+s.sub.split(" ")[0]}</span>${hits[0].i>=0?`<span class="cnt">${hits.length}</span>`:""}</div>`;
    hits.filter(x=>x.i>=0).forEach(x=>{ const l = x.type==="summary" ? null : s.lines[x.i];
      html += `<div class="sr-hit" data-sid="${s.id}" data-i="${x.i}" data-ty="${x.type}">
        <div class="sr-meta">${x.type==="summary" ? '<span class="pill sum">議事録</span>' : `${l[0]} ${l[2]}`}${x.type==="translation"?'<span class="pill">翻訳</span>':""}<span class="adv-only muted">L${x.i+1}</span></div>
        <div class="sr-text">${srMark(x.text)}</div></div>`; });
  }
  return html;
}
function bindSearch() {
  const go = () => { st.sq.q=$("#srQ").value; srRun(); renderList(); };
  $("#srQ").onkeydown = e => { if (e.key==="Enter") go(); };
  $("#srGo").onclick = go;
  document.querySelectorAll("#list [data-st]").forEach(b=>b.onclick=()=>{ st.sq.type=b.dataset.st; st.sq.q=$("#srQ").value; srRun(); renderList(); });
  $("#srDtBtn").onclick = () => { st.sq.dateOpen=!st.sq.dateOpen; st.sq.q=$("#srQ").value; renderList(); };
  document.querySelectorAll("#list [data-sd]").forEach(c=>c.onchange=()=>{ st.sq[c.dataset.sd]=c.value; st.sq.q=$("#srQ").value; srRun(); renderList(); });
  document.querySelectorAll("#list [data-sq]").forEach(b=>b.onclick=()=>{ const k=b.dataset.sq;
    Object.assign(st.sq, k==="clear" ? { y:"", m:"", d:"", h:"" } : { y:"2026", m:"10", d:k==="today"?"31":"", h:"" });
    st.sq.q=$("#srQ").value; srRun(); renderList(); });
  // 結果を押すと: その記録を開いて行へ移動して光らせる。議事録の結果は議事録タブを開く
  document.querySelectorAll("#list .sr-file, #list .sr-hit").forEach(e=>e.onclick=()=>{
    st.cur=e.dataset.sid; st.sel.clear(); st.menu=null;
    const ty=e.dataset.ty, i=+e.dataset.i;
    if (ty==="summary") { st.right=true; st.rtab="sum"; }
    if (ty==="translation" && st.view==="T") st.view="TR";
    renderAll();
    if (e.classList.contains("sr-hit") && ty!=="summary") { const ln=document.querySelector(`#tx .ln[data-i="${i}"]`);
      if (ln) { ln.scrollIntoView({ block:"center" }); ln.classList.add("flash"); setTimeout(()=>ln.classList.remove("flash"), 2000); } }
  });
}
