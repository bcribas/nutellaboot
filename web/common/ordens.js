// O rastreador de uma ordem: quem confirmou, quem caducou. Alimentado pelo
// SSE `command.acked` na hora e reconciliado pela rota de status enquanto
// houver máquina pendente. Usado pelo hotconfig e pelo laboratórios; o
// dashboard não manda ordem, e não importa isto.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el } from "/common/ui.js";

const RECONCILIA_MS = 15000;
const MAX_VISIVEIS = 3;

export function criarRastreador(caixa, opts = {}) {
  const ordens = []; // {image, id, command, estados: Map mac->{state,status}}
  let timer = null;

  function pinta() {
    caixa.innerHTML = "";
    caixa.classList.toggle("hidden", !ordens.length);
    for (const o of ordens) {
      const conta = { acked: 0, pending: 0, expired: 0 };
      for (const e of o.estados.values()) conta[e.state] = (conta[e.state] || 0) + 1;
      const linha = el("div", { class: "cmdrow" });
      const texto = el("span", {},
        el("b", {}, o.command), " ",
        t("cmd_progress", { ok: conta.acked, n: o.estados.size }),
        conta.expired ? ` · ${t("cmd_progress_expired", { n: conta.expired })}` : "",
        conta.pending ? ` · ${t("cmd_progress_waiting", { n: conta.pending })}` : "",
        opts.rotuloSede ? ` · ${opts.rotuloSede(o.image)}` : "");
      const detalhe = el("button", { class: "small", type: "button" }, t("cmd_progress_detail"));
      const lista = el("div", { class: "cmdlist hidden" });
      detalhe.onclick = () => {
        lista.classList.toggle("hidden");
        lista.innerHTML = "";
        for (const [mac, e] of [...o.estados].sort()) {
          lista.append(el("span", { class: `pill ${e.state === "acked" ? "ok" : e.state === "expired" ? "bad" : ""}` },
            `${(opts.nomeDoTime && opts.nomeDoTime(mac)) || mac}${e.status && e.status !== "done" ? " · " + e.status : ""}`), " ");
        }
      };
      const fechar = el("button", { class: "small", type: "button" }, "×");
      fechar.onclick = () => {
        ordens.splice(ordens.indexOf(o), 1);
        pinta();
      };
      linha.append(texto, " ", detalhe, " ", fechar, lista);
      caixa.append(linha);
    }
  }

  async function reconciliar() {
    let pendente = false;
    for (const o of ordens) {
      if (![...o.estados.values()].some((e) => e.state === "pending")) continue;
      try {
        const d = await api.get(`/api/v1/site-images/${encodeURIComponent(o.image)}/commands/${o.id}`, opts.api || {});
        for (const alvo of d.targets || []) o.estados.set(alvo.mac, { state: alvo.state, status: alvo.status });
      } catch {
        // rota de antes desta versão, ou comando podado: o SSE ainda alimenta
      }
      if ([...o.estados.values()].some((e) => e.state === "pending")) pendente = true;
    }
    pinta();
    clearTimeout(timer);
    if (pendente) timer = setTimeout(reconciliar, RECONCILIA_MS);
  }

  // uma ordem nova: `macs` são os alvos; sem eles a lista vem da reconciliação
  const acompanhar = (image, id, command, macs = []) => {
    const estados = new Map();
    for (const mac of macs) estados.set(mac, { state: "pending" });
    ordens.unshift({ image, id, command, estados });
    ordens.splice(MAX_VISIVEIS);
    pinta();
    clearTimeout(timer);
    timer = setTimeout(reconciliar, macs.length ? RECONCILIA_MS : 500);
  };
  // do SSE command.acked: {mac, id|command_id, status}
  const ack = (dados) => {
    const cid = dados.command_id || dados.id;
    const o = ordens.find((x) => x.id === cid);
    if (!o) return;
    o.estados.set(dados.mac, { state: "acked", status: dados.status });
    pinta();
  };
  const limpar = () => {
    ordens.length = 0;
    clearTimeout(timer);
    pinta();
  };
  return { acompanhar, ack, limpar };
}
