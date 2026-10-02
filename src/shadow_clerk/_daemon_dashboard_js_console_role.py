"""Shadow-clerk daemon: ダッシュボード JavaScript（AI Console の役割タブ）

コンソールは assistant と talk の2つ。表示は1画面を切り替えて使い、表示中でない役割の
SSE は描かずに状態だけ覚える。切り替えたら grid を取り直す（full snapshot がクライアントの
行を作り直すので、状態の掃除は loadConsole に任せる）。
"""

_JS_TEMPLATE_CONSOLE_ROLE = """\
/* --- AI Console の役割（assistant / talk） --- */
let _consoleRole='assistant';
const _consoleRoleRunning={assistant:false,talk:false};
const _CONSOLE_ROLE_TABS={assistant:'tabConsole',talk:'tabConsoleTalk'};
function consoleUrl(path){return path+'?role='+_consoleRole;}
function consoleBody(o){return JSON.stringify(Object.assign({role:_consoleRole},o||{}));}
function onConsoleEvent(d){
  const role=d.role||'assistant';
  if(d.auto&&role==='assistant')showAutoAnalysis();
  if(d.running!==undefined){_consoleRoleRunning[role]=!!d.running;updateConsoleRoleTabs();}
  if(role===_consoleRole)applyConsole(d);
}
function selectConsoleRole(role){
  if(role!==_consoleRole){
    _consoleRole=role;_consoleRunning=null;_consoleLoaded=false;_lastCols=0;
  }
  switchLogTab('console');
  updateConsoleRoleTabs();
}
function updateConsoleRoleTabs(){
  Object.keys(_CONSOLE_ROLE_TABS).forEach(r=>{
    const b=document.getElementById(_CONSOLE_ROLE_TABS[r]);if(!b)return;
    b.classList.toggle('active',logTab==='console'&&_consoleRole===r);
    b.dataset.bg=(r!==_consoleRole&&_consoleRoleRunning[r])?'1':'';
  });
}
function syncConsoleRoles(s){
  _consoleRoleRunning.assistant=!!s.console_running;
  _consoleRoleRunning.talk=!!s.talk_console_running;
  updateConsoleRoleTabs();updateAnalysisBtn();
  updateConsoleStatus(_consoleRoleRunning[_consoleRole]);
}
/* 分析ボタンは表示中の役割に関係なく assistant の状態を出す */
function updateAnalysisBtn(){
  const t=document.getElementById('btnStartAnalysis');if(!t)return;
  const on=!!_consoleRoleRunning.assistant;
  t.textContent=on?(I18N['dash.stop_analysis']||'Stop analysis'):(I18N['dash.start_analysis']||'Start analysis');
  t.title=on?(I18N['dash.stop_analysis_title']||''):(I18N['dash.start_analysis_title']||'');
}
"""
