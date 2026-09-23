// Utilidades de tela compartilhadas.

// Quase tudo que as telas mostram veio de fora: o nome de uma sede (escrito
// por um sub-admin), o pedido de imagem (escrito por um ANÔNIMO), o time do
// roster, o vendor de um alerta e o status da máquina (quem tem a chave de
// máquina escreve o que quiser). Estas telas rodam na sessão do admin, então
// nada disso entra num innerHTML sem passar por aqui.
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const $ = (s) => document.querySelector(s);

// Dentro do <dialog> modal aberto, se houver: o diálogo fica na camada de
// cima, e um aviso no <body> ficava ATRÁS dele e da cortina (o erro de um
// "Salvar" feito dentro do diálogo não aparecia). Quem fecha um diálogo e avisa
// fecha ANTES de chamar o toast, senão o aviso some junto com o diálogo.
export function toast(msg, isError = false) {
  const aviso = document.createElement("div");
  aviso.className = "toast" + (isError ? " err" : "");
  aviso.setAttribute("role", isError ? "alert" : "status");
  aviso.textContent = msg;
  const abertos = document.querySelectorAll("dialog[open]");
  (abertos.length ? abertos[abertos.length - 1] : document.body).appendChild(aviso);
  setTimeout(() => aviso.remove(), isError ? 7000 : 4500);
}

// Um elemento com filhos, sem innerHTML: `el("td", {class: "mono"}, texto)`.
// Texto de fora entra como nó de texto, que não vira marcação.
export function el(tag, attrs = {}, ...filhos) {
  const no = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") no.className = v;
    else if (k.startsWith("on")) no[k] = v;
    else no.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    no.append(f);
  }
  return no;
}

export function quando(epoch) {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString();
}

// Um valor com botão de copiar (uma chave recém-criada, um md5, um link).
// `rotulos` = {copy, copied} e, com `oculto`, também {show, hide}: o segredo
// que fica na tela (token, chave de boot) aparece mascarado até pedirem.
export function copiavel(valor, rotulos, { oculto = false } = {}) {
  const MASCARA = "••••••••••••";
  const code = el("code", {}, oculto ? MASCARA : valor);
  const btn = el("button", { class: "small", type: "button" }, rotulos.copy);
  btn.onclick = async () => {
    await navigator.clipboard.writeText(valor);
    btn.textContent = rotulos.copied;
    setTimeout(() => (btn.textContent = rotulos.copy), 1500);
  };
  const partes = [code, " ", btn];
  if (oculto) {
    const ver = el("button", { class: "small", type: "button" }, rotulos.show);
    ver.onclick = () => {
      const aberto = code.textContent === valor;
      code.textContent = aberto ? MASCARA : valor;
      ver.textContent = aberto ? rotulos.show : rotulos.hide;
    };
    partes.push(" ", ver);
  }
  return el("span", { class: "copiavel" }, ...partes);
}
