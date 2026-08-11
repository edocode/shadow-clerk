"""Shadow-clerk daemon: ダッシュボード JavaScript (device selection)"""

_JS_TEMPLATE_DEVICES = """\
async function loadAudioDevices(cfg){
  let d;
  try{d=await(await fetch('/api/audio-devices')).json();}catch(e){return;}
  const pinned=d.cli_pinned||{};
  fillDeviceSelect('cfg_mic_device',d.mic||[],cfg.mic_device,pinned.mic);
  fillDeviceSelect('cfg_monitor_device',d.monitor||[],cfg.monitor_device,pinned.monitor);
}
function fillDeviceSelect(id,items,current,cliPinned){
  const sel=document.getElementById(id);if(!sel)return;
  if(cliPinned){
    // CLI の --mic/--monitor 番号指定が config より優先するため、UI から変えても効かない
    sel.innerHTML='';
    const o=document.createElement('option');o.textContent=I18N['cfg.device_cli_pinned'];sel.appendChild(o);
    sel.disabled=true;
    return;
  }
  sel.disabled=false;sel.innerHTML='';
  const auto=document.createElement('option');auto.value='';auto.textContent=I18N['cfg.device_auto'];sel.appendChild(auto);
  let matched=false;
  for(const it of items){
    const o=document.createElement('option');o.value=it.name;o.textContent=it.label;o.title=it.name;
    if(it.name===current){o.selected=true;matched=true;}
    sel.appendChild(o);
  }
  // 設定済みだが一覧に無い（抜かれている）場合も選択肢として残す
  if(current&&!matched){
    const o=document.createElement('option');o.value=current;o.textContent=current;o.selected=true;sel.appendChild(o);
  }
}
async function refreshAudioDevices(){
  // 実際の再列挙 (refresh_device_list) はキャプチャスレッドでしか安全に呼べないため、
  // サーバー側はフラグを立てるだけ。次の監視ティック（2秒間隔）で消費されるまで、
  // updated_at の変化をポーリングして「再列挙が終わった」ことを確認する。
  const btn=document.getElementById('cfgDeviceRefreshBtn');
  const micSel=document.getElementById('cfg_mic_device');
  const monSel=document.getElementById('cfg_monitor_device');
  // 保存前でも今表示中の選択（自動決定した値ではなく UI 上の選択）を維持する
  const cur={
    mic_device: (micSel&&!micSel.disabled)?(micSel.value||null):cfgData.mic_device,
    monitor_device: (monSel&&!monSel.disabled)?(monSel.value||null):cfgData.monitor_device,
  };
  if(btn)btn.disabled=true;
  try{
    let before=null;
    try{before=(await(await fetch('/api/audio-devices')).json()).updated_at;}catch(e){/* noop */}
    await fetch('/api/audio-devices/refresh',{method:'POST'});
    for(let i=0;i<8;i++){
      await new Promise(r=>setTimeout(r,1000));
      try{
        const d=await(await fetch('/api/audio-devices')).json();
        if(d.updated_at!==before)break;
      }catch(e){/* noop */}
    }
    await loadAudioDevices(cur);
  }finally{
    if(btn)btn.disabled=false;
  }
}
"""
