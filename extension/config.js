// エンドポイントの解決。background と options で同じ既定値を使うため切り出してある。
// match pattern はポートを書けないので manifest 側はホストのみを許可しており、
// ポートを変えても host_permissions を直す必要はない。

export const DEFAULT_ORIGIN = "http://127.0.0.1:8765";
const KEY = "origin";

export async function getOrigin() {
  const v = await chrome.storage.local.get(KEY);
  return (v[KEY] || DEFAULT_ORIGIN).replace(/\/+$/, "");
}

export async function setOrigin(origin) {
  await chrome.storage.local.set({ [KEY]: origin.replace(/\/+$/, "") });
}

// 127.0.0.1 / localhost 以外はサーバー側が拒否するので、保存前に弾いて理由を返す
export function validateOrigin(input) {
  let u;
  try {
    u = new URL(input);
  } catch {
    return { ok: false, message: "URL の形式が正しくありません（例: http://127.0.0.1:8765）" };
  }
  if (u.protocol !== "http:") {
    return { ok: false, message: "http:// で指定してください" };
  }
  if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") {
    return { ok: false, message: "保存 API は localhost からのみ受け付けます" };
  }
  if (u.pathname !== "/" || u.search || u.hash) {
    return { ok: false, message: "ホストとポートだけを指定してください" };
  }
  return { ok: true, origin: u.origin };
}
