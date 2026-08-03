// Cliente da API do NutellaBoot 3.
//
// Duas formas de credencial, e nenhuma delas fica guardada aqui:
//
//   * telas de imagem (configureitor, hotconfig) — recebem
//     ?id=<imagem>&tk=<token> na URL, lido a cada chamada. É o link que se
//     entrega a uma sede, e ele não muda (invariante do projeto).
//
//   * console (/admin/) — SESSÃO. A chave de administração, ou o código de
//     convite, é trocada uma vez por um cookie HttpOnly em
//     POST /api/v1/session; daí em diante o navegador manda o cookie sozinho.
//
// NÃO volte a guardar a credencial em sessionStorage/localStorage. Além de
// deixá-la ao alcance de qualquer script da página, foi essa ida e volta que
// produziu o bug de deslogar a cada reload: a tela regravava o campo de login
// (vazio no carregamento) por cima da chave boa. Há teste guardando isto.

const params = new URLSearchParams(location.search);
export const imageId = params.get("id") || "";

function imageToken() {
  return params.get("tk") || "";
}

// O cookie de sessão só é aceito pelo servidor junto deste cabeçalho. Um
// <form> de outro site não consegue defini-lo, e um fetch cross-site com
// cabeçalho custom esbarra no preflight — é o que impede CSRF agora que
// existe cookie.
const CONSOLE_HEADER = { "X-NB-Console": "1" };

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

export async function request(method, path, { body, kind = "image", raw, contentType, token } = {}) {
  const headers = { ...CONSOLE_HEADER };
  // no console a credencial é o cookie; nas telas de sede, o token da URL.
  // `token` é para quem tem o token em mãos mas não na URL — a tela de
  // auto-atendimento, logo depois de criar a imagem.
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  } else if (kind !== "admin" && imageToken()) {
    headers.Authorization = `Bearer ${imageToken()}`;
  }
  const opts = { method, headers, credentials: "same-origin" };
  if (raw) {
    opts.body = raw;
    if (contentType) opts.headers["Content-Type"] = contentType;
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

// --- sessão do console ---

export async function login(key) {
  return post("/api/v1/session", { key }, { kind: "admin" });
}

export async function logout(todos = false) {
  return del(`/api/v1/session${todos ? "?all=true" : ""}`, { kind: "admin" });
}

export function wallpaperUrl(image, versao) {
  // Mesmo caso do eventsUrl: <img> não manda cabeçalho, então a credencial vai
  // na URL (token de sede) ou vem do cookie (console). O `v=` é só para o
  // navegador não reaproveitar a imagem antiga depois de trocar.
  const tk = imageToken();
  const q = new URLSearchParams();
  if (versao) q.set("v", versao);
  if (tk) q.set("tk", tk);
  const s = q.toString();
  return `/api/v1/site-images/${encodeURIComponent(image)}/wallpaper${s ? `?${s}` : ""}`;
}

// --- pendrive de boot ---
//
// São três downloads, e nenhum deles pode mandar cabeçalho: `<a download>` não
// tem como. Vale o token na URL (as telas de sede já o têm) ou o cookie de
// sessão, do mesmo jeito que a prévia do wallpaper e o SSE.

function _tk(token) {
  return token || imageToken();
}

export function usbConfUrl(image, token) {
  const tk = _tk(token);
  const q = tk ? `?tk=${encodeURIComponent(tk)}` : "";
  return `/api/v1/site-images/${encodeURIComponent(image)}/usb/conf${q}`;
}

export function usbImageUrl(image, token) {
  const tk = _tk(token);
  const q = tk ? `?tk=${encodeURIComponent(tk)}` : "";
  return `/api/v1/site-images/${encodeURIComponent(image)}/usb/image${q}`;
}

export function usbGenericUrl(image, token) {
  // a genérica não é de imagem nenhuma, mas ainda pede credencial: são 400 MB
  // saindo da máquina que responde à API durante a prova
  const tk = _tk(token);
  const q = new URLSearchParams();
  if (image && tk) {
    q.set("id", image);
    q.set("tk", tk);
  }
  const s = q.toString();
  return `/api/v1/usb/generic/image${s ? `?${s}` : ""}`;
}

export function eventsUrl(image) {
  // Com token de sede na URL, ele vai junto (o EventSource não manda
  // cabeçalho). No console não vai credencial nenhuma: o cookie de sessão
  // acompanha por ser mesma origem.
  const tk = imageToken();
  const q = tk ? `?tk=${encodeURIComponent(tk)}` : "";
  return `/api/v1/site-images/${encodeURIComponent(image)}/events${q}`;
}
