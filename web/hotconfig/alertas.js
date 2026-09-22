// A visão Alertas: o histórico da sede inteira (quem dispensou o quê, quando),
// que só saía no CSV do relatório da frota; e a aba de alertas do detalhe.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, el } from "/common/ui.js";

export const KIND_LABEL = {
  "usb.storage": "usb_storage",
  "identity.duplicate": "identity_duplicate",
  "usb.phone": "usb_phone",
  "usb.network": "usb_network",
  "usb.other": "usb_other",
  "media.cd": "media_cd",
  "display.multiple": "display_multiple",
};
const EVENT_LABEL = { raised: "alert_ev_raised", dismissed: "alert_ev_dismissed" };

let historico = [];
let nomeDoTime = () => "";

export function usarNomes(fn) {
  nomeDoTime = fn;
}

function base() {
  return `/api/v1/site-images/${encodeURIComponent(api.imageId)}`;
}

function quando(epoch) {
  return epoch ? new Date(epoch * 1000).toLocaleString() : "";
}

function tabela(linhas, comMac) {
  const tb = el("table", { class: "altable" },
    el("thead", {}, el("tr", {},
      el("th", {}, t("alert_when")), comMac ? el("th", {}, t("machine")) : null,
      el("th", {}, t("alert_what")), el("th", {}, t("alert_detail")), el("th", {}, t("alert_state")))));
  const corpo = el("tbody");
  for (const a of linhas) {
    const estado = a.event === "dismissed"
      ? t("dismissed_by", { who: a.dismissed_by || "?", when: quando(a.dismissed_at) })
      : t("alert_still_open");
    corpo.append(el("tr", { class: a.event === "dismissed" ? "" : "aberto" },
      el("td", { class: "muted" }, quando(a.event === "dismissed" ? a.dismissed_at : a.at)),
      comMac ? el("td", { class: "mono" }, a.mac, a.binding_user ? ` · ${a.binding_user}` : "") : null,
      el("td", {}, t(KIND_LABEL[a.kind] || "usb_other")),
      el("td", { class: "muted" }, [a.vendor, a.detail].filter(Boolean).join(" · ")),
      el("td", {}, t(EVENT_LABEL[a.event] || "alert_ev_raised"), " ", el("span", { class: "muted" }, estado))));
  }
  tb.append(corpo);
  return tb;
}

export async function carregarHistorico() {
  const box = $("#al_hist");
  if (!box) return;
  try {
    historico = (await api.get(`${base()}/alerts/history?n=1000`)).history || [];
  } catch (e) {
    box.textContent = `${t("error")}: ${e.message}`;
    return;
  }
  box.innerHTML = "";
  if (!historico.length) {
    box.className = "muted";
    box.textContent = t("alerts_history_none");
    return;
  }
  box.className = "";
  box.append(tabela(historico, true));
}

function csvCampo(v) {
  const s = String(v ?? "");
  const aspa = String.fromCharCode(34);
  const precisa = s.includes(aspa) || s.includes(",") || s.includes("\n");
  return precisa ? aspa + s.split(aspa).join(aspa + aspa) + aspa : s;
}

function exportarCsv() {
  const iso = (e) => (e ? new Date(e * 1000).toISOString() : "");
  const linhas = ["mac,team,event,kind,detail,vendor,raised_at,dismissed_at,dismissed_by"];
  for (const a of historico) {
    linhas.push([a.mac, nomeDoTime(a.mac), a.event, a.kind, a.detail, a.vendor, iso(a.at), iso(a.dismissed_at), a.dismissed_by]
      .map(csvCampo).join(","));
  }
  const url = URL.createObjectURL(new Blob([linhas.join("\n") + "\n"], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${api.imageId}-alertas.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

// a aba Alertas do detalhe da máquina
export async function abaAlertas(m, painel, aoMudar) {
  painel.innerHTML = "";
  painel.append(el("p", { class: "muted" }, t("loading")));
  let linhas;
  try {
    linhas = (await api.get(`${base()}/machines/${m.mac}/alerts/history`)).history || [];
  } catch (e) {
    painel.textContent = `${t("error")}: ${e.message}`;
    return;
  }
  painel.innerHTML = "";
  const abertos = (m.alerts || []).length;
  if (abertos) {
    const todos = el("button", { class: "small", type: "button" }, t("dismiss_all_machine", { n: abertos }));
    todos.onclick = async () => {
      if (!confirm(t("dismiss_all_confirm", { n: abertos }))) return;
      await api.post(`${base()}/machines/${m.mac}/alerts/dismiss-all`, {});
      if (aoMudar) aoMudar();
    };
    painel.append(el("div", { class: "actions" }, todos));
  }
  if (!linhas.length) {
    painel.append(el("p", { class: "muted" }, t("alerts_history_none")));
    return;
  }
  painel.append(tabela(linhas.slice().reverse(), false));
}

export function iniciarAlertas() {
  $("#al_refresh").onclick = carregarHistorico;
  $("#al_csv").onclick = exportarCsv;
}
