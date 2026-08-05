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

let sites = [];
// a série vem do SERVIDOR (/labs/series, um ponto por minuto): sobrevive ao
// F5 e recorta por período — "só a competição importa"
let serieFrota = [];
let ultimaBusca = 0;
// desde quando olhar: predefinição (segundos para trás) ou horário absoluto
// (epoch). Vive na URL — recarregar ou compartilhar o link preserva o recorte.
let desdeRel = 7200;
let desdeAbs = 0;
// modo compartilhado: com ?tk= na URL a tela é só-leitura de verdade — a
// chave não tem machines:read (o zoom não busca máquinas) nem abre hotconfig
const compartilhado = Boolean(new URLSearchParams(location.search).get("tk"));

function desdeEpoch() {
  return desdeAbs || Math.floor(Date.now() / 1000) - desdeRel;
}
let zoomAberto = null; // id da sede com o zoom aberto
let zoomTimer = null;
let vista = "geral";
let inventario = null;
const INV_MS = 60000; // o inventário varre a frota inteira: ritmo mais folgado

// --- regiões -----------------------------------------------------------------
//
// O agrupamento do mapa: a UF sai do prefixo do fullname ("AC, Rio Branco -
// IFAC") ou, na falta, do próprio id (26bracrb = 26 + br + ac + ...). Sede de
// fora do Brasil cai no grupo do país.
const REGIAO_UF = {
  AC: "norte", AP: "norte", AM: "norte", PA: "norte", RO: "norte", RR: "norte", TO: "norte",
  AL: "nordeste", BA: "nordeste", CE: "nordeste", MA: "nordeste", PB: "nordeste",
  PE: "nordeste", PI: "nordeste", RN: "nordeste", SE: "nordeste",
  DF: "centrooeste", GO: "centrooeste", MT: "centrooeste", MS: "centrooeste",
  ES: "sudeste", MG: "sudeste", RJ: "sudeste", SP: "sudeste",
  PR: "sul", RS: "sul", SC: "sul",
};
const REGIAO_ORDEM = ["norte", "nordeste", "centrooeste", "sudeste", "sul", "internacional", "outros"];

function regiaoDe(s) {
  const m = (s.fullname || "").match(/^([A-Z]{2}),/);
  if (m && REGIAO_UF[m[1]]) return REGIAO_UF[m[1]];
  const mid = (s.id || "").match(/^\d{2}([a-z]{2})([a-z]{2})/);
  if (mid) {
    if (mid[1] === "br") return REGIAO_UF[mid[2].toUpperCase()] || "outros";
    return "internacional";
  }
  return "outros";
}

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

const KIND_LABEL = {
  "usb.storage": "usb_storage",
  "usb.phone": "usb_phone",
  "usb.network": "usb_network",
  "usb.other": "usb_other",
  "media.cd": "media_cd",
};

function hora(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString() : "";
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
    serieFrota,
    [{ campo: "online", cor: "var(--serie1)" }],
    Math.max(10, totais.m)
  );
  $("#g-res").innerHTML = grafico(
    serieFrota,
    [
      { campo: "mem", cor: "var(--serie1)", suf: "%" },
      { campo: "cpu", cor: "var(--serie2)", suf: "%" },
    ],
    100
  );

  // mapa de calor por REGIÃO: pior métrica manda na cor; sede sem máquina
  // ligada esmaece; clicar dá zoom
  const mapa = $("#mapa");
  mapa.innerHTML = "";
  const grupos = new Map();
  for (const s of sites) {
    const g = regiaoDe(s);
    if (!grupos.has(g)) grupos.set(g, []);
    grupos.get(g).push(s);
  }
  for (const g of REGIAO_ORDEM) {
    const lista = grupos.get(g);
    if (!lista || !lista.length) continue;
    lista.sort((a, b) => a.id.localeCompare(b.id));
    const tot = lista.reduce(
      (a, s) => ({ on: a.on + s.online, m: a.m + s.machines, al: a.al + s.alerts }),
      { on: 0, m: 0, al: 0 }
    );
    const h = document.createElement("div");
    h.className = "regiao";
    // chave montada fora da chamada de tradução: o guarda de i18n procura
    // strings fixas ali dentro, e um prefixo parcial viraria uma chave
    // inexistente para ele
    const chaveRegiao = "dash_reg_" + g;
    h.innerHTML = `<span>${t(chaveRegiao)}</span>
      <span class="dsub">${lista.length} · <b>${tot.on}</b>/${tot.m}${
        tot.al ? ` · <b class="ral">${tot.al}</b>` : ""}</span>`;
    mapa.appendChild(h);
    const grade = document.createElement("div");
    grade.className = "mapa";
    for (const s of lista) {
      const r = s.res || {};
      const pior = Math.max(r.mem_max ?? 0, r.cpu_max ?? 0, r.disk_max ?? 0);
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
        ${medidor("swap", r.swap_on > 0 ? 100 : 0, r.swap_mb > 0 ? `${r.swap_mb}M` : "0")}
        ${r.disk_max != null ? medidor("disco", r.disk_max, `${r.disk_max}%`) : ""}`;
      el.onclick = () => abrirZoom(s.id);
      grade.appendChild(el);
    }
    mapa.appendChild(grade);
  }
  $("#dvazio").hidden = sites.length > 0;
  $("#dvazio").textContent = t("dash_empty");
  if (zoomAberto) renderZoomCabecalho();
}

function mediaFrota(campo) {
  const vals = sites.map((s) => s.res?.[campo]).filter((v) => v != null);
  return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
}

async function buscarSerie() {
  try {
    const d = await api.get(`/api/v1/labs/series?since=${desdeEpoch()}`);
    serieFrota = d.points || [];
  } catch (e) {
    return;
  }
  render();
}

async function buscar() {
  try {
    const d = await api.get("/api/v1/labs?dias=1");
    sites = d.sites || [];
  } catch (e) {
    $("#updated").textContent = `${t("error")}: ${e.message}`;
    return;
  }
  ultimaBusca = Date.now();
  render();
}

// --- as visões de inventário -------------------------------------------------

// A rosca: a ÚNICA pizza do sistema, porque é o único caso onde ela é a
// leitura certa — parte-de-um-todo com poucas fatias (≤5 faixas de RAM).
// Ranking e comparação ficam em barras, que são mais precisas para ordenar.
const CORES_ROSCA = ["var(--serie1)", "var(--serie2)", "var(--serie3)", "var(--ok)", "var(--warn)"];

function rosca(fatias, totalRotulo) {
  const total = fatias.reduce((a, [, n]) => a + n, 0);
  if (!total) return `<p class="dsub">${t("dash_inv_none")}</p>`;
  const R = 80;
  const r = 52;
  const C = 95;
  let ang = -Math.PI / 2;
  let paths = "";
  for (const [i, [, n]] of fatias.entries()) {
    const frac = n / total;
    const a2 = ang + frac * 2 * Math.PI;
    const grande = frac > 0.5 ? 1 : 0;
    const x1 = C + R * Math.cos(ang);
    const y1 = C + R * Math.sin(ang);
    const x2 = C + R * Math.cos(a2);
    const y2 = C + R * Math.sin(a2);
    const xi2 = C + r * Math.cos(a2);
    const yi2 = C + r * Math.sin(a2);
    const xi1 = C + r * Math.cos(ang);
    const yi1 = C + r * Math.sin(ang);
    paths += `<path d="M ${x1.toFixed(1)} ${y1.toFixed(1)}
      A ${R} ${R} 0 ${grande} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}
      L ${xi2.toFixed(1)} ${yi2.toFixed(1)}
      A ${r} ${r} 0 ${grande} 0 ${xi1.toFixed(1)} ${yi1.toFixed(1)} Z"
      fill="${CORES_ROSCA[i % CORES_ROSCA.length]}"/>`;
    ang = a2;
  }
  const svg = `<svg viewBox="0 0 190 190">${paths}
    <text x="${C}" y="${C - 2}" text-anchor="middle" class="rosca-centro">${total}</text>
    <text x="${C}" y="${C + 16}" text-anchor="middle" class="rosca-centro-sub">${totalRotulo}</text></svg>`;
  const leg = fatias
    .map(([nome, n], i) =>
      `<span><i class="quad" style="background:${CORES_ROSCA[i % CORES_ROSCA.length]}"></i>
       ${nome} — <b>${n}</b> (${Math.round((100 * n) / total)}%)</span>`)
    .join("");
  return `${svg}<div class="rosca-leg">${leg}</div>`;
}

function hbarra(rotulo, valor, maximo, texto) {
  const pct = maximo > 0 ? Math.round((100 * valor) / maximo) : 0;
  return `<div class="hbarra"><span class="hrot" title="${rotulo}">${rotulo}</span>
    <span class="htrilho"><i style="width:${pct}%"></i></span>
    <span class="hval">${texto ?? valor}</span></div>`;
}

function renderInventario() {
  if (!inventario) return;
  const inv = inventario;
  const maxCpu = Math.max(1, ...inv.processors.map(([, n]) => n));
  $("#inv-cpus").innerHTML = inv.processors
    .map(([nome, n]) => hbarra(nome, n, maxCpu))
    .join("") || `<p class="dsub">${t("dash_inv_none")}</p>`;
  $("#inv-ram").innerHTML = rosca(inv.ram, t("dash_hw_machines"));

  const hw = inv.sites_hw || [];
  const maxRamAvg = Math.max(1, ...hw.map((s) => s.ram_avg_mb));
  const linhaHw = (s, cls) =>
    `<div class="hbarra"><span class="hrot">${s.site}</span>
      <span class="htrilho"><i class="${cls}" style="width:${Math.round((100 * s.ram_avg_mb) / maxRamAvg)}%"></i></span>
      <span class="hval">${(s.ram_avg_mb / 1024).toFixed(1)}G${s.cores_avg ? ` · ${s.cores_avg}c` : ""}</span></div>`;
  $("#inv-melhores").innerHTML = hw.slice(0, 5).map((s) => linhaHw(s, "top")).join("")
    || `<p class="dsub">${t("dash_inv_none")}</p>`;
  $("#inv-piores").innerHTML = hw.slice(-5).reverse().map((s) => linhaHw(s, "bottom")).join("")
    || `<p class="dsub">${t("dash_inv_none")}</p>`;

  const maxEd = Math.max(1, ...inv.editors_now.map(([, n]) => n));
  $("#inv-ed-agora").innerHTML = inv.editors_now
    .map(([ed, n]) => hbarra(ed, n, maxEd))
    .join("") || `<p class="dsub">${t("dash_inv_none")}</p>`;
  const maxMin = Math.max(1, ...inv.editors_minutes.map(([, n]) => n));
  $("#inv-ed-min").innerHTML = inv.editors_minutes
    .map(([ed, n]) => hbarra(ed, n, maxMin, `${n} min`))
    .join("") || `<p class="dsub">${t("dash_inv_none")}</p>`;

  $("#inv-disklow").textContent = inv.disks_low > 0 ? inv.disks_low : "";
  $("#inv-discos").innerHTML = inv.disks.length
    ? inv.disks
        .map((d) => {
          const cls = d.pct >= 95 ? "bad" : d.pct >= 85 ? "warn" : "";
          return `<div class="disco-linha${d.online ? "" : " offline"}">
            <span class="dsede">${d.site}</span>
            <span class="dquem">${d.team || d.mac}</span>
            <span class="dpct ${cls}">${d.pct}%</span>
            <span class="dsub">${d.free_mb} MB ${t("dash_disk_free")}</span></div>`;
        })
        .join("")
    : `<p class="dsub">${t("dash_disk_none")}</p>`;
}

async function buscarInventario() {
  try {
    inventario = await api.get("/api/v1/labs/inventory");
  } catch (e) {
    return;
  }
  renderInventario();
}

function trocarVista(nova) {
  vista = nova;
  for (const b of document.querySelectorAll(".dabas button")) {
    b.classList.toggle("on", b.dataset.vista === nova);
  }
  $("#v-geral").hidden = nova !== "geral";
  $("#v-hw").hidden = nova !== "hw";
  $("#v-ed").hidden = nova !== "ed";
  $("#v-disco").hidden = nova !== "disco";
  if (nova !== "geral" && !inventario) buscarInventario();
}

// --- o zoom de uma sede ------------------------------------------------------

function estadoMaquina(m) {
  if (m.online) return "on";
  return m.seconds_since_contact != null && m.seconds_since_contact < 600 ? "stale" : "off";
}

function piorDe(m) {
  const res = m.status?.sysresources || {};
  const cores = m.status?.hwinfo?.cores;
  const mem = res.mem_pct ?? 0;
  const cpu =
    Array.isArray(res.loadavg) && cores ? Math.min(100, Math.round((100 * res.loadavg[0]) / cores)) : 0;
  const hd = m.status?.sysdisk?.home_pct ?? 0;
  return Math.max(mem, cpu, hd, (res.swap_used_mb || 0) > 0 ? 90 : 0);
}

let serieZoom = [];

async function buscarSerieZoom() {
  if (!zoomAberto) return;
  try {
    const d = await api.get(
      `/api/v1/labs/series?site=${encodeURIComponent(zoomAberto)}&since=${desdeEpoch()}`
    );
    serieZoom = d.points || [];
  } catch (e) {
    serieZoom = [];
  }
  renderZoomCabecalho();
}

function renderZoomCabecalho() {
  const s = sites.find((x) => x.id === zoomAberto);
  if (!s) return;
  $("#z-id").textContent = s.id;
  $("#z-name").textContent = s.fullname || "";
  $("#z-counts").textContent = `${s.online}/${s.machines} · ${s.alerts} ${t("dash_alerts")}`;
  $("#z-graf").innerHTML = grafico(
    serieZoom,
    [
      { campo: "mem", cor: "var(--serie1)", suf: "%" },
      { campo: "cpu", cor: "var(--serie2)", suf: "%" },
    ],
    100
  );
  const az = $("#z-alertas");
  az.innerHTML = "";
  for (const a of s.alert_list || []) {
    const linha = document.createElement("div");
    linha.className = "zalerta";
    linha.innerHTML = `<b>${t(KIND_LABEL[a.kind] || "usb_other")}</b>
      <span>${a.team ? `${a.team} · ` : ""}${a.mac || ""}</span>
      <span class="dsub">${a.vendor || a.detail || ""}</span>
      <span class="dsub">${hora(a.at)}</span>`;
    az.appendChild(linha);
  }
}

async function renderZoomMaquinas() {
  if (!zoomAberto) return;
  let dados;
  try {
    dados = await api.get(`/api/v1/site-images/${encodeURIComponent(zoomAberto)}/machines`, {
      kind: "admin",
    });
  } catch (e) {
    $("#z-maquinas").textContent = `${t("error")}: ${e.message}`;
    return;
  }
  const ms = dados.machines || [];
  // as piores em cima: é o "entender a situação" — quem está mal aparece antes
  ms.sort((a, b) => piorDe(b) - piorDe(a));
  const grade = $("#z-maquinas");
  grade.innerHTML = ms.length ? "" : `<p class="dsub">${t("dash_zoom_none")}</p>`;
  for (const m of ms) {
    const res = m.status?.sysresources || {};
    const cores = m.status?.hwinfo?.cores;
    const cpu =
      Array.isArray(res.loadavg) && cores
        ? Math.min(100, Math.round((100 * res.loadavg[0]) / cores))
        : null;
    const est = estadoMaquina(m);
    const el = document.createElement("div");
    el.className = `zmac ${est}` + ((m.alerts || []).length ? " alerta" : "");
    const nome = m.binding?.name || m.binding?.user_id || m.mac;
    el.innerHTML = `
      <div class="ztitulo">${m.lock?.locked ? "🔒 " : ""}${nome}</div>
      <div class="zmacaddr">${m.mac}${est !== "on" ? ` · ${t(est === "stale" ? "stale" : "offline")}` : ""}</div>
      ${medidor("RAM", res.mem_pct, res.mem_pct != null ? `${res.mem_pct}%` : "—")}
      ${medidor("CPU", cpu, cpu != null ? `${cpu}%` : "—")}
      ${medidor("swap", (res.swap_used_mb || 0) > 0 ? 100 : 0, res.swap_used_mb ? `${res.swap_used_mb}M` : "0")}
      ${m.status?.sysdisk?.home_pct != null
        ? medidor("disco", m.status.sysdisk.home_pct, `${m.status.sysdisk.home_pct}%`)
        : ""}`;
    grade.appendChild(el);
  }
}

function abrirZoom(id) {
  zoomAberto = id;
  serieZoom = [];
  $("#zoom").hidden = false;
  $("#z-maquinas").innerHTML = "";
  renderZoomCabecalho();
  buscarSerieZoom();
  if (compartilhado) {
    // a chave compartilhada não tem machines:read (e é assim de propósito):
    // o zoom mostra o gráfico e os alertas do resumo, e nada de hotconfig
    $("#z-hot").hidden = true;
    $("#z-maquinas").innerHTML = `<p class="dsharenote">${t("dash_shared_note")}</p>`;
    return;
  }
  $("#z-hot").hidden = false;
  $("#z-hot").href = `/hotconfig/?id=${encodeURIComponent(id)}`;
  renderZoomMaquinas();
  // mais fino que os 30 s da frota: para UMA sede a chamada é barata
  zoomTimer = setInterval(renderZoomMaquinas, 10000);
}

function fecharZoom() {
  zoomAberto = null;
  $("#zoom").hidden = true;
  clearInterval(zoomTimer);
}

function relogio() {
  $("#clock").textContent = new Date().toLocaleTimeString();
  if (ultimaBusca) {
    const s = Math.round((Date.now() - ultimaBusca) / 1000);
    $("#updated").textContent = t("dash_updated", { s });
  }
}

function aplicarDesdeNaUrl() {
  const u = new URL(location.href);
  if (desdeAbs) u.searchParams.set("since", String(desdeAbs));
  else u.searchParams.delete("since");
  history.replaceState(null, "", u);
}

function montarPeriodo() {
  const abs = new URLSearchParams(location.search).get("since");
  if (abs && Number(abs) > 0) {
    desdeAbs = Number(abs);
    const dt = new Date(desdeAbs * 1000);
    dt.setMinutes(dt.getMinutes() - dt.getTimezoneOffset());
    $("#desde-abs").value = dt.toISOString().slice(0, 16);
    for (const b of document.querySelectorAll(".dtempo button")) b.classList.remove("on");
  }
  for (const b of document.querySelectorAll(".dtempo button")) {
    b.onclick = () => {
      desdeRel = Number(b.dataset.desde);
      desdeAbs = 0;
      $("#desde-abs").value = "";
      for (const x of document.querySelectorAll(".dtempo button")) {
        x.classList.toggle("on", x === b);
      }
      aplicarDesdeNaUrl();
      buscarSerie();
      buscarSerieZoom();
    };
  }
  $("#desde-abs").onchange = () => {
    const v = $("#desde-abs").value;
    if (!v) return;
    desdeAbs = Math.floor(new Date(v).getTime() / 1000);
    for (const b of document.querySelectorAll(".dtempo button")) b.classList.remove("on");
    aplicarDesdeNaUrl();
    buscarSerie();
    buscarSerieZoom();
  };
}

async function main() {
  await init(null);
  apply(document);
  montarPeriodo();
  $("#z-close").onclick = fecharZoom;
  $("#zoom").onclick = (e) => {
    if (e.target === $("#zoom")) fecharZoom();
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") fecharZoom();
  });
  for (const b of document.querySelectorAll(".dabas button")) {
    b.onclick = () => trocarVista(b.dataset.vista);
  }
  await buscar();
  buscarSerie();
  buscarInventario();
  setInterval(buscar, RITMO_MS);
  setInterval(buscarSerie, RITMO_MS);
  setInterval(buscarInventario, INV_MS);
  setInterval(relogio, 1000);
  relogio();
}

main();
