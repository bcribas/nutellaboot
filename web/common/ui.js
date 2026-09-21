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

export function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4500);
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

// Valor que só aparece UMA vez (uma chave recém-criada): mostra com botão de
// copiar. `rotulos` = {copy, copied}.
export function copiavel(valor, rotulos) {
  const code = el("code", {}, valor);
  const btn = el("button", { class: "small", type: "button" }, rotulos.copy);
  btn.onclick = async () => {
    await navigator.clipboard.writeText(valor);
    btn.textContent = rotulos.copied;
    setTimeout(() => (btn.textContent = rotulos.copy), 1500);
  };
  return el("span", { class: "copiavel" }, code, " ", btn);
}
