// Cliente da API do NutellaBoot 3.
//
// Credenciais: as telas de imagem (configureitor, hotconfig) recebem
// ?id=<imagem>&tk=<token> na URL; a tela de administração guarda a chave de
// admin no sessionStorage (não vai para a URL, não fica no histórico).

const params = new URLSearchParams(location.search);
export const imageId = params.get("id") || "";

function imageToken() {
  return params.get("tk") || "";
}

export function adminKey() {
  return sessionStorage.getItem("nb3-admin-key") || "";
}

export function setAdminKey(k) {
  sessionStorage.setItem("nb3-admin-key", k);
}

export function clearAdminKey() {
  sessionStorage.removeItem("nb3-admin-key");
}

function authHeader(kind) {
  const key = kind === "admin" ? adminKey() : imageToken();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function parse(resp) {
  if (resp.status === 204) return null;
  const text = await resp.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, body && body.detail ? body.detail : String(body));
  }
  return body;
}

export async function request(method, path, { body, kind = "image", raw } = {}) {
  const opts = { method, headers: { ...authHeader(kind) } };
  if (raw) {
    opts.body = raw;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  return parse(await fetch(path, opts));
}

export const get = (p, o) => request("GET", p, o);
export const post = (p, body, o) => request("POST", p, { body, ...o });
export const put = (p, body, o) => request("PUT", p, { body, ...o });
export const patch = (p, body, o) => request("PATCH", p, { body, ...o });
export const del = (p, o) => request("DELETE", p, o);

export function eventsUrl(image) {
  const tk = imageToken() || adminKey();
  return `/api/v1/site-images/${encodeURIComponent(image)}/events?tk=${encodeURIComponent(tk)}`;
}
