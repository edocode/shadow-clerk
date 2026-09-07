import { DEFAULT_ORIGIN, getOrigin, setOrigin, validateOrigin } from "./config.js";

const $origin = document.getElementById("origin");
const $status = document.getElementById("status");

function say(message, kind = "") {
  $status.textContent = message;
  $status.className = kind;
}

$origin.value = await getOrigin();
$origin.placeholder = DEFAULT_ORIGIN;

document.getElementById("save").addEventListener("click", async () => {
  const v = validateOrigin($origin.value.trim());
  if (!v.ok) {
    say(v.message, "err");
    return;
  }
  await setOrigin(v.origin);
  $origin.value = v.origin;
  say(`保存しました: ${v.origin}`, "ok");
});

document.getElementById("reset").addEventListener("click", async () => {
  await setOrigin(DEFAULT_ORIGIN);
  $origin.value = DEFAULT_ORIGIN;
  say(`既定に戻しました: ${DEFAULT_ORIGIN}`, "ok");
});

// 保存前でも確かめられるよう、入力欄の値をそのまま試す。
// /api/status は daemon が生きていれば必ず返るので、これで到達性が分かる。
document.getElementById("test").addEventListener("click", async () => {
  const v = validateOrigin($origin.value.trim());
  if (!v.ok) {
    say(v.message, "err");
    return;
  }
  say("接続中…");
  try {
    const res = await fetch(`${v.origin}/api/status`, { cache: "no-store" });
    if (!res.ok) {
      say(`つながりましたが HTTP ${res.status} が返りました`, "err");
      return;
    }
    const s = await res.json();
    const target = s.session || s.output_path || "(記録なし)";
    say(`OK — 記録中: ${target}`, "ok");
  } catch (e) {
    say(`つながりません。daemon が起動しているか確認してください（${e}）`, "err");
  }
});
