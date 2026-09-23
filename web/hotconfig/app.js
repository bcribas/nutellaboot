// Painel de gestão do laboratório: estado quase em tempo real (SSE) e ações
// em massa. O hotconfig do nb2 recarregava a lista inteira por polling manual
// (0/1/5/10 min) — aqui o servidor empurra as mudanças.
import * as api from "/common/api.js";
import { init, t, apply, currentLang } from "/common/i18n.js";
import { esc } from "/common/ui.js";
import { graficoTempo } from "./grafico.js";
import { criarRastreador } from "/common/ordens.js";
import { carregarRoster, renderTimes, informarMaquinas, nomeDoTime, abaTime, iniciarTimes } from "./times.js";
import * as alertas from "./alertas.js";
import * as sala from "./sala.js";

const $ = (s) => document.querySelector(s);
let machines = [];
let rejeitadas = [];
let selected = new Set();
// comando → campo que o trava no modelo. O render() reabilitava a barra inteira
// a cada seleção, desfazendo o que desabilitarComandosBloqueados() marcou: o
// botão voltava a prometer o que o servidor nega.
const bloqueados = new Map();
// o padrão é ver as LIGADAS: listar máquina desligada por padrão é ruído numa
// sala — quem quiser o cemitério marca "Todas". `stale` (piscou há pouco)
// conta como ligada: sumir com ela esconderia problema.
let filter = "on";
let source = null;
let refreshTimer = null;

const FILTERS = ["on", "all", "usb", "locked", "alert", "unbound", "offline"];
const FILTER_LABEL = {
  on: "filter_on",
  all: "filter_all",
  usb: "filter_usb",
  locked: "filter_locked",
  alert: "filter_alert",
  unbound: "filter_unbound",
  offline: "filter_offline",
};

// --- alertas de dispositivo -------------------------------------------------
//
// Som: nenhuma tela do projeto tocava áudio até aqui. O navegador só deixa
// tocar depois de um gesto do usuário, então a barra tem um botão para armar,
// e a escolha fica guardada. Um oscilador do WebAudio evita depender de
// arquivo externo (a política de conteúdo das páginas publicadas bloquearia).
let audioCtx = null;
let alertaSoando = false;

function somArmado() {
  return localStorage.getItem("nb3-lab-som") === "1";
}

function armarSom() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.resume();
    localStorage.setItem("nb3-lab-som", "1");
    apitar();
    atualizarBotaoSom();
  } catch {
    toast(t("sound_unavailable"), true);
  }
}

function apitar() {
  if (!audioCtx || !somArmado()) return;
  const agora = audioCtx.currentTime;
  for (const [i, freq] of [880, 660, 880].entries()) {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.frequency.value = freq;
    osc.type = "square";
    gain.gain.value = 0.09;
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(agora + i * 0.18);
    osc.stop(agora + i * 0.18 + 0.14);
  }
}

function atualizarBotaoSom() {
  const b = $("#soundbtn");
  if (!b) return;
  b.textContent = somArmado() ? t("sound_on") : t("sound_enable");
  b.classList.toggle("primary", !somArmado());
}

function renderAlerts() {
  const bar = $("#alertbar");
  if (!bar) return;
  const abertos = machines.flatMap((m) => usbAlerts(m).map((a) => ({ ...a, m })));
  bar.classList.toggle("hidden", abertos.length === 0);
  bar.innerHTML = "";
  if (!abertos.length) {
    alertaSoando = false;
    return;
  }

  // apita ao aparecer alerta novo, não a cada redesenho
  if (!alertaSoando) {
    apitar();
    alertaSoando = true;
  }

  for (const a of abertos.sort((x, y) => y.at - x.at)) {
    const linha = document.createElement("div");
    linha.className = "arow";
    const quando = new Date(a.at * 1000).toLocaleTimeString();
    const quem = teamLabel(a.m) ? `${teamLabel(a.m)} · ` : "";
    linha.innerHTML = `<span class="awhat">${t(KIND_LABEL[a.kind] || "usb_other")}</span>
      <span class="amac">${esc(quem)}${esc(a.mac)}</span>
      <span>${esc([a.vendor, a.detail].filter(Boolean).join(" · "))}</span>
      <span class="awhen">${quando}</span>`;
    const btn = document.createElement("button");
    btn.className = "small";
    btn.textContent = t("dismiss");
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api.post(
          `/api/v1/site-images/${api.imageId}/machines/${a.mac}/alerts/${a.id}/dismiss`,
          {}
        );
        loadAll();
      } catch (e) {
        btn.disabled = false;
        toast(`${t("error")}: ${e.message}`, true);
      }
    };
    const espaco = document.createElement("span");
    espaco.className = "spacer";
    linha.append(espaco, btn);
    bar.appendChild(linha);
  }
}

const KIND_LABEL = alertas.KIND_LABEL;

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function isAlert(m) {
  const alerts = m.status?.sysresources?.alerts;
  return Array.isArray(alerts) && alerts.length > 0;
}

// Alerta aberto de dispositivo: veio do servidor e fica até alguém dispensar,
// então sobrevive a reboot da máquina e a recarga da página.
function usbAlerts(m) {
  return Array.isArray(m.alerts) ? m.alerts : [];
}

function state(m) {
  if (!m.online) {
    return m.seconds_since_contact != null && m.seconds_since_contact < 600 ? "stale" : "offline";
  }
  return isAlert(m) ? "alert" : "online";
}

function teamLabel(m) {
  const b = m.binding;
  if (!b) return null;
  return b.name || nomeDoTime(b.user_id) || b.user_id || null;
}

// --- as visões da tela ---
let visao = "maquinas";

function mostrarVisao(nome) {
  visao = nome;
  for (const b of document.querySelectorAll("#views button")) b.classList.toggle("on", b.dataset.view === nome);
  for (const v of ["maquinas", "times", "sala", "alertas"]) {
    $(`#pane_${v}`).classList.toggle("hidden", v !== nome);
  }
  if (nome === "times") renderTimes();
  if (nome === "sala") sala.carregarSala();
  if (nome === "alertas") alertas.carregarHistorico();
  if (location.hash !== `#${nome}`) history.replaceState(null, "", `#${nome}`);
}

function matches(m) {
  const q = $("#search").value.trim().toLowerCase();
  if (q) {
    const hay = `${m.mac} ${teamLabel(m) || ""} ${m.binding?.seat || ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  if (filter === "locked") return m.lock?.locked;
  if (filter === "usb") return usbAlerts(m).length > 0;
  if (filter === "alert") return isAlert(m) || usbAlerts(m).length > 0;
  if (filter === "unbound") return !m.binding;
  if (filter === "offline") return !m.online;
  if (filter === "on") return state(m) !== "offline";
  return true;
}

function card(m) {
  const el = document.createElement("div");
  const st = state(m);
  el.className =
    `mcard ${st}` +
    (m.lock?.locked ? " locked" : "") +
    (usbAlerts(m).length ? " usb" : "") +
    (selected.has(m.mac) ? " sel" : "");
  el.dataset.mac = m.mac;

  const team = teamLabel(m);
  const res = m.status?.sysresources || {};
  const ops = m.status?.operations || {};
  const memPct = res.mem_pct ?? 0;
  const diskPct = m.status?.sysdisk?.home_pct ?? null;
  const diskFree = m.status?.sysdisk?.home_free_mb ?? null;
  const load = Array.isArray(res.loadavg) ? res.loadavg[0] : null;
  const seat = m.binding?.seat ? `#${m.binding.seat} · ` : "";

  el.innerHTML = `
    <div class="team${team ? "" : " none"}">${esc(seat)}${esc(team || t("no_team"))}</div>
    <div class="mac">${esc(m.mac)}</div>
    <div class="metrics">
      <span>${t("memory")} <b class="${memPct > 85 ? "hot" : ""}">${memPct}%</b></span>
      ${load != null ? `<span>${t("load")} <b class="${load > 4 ? "hot" : ""}">${load.toFixed(1)}</b></span>` : ""}
      <span>${t("firewall")} <b>${ops.firewall === true ? "ON" : ops.firewall === false ? "OFF" : "—"}</b></span>
    </div>
    <div class="bar"><i class="${memPct > 85 ? "bad" : memPct > 70 ? "warn" : ""}" style="width:${Math.min(memPct, 100)}%"></i></div>
    ${diskPct != null ? `<div class="metrics"><span>${t("disk_home")} <b class="${diskPct >= 85 ? "hot" : ""}">${diskPct}%</b>${
      diskFree != null ? ` · ${diskFree} MB` : ""}</span></div>
    <div class="bar"><i class="${diskPct >= 95 ? "bad" : diskPct >= 85 ? "warn" : ""}" style="width:${Math.min(diskPct, 100)}%"></i></div>` : ""}
    <div class="metrics"><span>${
      m.online ? t("online") : st === "stale" ? t("stale") : t("offline")
    }${m.seconds_since_contact != null ? ` · ${m.seconds_since_contact}s` : ""}</span></div>`;

  el.onclick = (ev) => {
    if (ev.detail === 2) return showDetail(m);
    selected.has(m.mac) ? selected.delete(m.mac) : selected.add(m.mac);
    render();
  };
  return el;
}

// Painel vazio não pode ser mudo quando alguém ESTÁ tentando reportar. Um
// agente com a identificação quebrada leva 400 em tudo — inclusive no status,
// então a máquina nunca chega a existir — e daqui isso parecia "ninguém ligou
// o computador ainda". Foram 30 horas assim.
function renderRejeitadas() {
  const box = $("#rejected");
  if (!rejeitadas.length || machines.length) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  const quais = esc(rejeitadas.map((r) => `"${r.id}"`).join(", "));
  box.innerHTML = `${t("rejected_machines", { n: rejeitadas.length })} ${quais}<br>${t(
    "rejected_machines_hint"
  )}`;
}

function render() {
  renderAlerts();
  const list = machines.filter(matches);
  const grid = $("#grid");
  grid.innerHTML = "";
  list.forEach((m) => grid.appendChild(card(m)));
  $("#empty").classList.toggle("hidden", machines.length > 0);
  renderRejeitadas();

  const online = machines.filter((m) => m.online).length;
  $("#counts").textContent = `${t("machines_online", { n: online })} · ${t("machines_total", {
    n: machines.length,
  })}`;
  $("#selcount").textContent = t("selected_n", { n: selected.size });
  $("#actionbar")
    .querySelectorAll("button")
    .forEach((b) => (b.disabled = selected.size === 0 || bloqueados.has(b.dataset.cmd)));
}

// --- gráfico com eixo do tempo -----------------------------------------------
//
// Diferente do gráfico do dashboard (que desenha por índice), aqui o X mapeia
// o TEMPO: um buraco de máquina desligada vira lacuna na linha (o traço quebra
// quando duas amostras distam mais de 5 min), não um segmento esticado — e os
// ticks de hora no eixo dizem de quando é cada trecho. SVG à mão, como tudo
// aqui: as telas são autocontidas, sem CDN.
const ACK_LABEL = { done: "ack_done", error: "ack_error", failed: "ack_failed", expired: "ack_expired" };

function showDetail(m, abrirNaAba) {
  const box = document.createElement("div");
  box.className = "detail";
  const inner = document.createElement("div");
  inner.innerHTML = `
    <h2>${esc(teamLabel(m) || t("no_team"))} <span class="mono muted">${esc(m.mac)}</span></h2>`;

  // Três abas: os gráficos do período (a leitura útil abre primeiro), o estado
  // cru de agora (a telemetria) e o histórico (o journal que a máquina manda a
  // cada 5 minutos). O journal só é buscado quando alguém clica — são centenas
  // de kB por máquina.
  const abas = document.createElement("div");
  abas.className = "tabs";
  abas.style.cssText = "display:flex;gap:8px;margin:10px 0";
  const painel = document.createElement("div");

  let desdeGraf = 7200; // 0 = tudo o que o samples.jsonl guarda
  const mostrarGraficos = async () => {
    painel.innerHTML = `<p class="muted">${t("loading")}</p>`;
    const since = desdeGraf ? Math.floor(Date.now() / 1000) - desdeGraf : 0;
    let dd;
    try {
      dd = await api.get(
        `/api/v1/site-images/${api.imageId}/machines/${m.mac}/samples?since=${since}`
      );
    } catch (e) {
      painel.innerHTML = `<p class="muted">${t("error")}: ${esc(e.message)}</p>`;
      return;
    }
    const pts = dd.points || [];
    const cores = m.status?.hwinfo?.cores;
    const maxLd = Math.max(0, ...pts.map((p) => p.ld ?? 0));
    const maxSw = Math.max(0, ...pts.map((p) => p.sw ?? 0));
    const periodos = [[1800, "30 min"], [7200, "2 h"], [18000, "5 h"], [86400, "24 h"], [0, t("period_all")]];
    painel.innerHTML =
      `<div class="gperiodo">${periodos
        .map(([s, r]) =>
          `<button type="button" class="small${s === desdeGraf ? " on" : ""}" data-desde="${s}">${r}</button>`)
        .join("")}</div>` +
      (dd.truncated ? `<p class="muted">${t("samples_truncated")}</p>` : "") +
      graficoTempo(pts, [
        { campo: "mem", cor: "#58a6ff", rot: "RAM", suf: "%" },
        { campo: "hd", cor: "#b78aff", rot: "/home", suf: "%" },
      ], 100) +
      graficoTempo(
        pts,
        [{ campo: "ld", cor: "#ffa657", rot: "load" }],
        Math.max(cores || 1, maxLd) * 1.1,
        cores,
        cores ? t("chart_cores", { n: cores }) : ""
      ) +
      graficoTempo(pts, [{ campo: "sw", cor: "#ff6b6b", rot: "swap", suf: " MB" }],
        Math.max(64, maxSw));
    painel.querySelectorAll(".gperiodo button").forEach((b) => {
      b.onclick = () => {
        desdeGraf = Number(b.dataset.desde);
        mostrarGraficos();
      };
    });
  };

  const mostrarEstado = () => {
    painel.innerHTML = `<pre>${esc(JSON.stringify(m.status, null, 1))}</pre>`;
  };
  const mostrarLogs = async () => {
    painel.innerHTML = `<p class="muted">${t("loading")}</p>`;
    try {
      const d = await api.get(
        `/api/v1/site-images/${api.imageId}/machines/${m.mac}/logs?tail=800`
      );
      const pre = document.createElement("pre");
      pre.textContent = d.journal || t("logs_none");
      pre.style.cssText = "max-height:52vh;overflow:auto";
      painel.innerHTML = "";
      painel.appendChild(pre);
      if (d.journal) {
        const baixar = document.createElement("button");
        baixar.className = "small";
        baixar.textContent = t("logs_download");
        baixar.onclick = () => {
          const url = URL.createObjectURL(new Blob([d.journal], { type: "text/plain" }));
          const a = document.createElement("a");
          a.href = url;
          a.download = `${m.mac}-journal.txt`;
          a.click();
          URL.revokeObjectURL(url);
        };
        painel.appendChild(baixar);
      }
    } catch (e) {
      painel.innerHTML = `<p class="muted">${t("error")}: ${esc(e.message)}</p>`;
    }
  };

  const recarregaEFecha = () => {
    box.remove();
    loadAll();
  };
  const mostrarTime = () => abaTime(m, painel, recarregaEFecha);
  const mostrarAlertas = () => alertas.abaAlertas(m, painel, recarregaEFecha);
  const mostrarOrdens = async () => {
    // os acks vêm junto com os logs; tail=1 é o mínimo que a rota aceita
    painel.innerHTML = `<p class="muted">${t("loading")}</p>`;
    let d;
    try {
      d = await api.get(`/api/v1/site-images/${api.imageId}/machines/${m.mac}/logs?tail=1`);
    } catch (e) {
      painel.innerHTML = `<p class="muted">${t("error")}: ${esc(e.message)}</p>`;
      return;
    }
    painel.innerHTML = "";
    if (m.pending) {
      const p = document.createElement("p");
      p.textContent = t("orders_pending", { n: m.pending });
      painel.appendChild(p);
    }
    const acks = (d.acks || []).slice().reverse();
    if (!acks.length) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = t("orders_none");
      painel.appendChild(p);
      return;
    }
    const tabela = document.createElement("table");
    for (const a of acks) {
      const tr = document.createElement("tr");
      const rot = ACK_LABEL[a.status] ? t(ACK_LABEL[a.status]) : String(a.status || "");
      tr.innerHTML = `<td class="muted">${new Date(a.at * 1000).toLocaleString()}</td>
        <td class="mono">${esc(a.command || a.id)}</td>
        <td><span class="pill ${a.status === "expired" ? "bad" : a.status === "done" ? "ok" : "warn"}">${esc(rot)}</span></td>`;
      const td = document.createElement("td");
      if (a.output) {
        const det = document.createElement("details");
        const sum = document.createElement("summary");
        sum.textContent = t("ack_output");
        const pre = document.createElement("pre");
        pre.textContent = String(a.output).slice(0, 4000);
        det.append(sum, pre);
        td.appendChild(det);
      }
      tr.appendChild(td);
      tabela.appendChild(tr);
    }
    painel.appendChild(tabela);
  };

  for (const [chave, acao] of [
    ["tab_charts", mostrarGraficos],
    ["tab_state", mostrarEstado],
    ["tab_logs", mostrarLogs],
    ["tab_team", mostrarTime],
    ["tab_alerts", mostrarAlertas],
    ["tab_orders", mostrarOrdens],
  ]) {
    const b = document.createElement("button");
    b.className = "small";
    b.textContent =
      chave === "tab_logs" && m.logs?.bytes
        ? `${t(chave)} (${Math.round(m.logs.bytes / 1024)} kB)`
        : t(chave);
    b.dataset.tab = chave;
    b.onclick = () => {
      abas.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      acao();
    };
    abas.appendChild(b);
  }
  const inicial = abrirNaAba || "tab_charts";
  [...abas.children].find((b) => b.dataset.tab === inicial).classList.add("on");
  ({ tab_team: mostrarTime, tab_alerts: mostrarAlertas, tab_orders: mostrarOrdens }[inicial] || mostrarGraficos)();
  inner.append(abas, painel);

  const close = document.createElement("button");
  close.textContent = t("close");
  close.onclick = () => box.remove();
  const lockBtn = document.createElement("button");
  lockBtn.className = "primary";
  lockBtn.textContent = m.lock?.locked ? t("unlock_screen") : t("lock_screen");
  lockBtn.onclick = async () => {
    const verb = m.lock?.locked ? "unlock" : "lock";
    await api.post(`/api/v1/site-images/${api.imageId}/machines/${m.mac}/${verb}`);
    box.remove();
    loadAll();
  };
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.style.marginTop = "12px";
  actions.append(lockBtn, close);
  inner.appendChild(actions);
  box.appendChild(inner);
  box.onclick = (e) => e.target === box && box.remove();
  document.body.appendChild(box);
}

// O servidor recusa comando que contradiz um campo travado no modelo — o
// botão não pode prometer o que ele vai negar. Falhar aqui não pode esconder a
// tela: sem a lista, todos os botões continuam oferecidos e quem clicar recebe
// a recusa do servidor, que é o que valia antes.
async function desabilitarComandosBloqueados() {
  let d;
  try {
    d = await api.get(`/api/v1/site-images/${api.imageId}/commands`);
  } catch {
    return;
  }
  bloqueados.clear();
  for (const [cmd, campo] of Object.entries(d.blocked || {})) {
    bloqueados.set(cmd, campo);
    const b = $(`[data-cmd="${cmd}"]`);
    if (!b) continue;
    b.disabled = true;
    b.title = t("command_locked", { field: campo });
  }
}

// A confirmação forte do pre-contest: digitar o número de máquinas, como no
// painel da frota. Um confirm() de um clique não está à altura de uma ação que
// apaga o trabalho de todos os times da seleção.
function confirmarPrecontest(n) {
  return new Promise((resolve) => {
    const fundo = document.createElement("div");
    fundo.className = "confirma";
    fundo.innerHTML = `<div class="cbox">
      <h3>${t("pre_contest")}</h3>
      <p>${t("pre_contest_confirm", { n })}</p>
      <p><input type="text" inputmode="numeric" id="cnum" autocomplete="off"></p>
      <div class="actions">
        <button type="button" class="danger" id="cok" disabled>${t("fleet_confirm_go")}</button>
        <button type="button" id="ccancel">${t("cancel")}</button>
      </div></div>`;
    document.body.appendChild(fundo);
    const campo = fundo.querySelector("#cnum");
    const ok = fundo.querySelector("#cok");
    campo.focus();
    campo.oninput = () => {
      ok.disabled = campo.value.trim() !== String(n);
    };
    ok.onclick = () => {
      fundo.remove();
      resolve(true);
    };
    fundo.querySelector("#ccancel").onclick = () => {
      fundo.remove();
      resolve(false);
    };
  });
}

let rastreador = null;

async function sendCommand(cmd) {
  const macs = [...selected];
  if (!macs.length) return;
  const label = $(`[data-cmd="${cmd}"]`).textContent;
  if (cmd === "precontest") {
    if (!(await confirmarPrecontest(macs.length))) return;
  } else if (!confirm(t("confirm_command", { cmd: label, n: macs.length }))) {
    return;
  }
  try {
    if (cmd === "lock" || cmd === "unlock") {
      const rs = await Promise.all(
        macs.map((mac) => api.post(`/api/v1/site-images/${api.imageId}/machines/${mac}/${cmd}`))
      );
      // cada trava é um comando por máquina: acompanha o primeiro id como amostra
      for (const [i, r] of rs.entries()) {
        if (r && r.command_id) rastreador.acompanhar(api.imageId, r.command_id, cmd, [macs[i]]);
      }
    } else {
      const r = await api.post(`/api/v1/site-images/${api.imageId}/commands`, { command: cmd, target: macs });
      if (r && r.command_id) rastreador.acompanhar(api.imageId, r.command_id, cmd, macs);
    }
    toast(t("command_sent", { n: macs.length }));
    loadAll();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function loadAll() {
  try {
    const horas = Number($("#vistas").value) || 0;
    const q = horas ? `?active_since=${Math.floor(Date.now() / 1000) - horas * 3600}` : "";
    const data = await api.get(`/api/v1/site-images/${api.imageId}/machines${q}`);
    machines = data.machines;
    rejeitadas = data.rejected || [];
    informarMaquinas(machines);
    render();
    if (visao === "times") renderTimes();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

// Relatório da sede por período: abre em outra aba, já com o token na URL —
// é `<a href>` na prática, e link não manda cabeçalho.
const PERIODOS = [
  ["report_last_hour", 3600],
  ["report_last_4h", 4 * 3600],
  ["report_today", 0],
];

function abrirRelatorio() {
  const escolhas = PERIODOS.map((p, i) => `${i + 1}) ${t(p[0])}`).join("\n");
  const escolha = prompt(`${t("report_period")}\n${escolhas}`, "2");
  if (!escolha) return;
  const idx = Math.min(Math.max(parseInt(escolha, 10) || 2, 1), PERIODOS.length) - 1;
  const agora = Math.floor(Date.now() / 1000);
  let desde;
  if (PERIODOS[idx][1]) {
    desde = agora - PERIODOS[idx][1];
  } else {
    const meia = new Date();
    meia.setHours(0, 0, 0, 0);
    desde = Math.floor(meia.getTime() / 1000);
  }
  window.open(api.reportUrl(api.imageId, desde, agora, currentLang()), "_blank");
}

function connectEvents() {
  if (source) source.close();
  source = new EventSource(api.eventsUrl(api.imageId));
  source.onopen = () => $("#live").classList.add("on");
  source.onerror = () => $("#live").classList.remove("on");
  // Qualquer evento agenda uma releitura curta — agrupa rajadas (sala inteira
  // reportando ao mesmo tempo) em uma única requisição.
  const bump = () => {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(loadAll, 400);
  };
  // O alerta não passa pelo debounce: 400 ms importa pouco para telemetria,
  // mas aqui é o intervalo entre alguém espetar um pendrive e o fiscal ver.
  source.addEventListener("alert.raised", () => {
    clearTimeout(refreshTimer);
    loadAll();
  });
  source.addEventListener("alert.dismissed", bump);
  source.addEventListener("command.acked", (ev) => {
    try {
      rastreador.ack(JSON.parse(ev.data));
    } catch {
      /* dado malformado: a reconciliação cobre */
    }
  });

  for (const ev of [
    "machine.status",
    "machine.first_seen",
    "machine.locked",
    "machine.unlocked",
    "machine.bound",
    "machine.unbound",
    "command.acked",
    "command.sent",
  ]) {
    source.addEventListener(ev, bump);
  }
}

function renderFilters() {
  const box = $("#filters");
  box.innerHTML = "";
  for (const f of FILTERS) {
    const b = document.createElement("button");
    b.className = "small" + (filter === f ? " on" : "");
    b.textContent = t(FILTER_LABEL[f]);
    b.onclick = () => {
      filter = f;
      renderFilters();
      render();
    };
    box.appendChild(b);
  }
}

async function main() {
  await init($("#lang"));
  if (!api.imageId) {
    $("#empty").textContent = t("no_token");
    $("#goconfig").remove();
    return;
  }
  // a identidade da sede, evidente: quem opera várias abas precisa saber em
  // qual sala está mandando comando. O fullname não vem em nenhuma resposta
  // que a tela já busca — um GET no image.json resolve (o token autentica).
  $("#identid").textContent = api.imageId;
  document.title = `${api.imageId} — hotconfig`;
  api.get(`/api/v1/site-images/${api.imageId}`).then((info) => {
    $("#identname").textContent = info.fullname || "";
    if (info.fullname) document.title = `${api.imageId} · ${info.fullname} — hotconfig`;
  }).catch(() => {});
  $("#goconfig").href = api.telaIrma("configureitor");
  await desabilitarComandosBloqueados();
  renderFilters();
  $("#search").oninput = render;
  $("#reportbtn").onclick = abrirRelatorio;
  $("#soundbtn").onclick = armarSom;
  atualizarBotaoSom();
  if (somArmado()) {
    // o navegador só libera áudio depois de um gesto; o primeiro clique em
    // qualquer lugar da página serve para reabrir o contexto
    document.addEventListener("click", () => {
      try {
        audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        audioCtx.resume();
      } catch {
        /* navegador sem WebAudio: a faixa vermelha continua valendo */
      }
    }, { once: true });
  }
  rastreador = criarRastreador($("#cmdprogress"), { nomeDoTime: (mac) => teamLabel(machines.find((x) => x.mac === mac) || {}) });
  iniciarTimes();
  alertas.iniciarAlertas();
  alertas.usarNomes((mac) => teamLabel(machines.find((x) => x.mac === mac) || {}) || "");
  sala.iniciarSala();
  sala.usarNomes(
    (mac) => teamLabel(machines.find((x) => x.mac === mac) || {}) || "",
    (mac) => {
      const m = machines.find((x) => x.mac === mac);
      if (m) showDetail(m);
    });
  for (const b of document.querySelectorAll("#views button")) b.onclick = () => mostrarVisao(b.dataset.view);
  document.addEventListener("nb3:abrir-time", (ev) => {
    const m = machines.find((x) => x.mac === ev.detail);
    if (m) showDetail(m, "tab_team");
  });
  document.addEventListener("nb3:roster-mudou", render);
  try {
    localStorage.setItem("nb3-lab-vistas", $("#vistas").value = localStorage.getItem("nb3-lab-vistas") || "0");
  } catch {
    /* sem storage: fica em "todas" */
  }
  $("#vistas").onchange = () => {
    try {
      localStorage.setItem("nb3-lab-vistas", $("#vistas").value);
    } catch {
      /* idem */
    }
    loadAll();
  };
  try {
    await carregarRoster();
  } catch {
    /* sem roster (ou sem escopo): o cartão mostra o user_id */
  }
  $("#selall").onclick = () => {
    machines.filter(matches).forEach((m) => selected.add(m.mac));
    render();
  };
  $("#selnone").onclick = () => {
    selected.clear();
    render();
  };
  $("#actionbar").querySelectorAll("[data-cmd]").forEach((b) => {
    b.onclick = () => sendCommand(b.dataset.cmd);
  });
  document.addEventListener("nb3:langchange", () => {
    apply();
    renderFilters();
    atualizarBotaoSom();
    render();
  });

  await loadAll();
  connectEvents();
  const inicial = location.hash.replace("#", "");
  if (["times", "sala", "alertas"].includes(inicial)) mostrarVisao(inicial);
  setInterval(loadAll, 30000); // rede de segurança se o SSE cair
}

main();
