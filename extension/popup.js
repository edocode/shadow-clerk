// ボタンを押した時点で撮る。撮影と送信は background が行い、ポップアップはすぐ閉じる
// （画面全体は daemon が撮るので、開いたままだとポップアップが写り込む）

for (const el of document.querySelectorAll("[data-msg]")) {
  el.textContent = chrome.i18n.getMessage(el.dataset.msg);
}

async function capture(source) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await chrome.runtime.sendMessage({
    type: "capture",
    source,
    windowId: tab?.windowId,
    title: source === "screen" ? chrome.i18n.getMessage("screen_title") : tab?.title || "",
    url: source === "screen" ? "" : tab?.url || "",
  });
  window.close();
}

document.getElementById("tab").addEventListener("click", () => capture("tab"));
document.getElementById("screen").addEventListener("click", () => capture("screen"));
document.getElementById("tab").focus();
