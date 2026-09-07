// 拡張アイコンのクリックで、表示中のタブをキャプチャして shadow-clerk に送る。
// 保存とファイル名の決定はサーバー側が行う(会議名は .clerk_session を見ないと分からないため)。

const ENDPOINT = "http://127.0.0.1:8765/api/screenshot";

chrome.action.onClicked.addListener(async (tab) => {
  try {
    // captureVisibleTab は activeTab 権限 + ユーザージェスチャーで動く。
    // アイコンのクリック自体がジェスチャーなので、事前のホスト権限は要らない。
    const image = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });

    const res = await fetch(ENDPOINT, {
      method: "POST",
      // application/json にすると preflight が飛ぶ。サーバーは Content-Type を見ずに
      // ボディを JSON として読むので、simple request になる text/plain で送る。
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify({ image, title: tab.title || "", url: tab.url || "" }),
    });

    if (!res.ok) {
      flash("!", "#c62828", `HTTP ${res.status}`);
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
      flash("－", "#f9a825", `${json.file}(会議の記録中ではないため transcript には残していません)`);
    }
  } catch (e) {
    // daemon が起きていない場合もここに来る
    flash("!", "#c62828", String(e));
  }
});

function flash(text, color, detail) {
  if (detail) console.log("[shadow-clerk]", detail);
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
}
