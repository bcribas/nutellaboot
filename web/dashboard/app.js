// Dashboard de transmissão: o sistema em funcionamento, para telão.
//
// Nenhum comando sai desta tela — só leitura, segura para deixar aberta numa
// entrevista. A série temporal é acumulada AQUI, enquanto a tela fica aberta:
// o servidor não guarda histórico para isto (o resumo é um instantâneo
// cacheado por 3 s), então o gráfico recomeça no F5 — troca justa por zero
// I/O de série no servidor que atende o boot.
import * as api from "/common/api.js";
import { init, t, apply } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);

const RITMO_MS = 30000; // decisão de produto: telão ligado o dia inteiro
const JANELA = 240; // pontos guardados = ~2 h a 30 s

let sites = [];
// cada ponto: {t, online, mem, cpu}
const serie = [];
let ultimaBusca = 0;

// os limiares da casa (os mesmos do agente e do hotconfig: 70 atenção, 85 ruim)
function nivel(pct) {
  if (pct == null) return "";
  if (pct > 85) return "bad";
  if (pct > 70) return "warn";
  return "";
}

// --- gráfico de linhas em SVG, sem biblioteca --------------------------------
//
// Primeiro código de visualização do projeto. À mão porque as telas são
// autocontidas (nada de CDN), e um polyline resolve: eixo do tempo implícito,
// escala vertical por série, últimas N amostras.
function grafico(pontos, series, maxY) {
  const W = 600;
  const H = 150;
  const PAD = 4;
  if (pontos.length < 2) {
    return `<svg viewBox="0 0 ${W} ${H}"><text x="${W / 2}" y="${H / 2}" fill="#97a2b6"
      font-size="13" text-anchor="middle">${t("dash_collecting")}</text></svg>`;
  }
  const x = (i) => PAD + (i * (W - 2 * PAD)) / Math.max(1, pontos.length - 1);
  const y = (v) => H - PAD - (Math.min(v, maxY) * (H - 2 * PAD)) / maxY;
  let corpo = "";
  // linhas de referência a 25/50/75%
  for (const frac of [0.25, 0.5, 0.75]) {
    const yy = H - PAD - frac * (H - 2 * PAD);
    corpo += `<line x1="${PAD}" y1="${yy}" x2="${W - PAD}" y2="${yy}"
      stroke="#2a3140" stroke-width="1"/>`;
  }
  for (const s of series) {
    const pts = pontos
      .map((p, i) => (p[s.campo] == null ? null : `${x(i).toFixed(1)},${y(p[s.campo]).toFixed(1)}`))
      .filter(Boolean)
      .join(" ");
    corpo += `<polyline points="${pts}" fill="none" stroke="${s.cor}"
      stroke-width="2.5" stroke-linejoin="round"/>`;
  }
  // o valor atual, grande, no canto — no MESMO svg (um overlay posicionado
  // por CSS quebrava em qualquer mudança de layout)
  const ult = pontos[pontos.length - 1];
  const rotulos = series
    .filter((s) => ult[s.campo] != null)
    .map((s) => `<b style="color:${s.cor}">${ult[s.campo]}${s.suf || ""}</b>`)
    .join(" ");
  return `<span class="gagora">${rotulos}</span>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${corpo}</svg>`;
}

function medidor(rotulo, pct, texto) {
  const cls = nivel(pct);
  return `<div class="medidor"><span class="rot">${rotulo}</span>
    <span class="trilho"><i class="${cls}" style="width:${Math.min(pct || 0, 100)}%"></i></span>
    <span class="val">${texto}</span></div>`;
}

function render() {
  const totais = sites.reduce(
    (a, s) => ({
      m: a.m + s.machines,
      on: a.on + s.online,
      al: a.al + s.alerts,
      at: a.at + (s.online > 0 ? 1 : 0),
    }),
    { m: 0, on: 0, al: 0, at: 0 }
  );
  $("#n-online").textContent = totais.on;
  $("#n-total").textContent = totais.m;
  $("#n-sites").textContent = totais.at;
  $("#n-alerts").textContent = totais.al;
  $("#n-alerts").parentElement.classList.toggle("zero", totais.al === 0);

  // gráficos
  $("#g-online").innerHTML = grafico(
    serie,
    [{ campo: "online", cor: "var(--serie1)" }],
    Math.max(10, totais.m)
  );
  $("#g-res").innerHTML = grafico(
    serie,
    [
      { campo: "mem", cor: "var(--serie1)", suf: "%" },
      { campo: "cpu", cor: "var(--serie2)", suf: "%" },
    ],
    100
  );

  // mapa de calor: pior métrica manda na cor; sede sem máquina ligada esmaece
  const mapa = $("#mapa");
  mapa.innerHTML = "";
  const ordenadas = [...sites].sort((a, b) => a.id.localeCompare(b.id));
  for (const s of ordenadas) {
    const r = s.res || {};
    const pior = Math.max(r.mem_max ?? 0, r.cpu_max ?? 0);
    const el = document.createElement("div");
    el.className =
      "sede" +
      (s.online === 0 ? " off" : pior > 85 || s.alerts > 0 ? " bad" : pior > 70 ? " warn" : "");
    el.innerHTML = `
      <span class="sid">${s.id}</span>
      <span class="son"><b>${s.online}</b>/${s.machines}</span>
      ${s.alerts > 0 ? `<span class="badge">${s.alerts}</span>` : ""}
      ${medidor("RAM", r.mem_avg, r.mem_avg != null ? `${r.mem_avg}%` : "—")}
      ${medidor("CPU", r.cpu_avg, r.cpu_avg != null ? `${r.cpu_avg}%` : "—")}
      ${medidor("swap", r.swap_on > 0 ? 100 : 0, r.swap_mb > 0 ? `${r.swap_mb}M` : "0")}`;
    mapa.appendChild(el);
  }
  $("#dvazio").hidden = sites.length > 0;
  $("#dvazio").textContent = t("dash_empty");
}

function mediaFrota(campo) {
  const vals = sites.map((s) => s.res?.[campo]).filter((v) => v != null);
  return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
}

async function buscar() {
  try {
    const d = await api.get("/api/v1/labs?dias=1", { kind: "admin" });
    sites = d.sites || [];
  } catch (e) {
    $("#updated").textContent = `${t("error")}: ${e.message}`;
    return;
  }
  ultimaBusca = Date.now();
  serie.push({
    t: ultimaBusca,
    online: sites.reduce((a, s) => a + s.online, 0),
    mem: mediaFrota("mem_avg"),
    cpu: mediaFrota("cpu_avg"),
  });
  if (serie.length > JANELA) serie.shift();
  render();
}

function relogio() {
  $("#clock").textContent = new Date().toLocaleTimeString();
  if (ultimaBusca) {
    const s = Math.round((Date.now() - ultimaBusca) / 1000);
    $("#updated").textContent = t("dash_updated", { s });
  }
}

async function main() {
  await init(null);
  apply(document);
  await buscar();
  setInterval(buscar, RITMO_MS);
  setInterval(relogio, 1000);
  relogio();
}

main();
