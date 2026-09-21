// A visão Sala: as máquinas comparadas entre si no período, pelo lote de
// samples (um pedido por sede, NDJSON). Ranking pelo pico, ou miniaturas na
// mesma escala.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, el, esc } from "/common/ui.js";
import { miniGrafico } from "./grafico.js";

const PERIODOS = [1800, 7200, 18000, 86400];
// campo -> {rótulo, teto do eixo, sufixo}
const METRICAS = {
  mem: { rot: "metric_mem", max: 100, suf: "%" },
  sw: { rot: "metric_swap", max: null, suf: " MB" },
  ld: { rot: "metric_load", max: null, suf: "" },
  psi_mem: { rot: "metric_psi_mem", max: 100, suf: "%" },
  psi_cpu: { rot: "metric_psi_cpu", max: 100, suf: "%" },
  psi_io: { rot: "metric_psi_io", max: 100, suf: "%" },
  hd: { rot: "metric_home", max: 100, suf: "%" },
};
let desde = 7200;
let nomeDoTime = () => "";
let abrirDetalhe = () => {};

export function usarNomes(fn, abrir) {
  nomeDoTime = fn;
  abrirDetalhe = abrir;
}

function estatistica(pontos, campo) {
  const vals = pontos.map((p) => p[campo]).filter((v) => v != null);
  if (!vals.length) return null;
  return {
    pico: Math.max(...vals),
    media: vals.reduce((a, b) => a + b, 0) / vals.length,
    ultimo: vals[vals.length - 1],
    oom: pontos.reduce((acc, p, i) => {
      const ant = i ? pontos[i - 1].oom : null;
      return acc + (p.oom != null && ant != null && p.oom > ant ? p.oom - ant : 0);
    }, 0),
  };
}

function fmt(v, suf) {
  return v == null ? "—" : `${Number.isInteger(v) ? v : v.toFixed(1)}${suf}`;
}

export async function carregarSala() {
  const box = $("#sala_out");
  if (!box) return;
  const campo = $("#sala_metrica").value || "mem";
  const modo = $("#sala_modo").value;
  box.className = "muted";
  box.textContent = t("loading");
  const since = Math.floor(Date.now() / 1000) - desde;
  let linhas;
  try {
    // limit=120 por máquina: uma sala de 60 fica perto de 1 MB
    linhas = await api.ndjson(
      `/api/v1/site-images/${encodeURIComponent(api.imageId)}/samples?since=${since}&limit=120&active_since=${since}`);
  } catch (e) {
    box.textContent = `${t("error")}: ${e.message}`;
    return;
  }
  const m = METRICAS[campo];
  const itens = linhas
    .map((l) => ({ ...l, st: estatistica(l.points || [], campo) }))
    .filter((l) => l.st);
  if (!itens.length) {
    box.textContent = t("room_none");
    return;
  }
  itens.sort((a, b) => b.st.pico - a.st.pico);
  const teto = m.max || Math.max(1, ...itens.map((i) => i.st.pico));
  const reamostradas = itens.filter((i) => i.resampled).length;
  const intervalo = itens[0].interval_s;
  $("#sala_info").textContent = reamostradas
    ? t("room_resampled", { n: reamostradas, s: intervalo })
    : `${itens.length} · ~${intervalo || "?"} s`;
  box.className = "";
  box.innerHTML = "";

  if (modo === "grid") {
    const grid = el("div", { class: "salagrid" });
    for (const i of itens) {
      const card = el("div", { class: "salacard" });
      card.innerHTML = `<div class="salanome">${esc(nomeDoTime(i.mac) || i.mac)} <span class="muted">${fmt(i.st.pico, m.suf)}</span></div>${miniGrafico(i.points, campo, teto)}`;
      card.onclick = () => abrirDetalhe(i.mac);
      grid.append(card);
    }
    box.append(grid);
    return;
  }

  const TOPO = 15;
  const tabela = el("table", { class: "rostable" },
    el("thead", {}, el("tr", {}, el("th", {}, t("team")), el("th", {}, t("machine")),
      el("th", {}, t("room_peak")), el("th", {}, t("room_avg")), el("th", {}, t("room_last")),
      el("th", {}, t("room_oom")), el("th", {}))));
  const corpo = el("tbody");
  const pinta = (lista) => {
    for (const i of lista) {
      const tr = el("tr", { class: "clicavel" },
        el("td", {}, nomeDoTime(i.mac) || el("span", { class: "muted" }, t("no_team"))),
        el("td", { class: "mono" }, i.mac),
        el("td", {}, el("b", {}, fmt(i.st.pico, m.suf))),
        el("td", { class: "muted" }, fmt(i.st.media, m.suf)),
        el("td", { class: "muted" }, fmt(i.st.ultimo, m.suf)),
        el("td", {}, i.st.oom ? el("span", { class: "pill bad" }, String(i.st.oom)) : ""),
        el("td"));
      tr.lastChild.innerHTML = miniGrafico(i.points, campo, teto, { W: 120, H: 28 });
      tr.onclick = () => abrirDetalhe(i.mac);
      corpo.append(tr);
    }
  };
  pinta(itens.slice(0, TOPO));
  tabela.append(corpo);
  box.append(tabela);
  if (itens.length > TOPO) {
    const mais = el("button", { class: "small", type: "button" }, t("room_show_all", { n: itens.length }));
    mais.onclick = () => {
      pinta(itens.slice(TOPO));
      mais.remove();
    };
    box.append(mais);
  }
}

export function iniciarSala() {
  const per = $("#sala_periodo");
  for (const s of PERIODOS) {
    const b = el("button", { type: "button", class: s === desde ? "on" : "" },
      s < 3600 ? `${s / 60} min` : `${s / 3600} h`);
    b.onclick = () => {
      desde = s;
      per.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      carregarSala();
    };
    per.append(b);
  }
  const sel = $("#sala_metrica");
  for (const [campo, m] of Object.entries(METRICAS)) sel.append(el("option", { value: campo }, t(m.rot)));
  sel.onchange = carregarSala;
  $("#sala_modo").onchange = carregarSala;
  $("#sala_refresh").onclick = carregarSala;
}
