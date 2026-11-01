// 左ペイン: 日付 / 会議（会議名ごと）/ 検索 と、会議の設定・紐付け
Object.assign(st, { ltab:"date", group:null, sort:"new" });
const named = () => sessions.filter(s=>!s.daily && !s.name.startsWith("名前なし"));
const itemHtml = s => {
  const live = st.meeting && st.meeting.id===s.id || (s.daily && !st.meeting);
  return `<div class="item ${s.id===st.cur?"act":""}" data-id="${s.id}">
    <div class="t">${s.daily?"🗒 ":""}${st.ltab==="mtg"?s.group+" "+s.sub.split(" ")[0]:s.name}${live?'<span class="pill live">● 記録中</span>':""}</div>
    <div class="s">${st.ltab==="mtg"?s.sub.split("·")[1]||"":s.sub}${s.summary?'<span class="pill sum">議事録あり</span>':""}${s.ai?'<span class="pill ai">AI アドバイスあり</span>':""}</div></div>`;
};
function renderList() {
  document.querySelectorAll("#ltabs button").forEach(b=>b.classList.toggle("act", b.dataset.lt===st.ltab));
  let html="";
  if (st.ltab==="search") html = searchHtml();
  else if (st.ltab==="date") { let g=null;
    for (const s of sessions) { if (s.group!==g) { g=s.group; html+=`<div class="grp">${g}</div>`; } html+=itemHtml(s); } }
  else if (!st.group) {
    const groups={}; named().forEach(s=>(groups[s.name] ||= []).push(s));
    let names=Object.keys(groups); if (st.sort==="abc") names.sort((a,b)=>a.localeCompare(b,"ja"));
    html = `<div class="sortbar"><span>会議名ごと</span><button class="lbtn sm" id="sortBtn">${st.sort==="abc"?"あいうえお順":"新しい順"} ⇅</button></div>`
      + names.map(n=>`<div class="item" data-g="${n}"><div class="t">${n}<span class="cnt">${groups[n].length}回</span></div>
        <div class="s">最新: ${groups[n][0].group} ${groups[n][0].sub.split(" ")[0]}</div>
        <button class="gear" data-cfg="${n}" title="この会議の設定">⚙</button></div>`).join("");
  } else {
    html = `<div class="ghead"><button class="lbtn sm" id="gBack">← 一覧へ</button><b>${st.group}</b><button class="lbtn sm" data-cfg="${st.group}" title="会議の設定">⚙ 設定</button></div>`
      + named().filter(s=>s.name===st.group).map(itemHtml).join("");
  }
  $("#list").innerHTML = html;
  if (st.ltab==="search") bindSearch();
  document.querySelectorAll("#list .item[data-id]").forEach(e=>e.onclick=()=>{ st.cur=e.dataset.id; st.sel.clear(); st.menu=null; renderAll(); });
  document.querySelectorAll("#list .item[data-g]").forEach(e=>e.onclick=()=>{ st.group=e.dataset.g; renderList(); });
  document.querySelectorAll("#list [data-cfg]").forEach(b=>b.onclick=ev=>{ ev.stopPropagation(); openMc(b.dataset.cfg); });
  const sb=$("#sortBtn"); if (sb) sb.onclick=()=>{ st.sort = st.sort==="abc"?"new":"abc"; renderList(); };
  const gb=$("#gBack"); if (gb) gb.onclick=()=>{ st.group=null; renderList(); };
  $("#linkBtn").style.display = cur().daily ? "none" : "";
}
document.querySelectorAll("#ltabs button").forEach(b=>b.onclick=()=>{ st.ltab=b.dataset.lt; st.group=null; renderList(); });

let mcName=null;
function openMc(n) {
  mcName=n;
  const cnt=sessions.filter(s=>s.name===n).length;
  $("#mcName").value=n; $("#mcNameHint").textContent=`変えると、この会議名の記録 ${cnt}件すべての名前が変わります`;
  $("#mcModal").classList.add("show");
}
$("#mcCancel").onclick=()=>$("#mcModal").classList.remove("show");
$("#mcOk").onclick=()=>{
  const nn=$("#mcName").value.trim()||mcName;
  sessions.forEach(s=>{ if (s.name===mcName) s.name=nn; });
  if (st.group===mcName) st.group=nn;
  $("#mcModal").classList.remove("show"); renderAll(); toast(`会議名を「${nn}」に変えました`);
};

$("#linkBtn").onclick=()=>{
  const s=cur();
  $("#lkSummary").textContent=`${s.group} ${s.sub.split(" ")[0]} の記録（いまの会議名: ${s.name}）`;
  $("#lkSel").innerHTML=[...new Set(named().map(x=>x.name))].map(n=>`<option ${n===s.name?"selected":""}>${n}</option>`).join("");
  $("#lkName").value=""; pickRadio("#lkModal [data-lk]", $("#lkModal [data-lk=existing]"));
  $("#lkModal").classList.add("show");
};
document.querySelectorAll("#lkModal [data-lk]").forEach(r=>r.onclick=()=>pickRadio("#lkModal [data-lk]", r));
$("#lkName").onfocus=()=>pickRadio("#lkModal [data-lk]", $("#lkModal [data-lk=new]"));
$("#lkCancel").onclick=()=>$("#lkModal").classList.remove("show");
$("#lkOk").onclick=()=>{ const s=cur(), mode=document.querySelector("#lkModal [data-lk].act").dataset.lk;
  s.name = mode==="existing" ? $("#lkSel").value : ($("#lkName").value.trim() || "名前なしの会議");
  $("#lkModal").classList.remove("show"); renderAll(); toast(`会議名を「${s.name}」にしました`); };

// 表示メニュー: ボタンの位置から開き、画面からはみ出さないように寄せる
$("#viewBtn").onclick = e => { e.stopPropagation(); $("#menu").classList.remove("open");
  const m=$("#viewMenu"), open=m.classList.toggle("open"); if (!open) return;
  const r=$("#viewBtn").getBoundingClientRect(), w=m.offsetWidth;
  m.style.top=`${r.bottom+6}px`; m.style.left=`${Math.max(8, Math.min(r.left, innerWidth-w-8))}px`; };

renderAll();
