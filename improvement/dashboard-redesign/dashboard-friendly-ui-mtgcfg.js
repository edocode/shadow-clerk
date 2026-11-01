// 会議ごとの設定: 会議をチェックで選び、選んだ会議にまとめて値を設定する（ルールは作らない）
// /api/meeting-settings に合わせる: 変えられるのは SET_KEYS の 6 項目だけ。既定（defaults）の編集・「既定に戻す」は API にない
const AUTO_ANALYZE = true;  // config.yaml の auto_analyze（設定画面「会議開始時に分析」）
// analyze は 3 状態: "default"（全体の設定に従う・yaml に書かない）/ true / false
const CFG_DEFAULTS = { analyze:"default", workdir:"", publish:true, publish_to:"artifact", notion_url:"", publish_advice:false };
// meeting.yaml の meetings[]（上から照合、最初に一致したものだけが効く）。手で書いた広いパターンも残りうる
let RULES = [
  { pattern:"^週次定例$", workdir:"~/work/product", publish_to:"notion", notion_url:"https://www.notion.so/acme/weekly", publish_advice:true },
  { pattern:"acme", publish:false, workdir:"~/work/acme" },
  { pattern:"^1on1$", analyze:false },
  { pattern:"^みんなで振り返り$", analyze:true },
];
const EXTRA_NAMES = ["acme 社 打ち合わせ", "acme 契約レビュー"];
const FIELDS = [
  ["AI アシスタント", [
    ["analyze", "会議を見守って分析する", [["default",`既定（全体の設定: ${AUTO_ANALYZE?"オン":"オフ"}）`],[true,"オン"],[false,"オフ"]], "会議を始めたときに AI アシスタントを起動するか。既定なら設定画面の「会議開始時に分析」に従います"],
    ["workdir", "作業フォルダ", "text", "AI アシスタントや Claude と会議をこのフォルダで起動します。空なら設定画面の作業フォルダを使います"],
  ]],
  ["公開", [
    ["publish", "議事録を外部サービスに公開してよい", "bool", "オフにすると、議事録や Advice を手元の外に出しません"],
    ["publish_to", "公開先", [["artifact","Artifact（非公開で作成し、リンクを渡す）"],["notion","Notion のページの下に作る"]]],
    ["notion_url", "Notion のページ", "text", "公開先が Notion のときだけ使います"],
    ["publish_advice", "会議中の Advice も公開して参加者と見る", "bool"],
  ]],
];
const FLAT = FIELDS.flatMap(g=>g[1]);
const fmtVal = (k,v) => { const f=FLAT.find(x=>x[0]===k); if (!f) return v;
  if (f[2]==="bool") return v?"する":"しない"; if (Array.isArray(f[2])) return (f[2].find(o=>o[0]==v)||[,v])[1].split("（")[0]; return v||"（なし）"; };
const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
const literalName = p => { const b=p.replace(/^\^/,"").replace(/\$$/,""); return /[.^$*+?{}[\]|()]/.test(b.replace(/\\./g,"")) ? "" : b.replace(/\\(.)/g,"$1"); };
const firstMatch = n => { const i=RULES.findIndex(r=>new RegExp(r.pattern,"i").test(n)); return [i, RULES[i]]; };
// GET /api/meeting-settings と同じ形: 解決済みの値 + matched + shared
function resolve(n) { const [,r]=firstMatch(n), v={ ...CFG_DEFAULTS };
  if (r) for (const k in CFG_DEFAULTS) if (k in r) v[k]=r[k];
  return { ...v, matched: r ? r.pattern : "(defaults)", shared: !!r && literalName(r.pattern)!==n }; }
// POST /api/meeting-settings と同じ: 自分だけのルールなら更新、広いルールならその値を写した ^名前$ を直前に足す
function applyTo(n, set) { const [i,r]=firstMatch(n);
  const put = o => { Object.assign(o, set); if (o.analyze==="default") delete o.analyze; };  // 既定 = キーを書かない
  if (r && literalName(r.pattern)===n) { put(r); return; }
  const nr = { pattern:`^${reEsc(n)}$`, ...(r ? Object.fromEntries(Object.entries(r).filter(([k])=>k in CFG_DEFAULTS)) : {}) };
  put(nr); RULES.splice(r ? i : RULES.length, 0, nr); }
const meetingNames = () => [...new Set(sessions.filter(s=>!s.daily && !s.name.startsWith("名前なし")).map(s=>s.name).concat(EXTRA_NAMES))];
// 一覧のチップ: 解決済みの値のうち、目を引くものだけ（API は「既定から変えたキー」を返さない）
const chips = n => { const v=resolve(n), c=[];
  if (v.analyze===false) c.push("分析しない"); else if (v.analyze===true) c.push("分析する"); if (!v.publish) c.push("公開しない"); else if (v.publish_to==="notion") c.push("公開先: Notion");
  if (v.publish_advice) c.push("Advice も公開"); if (v.workdir) c.push(`📁 ${v.workdir}`); return c; };
const ruleNote = n => { const v=resolve(n);
  return v.matched==="(defaults)" ? '<span class="muted">既定の設定を使用</span>'
    : v.shared ? `<span class="muted">共通の設定 <code>${v.matched}</code> を使用</span>` : ""; };
const lastOf = n => { const s=sessions.find(x=>x.name===n); return s ? `${s.group} ${s.sub.split(" ")[0]}` : "記録なし"; };

const cs = { sel:new Set(), q:"", onlyCustom:false, pend:{} };
document.body.insertAdjacentHTML("beforeend", `<div class="modal-bg" id="cfgModal"><div class="modal cfgm">
  <div class="cfg-h"><h3>会議ごとの設定</h3><span class="spacer"></span><button class="lbtn sm adv-only" id="cfgYamlBtn">YAML を見る</button><button class="lbtn sm" id="cfgClose">✕</button></div>
  <div class="cfg-b"><div class="cfg-list" id="cfgList"></div><div class="cfg-ed" id="cfgEd"></div></div>
  <div class="cfg-f"><span class="hint adv-only" style="margin:0">既定の値・報告の量・確認の間隔・前回の会議を読む数・調べものの当て先は ~/.local/share/shadow-clerk/meeting.yaml を直接編集します</span><span class="spacer"></span><button class="cta ghost" id="cfgCancel">キャンセル</button><button class="cta" id="cfgSave">保存</button></div>
</div></div>`);

const visible = () => meetingNames().filter(n=>n.toLowerCase().includes(cs.q.toLowerCase()) && (!cs.onlyCustom || resolve(n).matched!=="(defaults)"));
function renderCfgList() {
  const vis=visible(), allOn = vis.length && vis.every(n=>cs.sel.has(n));
  $("#cfgList").innerHTML = `<input id="cfgQ" class="cfg-q" placeholder="🔍 会議名で絞り込む" value="${cs.q}">
    <div class="cfg-tools"><label><input type="checkbox" id="cfgAll2" ${allOn?"checked":""}> 表示中をすべて選ぶ</label><label><input type="checkbox" id="cfgOnly" ${cs.onlyCustom?"checked":""}> 個別の設定がある会議だけ</label></div>`
    + vis.map(n=>{ const c=chips(n);
      return `<label class="cfg-li mrow ${cs.sel.has(n)?"act":""}"><input type="checkbox" data-pick="${n}" ${cs.sel.has(n)?"checked":""}>
        <div><b>${n}</b> <span class="muted" style="font-size:11px">${lastOf(n)}</span>
        <div class="s">${c.map(x=>`<span class="chip">${x}</span>`).join("")} ${ruleNote(n)}</div></div></label>`; }).join("")
    + (vis.length ? "" : `<div class="hint" style="margin:10px 4px">当てはまる会議がありません</div>`);
  const q=$("#cfgQ"); q.oninput=()=>{ cs.q=q.value; renderCfgList(); const n=$("#cfgQ"); n.focus(); n.setSelectionRange(n.value.length,n.value.length); };
  $("#cfgAll2").onchange=e=>{ vis.forEach(n=>e.target.checked?cs.sel.add(n):cs.sel.delete(n)); renderCfg(); };
  $("#cfgOnly").onchange=e=>{ cs.onlyCustom=e.target.checked; renderCfgList(); };
  document.querySelectorAll("#cfgList [data-pick]").forEach(c=>c.onchange=()=>{ c.checked?cs.sel.add(c.dataset.pick):cs.sel.delete(c.dataset.pick); renderCfg(); });
}

// 選んだ会議での値: 保存前の変更（pend）があればそれ、なければ解決済みの値。違えば mixed
function valueFor(k, names) {
  if (k in cs.pend) return { v:cs.pend[k], same:true, changed:true };
  const eff = names.map(n=>resolve(n)[k]);
  return { v:eff[0], same: eff.every(v=>v===eff[0]), changed:false };
}
function fieldHtml(k, label, type, hint, names) {
  const r = valueFor(k, names), mixed = !r.same, v = r.v;
  let ctl;
  if (type==="bool") ctl = `<select data-k="${k}">${mixed?'<option selected disabled>（会議によって違う）</option>':""}<option value="1" ${!mixed&&v?"selected":""}>する</option><option value="0" ${!mixed&&!v?"selected":""}>しない</option></select>`;
  else if (Array.isArray(type)) ctl = `<select data-k="${k}">${mixed?'<option selected disabled>（会議によって違う）</option>':""}${type.map(([o,l])=>`<option value="${o}" ${!mixed&&o==v?"selected":""}>${l}</option>`).join("")}</select>`;
  else ctl = `<input data-k="${k}" value="${mixed?"":v||""}" placeholder="${mixed?"（会議によって違う・空欄なら変えない）":k==="workdir"?"例: ~/work/product":""}">`;
  const state = r.changed ? `<span class="st cu">保存すると ${names.length}件に設定</span>` : "";
  return `<div class="cfg-row"><div class="cfg-lab">${label}${hint?`<div class="hint">${hint}</div>`:""}</div><div class="cfg-ctl">${ctl}<div class="st-line">${state}</div></div></div>`;
}
function renderCfgEd() {
  const names = [...cs.sel];
  if (!names.length) { $("#cfgEd").innerHTML = `<h4>会議を選んでください</h4><div class="hint" style="margin-top:0">左で会議にチェックを入れると、その会議の設定を変えられます。複数選ぶと、選んだ会議にまとめて同じ値を設定します。</div>`; return; }
  const shared = names.filter(n=>resolve(n).shared);
  let html = `<h4>${names.length===1?names[0]:`${names.length}件の会議`}</h4><div class="hint" style="margin-top:0">${names.length>1?`${names.join("、")} にまとめて設定します。`:""}変えた項目だけを書き込み、ほかの項目はそのままです。</div>`
    + (shared.length ? `<div class="hint">⚠ ${shared.join("、")} はほかの会議と共通の設定を使っています。変えると、その会議だけの設定を作って変えます（ほかの会議は変わりません）。</div>` : "");
  for (const [g, fields] of FIELDS) html += `<div class="cfg-g">${g}</div>` + fields.map(([k,l,t,h])=>fieldHtml(k,l,t,h,names)).join("");
  $("#cfgEd").innerHTML = html;
  $("#cfgEd").querySelectorAll("[data-k]").forEach(c=>c.onchange=()=>{ const k=c.dataset.k, f=FLAT.find(x=>x[0]===k);
    cs.pend[k] = f[2]==="bool" ? c.value==="1" : k==="analyze" ? (c.value==="default" ? "default" : c.value==="true") : c.value; renderCfgEd(); });
}
function renderCfg() { cs.pend={}; renderCfgList(); renderCfgEd(); }

// 保存形式は現行どおり meetings[].pattern
function toYaml() {
  const val = v => v===""?'""':typeof v==="string"&&/[:#]/.test(v)?`"${v}"`:v;
  return `meetings:\n` + RULES.map(r=>`  - pattern: "${r.pattern.replace(/\\/g,"\\\\")}"\n${Object.entries(r).filter(([k])=>k!=="pattern").map(([k,v])=>`    ${k}: ${val(v)}`).join("\n")}`).join("\n");
}
let cfgBackup;
function openCfg(meetingName) {
  cfgBackup = structuredClone(RULES);
  cs.sel = new Set(meetingName ? [meetingName] : []); cs.q=""; cs.onlyCustom=false;
  renderCfg(); $("#cfgModal").classList.add("show");
}
const closeCfg = restore => { if (restore) RULES=cfgBackup; $("#cfgModal").classList.remove("show"); renderList(); };
$("#cfgClose").onclick = () => closeCfg(true);
$("#cfgCancel").onclick = () => closeCfg(true);
$("#cfgSave").onclick = () => { const n=cs.sel.size, keys=Object.keys(cs.pend);
  if (n && keys.length) cs.sel.forEach(m=>applyTo(m, cs.pend));
  closeCfg(false); toast(n && keys.length ? `${n}件の会議に設定しました` : "変更はありません"); };
$("#cfgYamlBtn").onclick = () => { const b=structuredClone(RULES);
  if (Object.keys(cs.pend).length) cs.sel.forEach(m=>applyTo(m, cs.pend));
  const y=toYaml(); RULES=b;
  $("#cfgEd").innerHTML = `<h4>meeting.yaml の meetings（保存される内容）</h4><pre class="yaml">${y}</pre><button class="lbtn" onclick="renderCfgEd()">← 編集に戻る</button>`; };

// 入口: 会議タブの見出し / 各会議の ⚙ / その他メニュー / 会議開始の画面
const _renderList = renderList;
renderList = function () {
  _renderList();
  const sb=$("#sortBtn"); if (sb && !$("#cfgAll")) sb.parentElement.insertAdjacentHTML("afterend", `<button class="lbtn sm" id="cfgAll" style="width:100%;margin:0 0 8px">⚙ 会議ごとの設定（分析・公開・作業フォルダ）</button>`);
  const ca=$("#cfgAll"); if (ca) ca.onclick=()=>openCfg();
  document.querySelectorAll("#list [data-cfg]").forEach(b=>b.onclick=ev=>{ ev.stopPropagation(); openCfg(b.dataset.cfg); });
  document.querySelectorAll("#list .item[data-g] .wd").forEach(e=>e.remove());
  document.querySelectorAll("#list .item[data-g]").forEach(e=>{ const c=chips(e.dataset.g); if (c.length) e.insertAdjacentHTML("beforeend", `<div class="wd">⚙ ${c.join(" · ")}</div>`); });
  const gh=document.querySelector(".ghead"); if (gh && !$("#renBtn")) gh.querySelector("b").insertAdjacentHTML("afterend", `<button class="lbtn sm" id="renBtn" title="会議名を変える">✏</button>`);
  const rb=$("#renBtn"); if (rb) rb.onclick=()=>openMc(st.group);
};
document.querySelector("#menu hr").insertAdjacentHTML("beforebegin", `<div class="mi" id="miCfg">🗂<span>会議ごとの設定<small>分析・公開・作業フォルダを会議ごとに</small></span></div>`);
$("#miCfg").onclick = () => openCfg();
$("#mName").parentElement.querySelector(".hint").insertAdjacentHTML("afterend", `<div class="hint" id="mCfgLine" style="margin-top:6px"></div>`);
const updStartCfg = () => { const n=$("#mName").value.trim(), c=chips(n), a=resolve(n).analyze;
  // 会議ごとの analyze がオン / オフならそれ、既定なら auto_analyze
  $("#mAssist").checked = a==="default" ? AUTO_ANALYZE : a;
  $("#mAssist").closest("label").nextElementSibling.textContent = a===false ? "この会議は会議ごとの設定で「分析しない」です。チェックすると今回だけ起動します"
    : a==="default" && !AUTO_ANALYZE ? "設定で「会議開始時に分析」がオフです。チェックすると今回だけ起動します"
    : "決まったこと・宿題・確認が必要な点を「AI のアドバイス」に書き出します";
  $("#mCfgLine").innerHTML = `⚙ この会議の設定: ${c.length ? c.join("、") : "既定のまま"} <a href="#" id="mCfgChg">変更</a>`;
  $("#mCfgChg").onclick = e => { e.preventDefault(); openCfg(n); }; };
$("#mName").addEventListener("input", updStartCfg);
$("#meetingBtn").addEventListener("click", updStartCfg);
renderList();
