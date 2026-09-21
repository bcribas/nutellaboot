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
