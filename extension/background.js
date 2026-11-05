// ポップアップのボタンで、表示中のタブ、または画面全体を shadow-clerk に保存する。
// 保存とファイル名の決定はサーバー側が行う(会議名は .clerk_session を見ないと分からないため)。
// 画面全体はブラウザからは撮れない（chrome.desktopCapture は毎回選択画面を出す）ので、daemon に撮らせる。

import { getOrigin } from "./config.js";

// ポップアップが閉じて画面から消えるのを待つ時間。画面全体に写り込ませない
const POPUP_CLOSE_WAIT_MS = 300;

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "capture") return;
  // ポップアップは返事を受けたら閉じる。撮影はそのあとここで続ける
  sendResponse({ started: true });
  capture(msg);
});

async function capture({ source, windowId, title, url }) {
  try {
    let body;
    if (source === "screen") {
      await new Promise((resolve) => setTimeout(resolve, POPUP_CLOSE_WAIT_MS));
      body = { source: "screen", title };
    } else {
      // captureVisibleTab は activeTab 権限で動く。ポップアップを開いたこと自体が
      // 拡張の呼び出しなので、事前のホスト権限は要らない。
      const image = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
      body = { image, title, url };
    }
    const endpoint = `${await getOrigin()}/api/screenshot`;

    const res = await fetch(endpoint, {
      method: "POST",
      // application/json にすると preflight が飛ぶ。サーバーは Content-Type を見ずに
      // ボディを JSON として読むので、simple request になる text/plain で送る。
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      flash("!", "#c62828", `HTTP ${res.status} (${endpoint})`);
      return;
    }
    const json = await res.json();
    if (json.status !== "ok") {
      flash("!", "#c62828", json.message);
      return;
    }
    // 会議中でなければ transcript には残らない。それが分かるよう色を分ける。
    if (json.transcript_appended) {
      flash("OK", "#2e7d32", json.file);
    } else {
      flash("－", "#f9a825", `${json.file}(記録中ではないため transcript には残していません)`);
    }
  } catch (e) {
    // daemon が起きていない、ポート設定が違う場合もここに来る
    flash("!", "#c62828", String(e));
  }
}

function flash(text, color, detail) {
  if (detail) console.log("[shadow-clerk]", detail);
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
}
