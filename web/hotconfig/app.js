// Painel de gestão do laboratório: estado quase em tempo real (SSE) e ações
// em massa. O hotconfig do nb2 recarregava a lista inteira por polling manual
// (0/1/5/10 min) — aqui o servidor empurra as mudanças.
import * as api from "/common/api.js";
import { init, t, apply, currentLang } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);
let machines = [];
let rejeitadas = [];
let selected = new Set();
let filter = "all";
let source = null;
let refreshTimer = null;

const FILTERS = ["all", "usb", "locked", "alert", "unbound", "offline"];
const FILTER_LABEL = {
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
      <span class="amac">${quem}${a.mac}</span>
      <span>${[a.vendor, a.detail].filter(Boolean).join(" · ")}</span>
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

const KIND_LABEL = {
  "usb.storage": "usb_storage",
  "usb.phone": "usb_phone",
  "usb.network": "usb_network",
  "usb.other": "usb_other",
  "media.cd": "media_cd",
};

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
  return b.name || b.user_id || null;
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
  const load = Array.isArray(res.loadavg) ? res.loadavg[0] : null;
  const seat = m.binding?.seat ? `#${m.binding.seat} · ` : "";

  el.innerHTML = `
    <div class="team${team ? "" : " none"}">${seat}${team || t("no_team")}</div>
    <div class="mac">${m.mac}</div>
    <div class="metrics">
      <span>${t("memory")} <b class="${memPct > 85 ? "hot" : ""}">${memPct}%</b></span>
      ${load != null ? `<span>${t("load")} <b class="${load > 4 ? "hot" : ""}">${load.toFixed(1)}</b></span>` : ""}
      <span>${t("firewall")} <b>${ops.firewall === true ? "ON" : ops.firewall === false ? "OFF" : "—"}</b></span>
    </div>
    <div class="bar"><i class="${memPct > 85 ? "bad" : memPct > 70 ? "warn" : ""}" style="width:${Math.min(memPct, 100)}%"></i></div>
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
  const quais = rejeitadas.map((r) => `"${r.id}"`).join(", ");
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
  $("#actionbar").querySelectorAll("button").forEach((b) => (b.disabled = selected.size === 0));
}

function showDetail(m) {
  const box = document.createElement("div");
  box.className = "detail";
  const inner = document.createElement("div");
  inner.innerHTML = `
    <h2>${teamLabel(m) || t("no_team")} <span class="mono muted">${m.mac}</span></h2>`;

  // Duas abas: o estado de agora (a telemetria) e o histórico (o journal que a
  // máquina manda a cada 5 minutos). O journal só é buscado quando alguém
  // clica — são centenas de kB por máquina.
  const abas = document.createElement("div");
  abas.className = "tabs";
  abas.style.cssText = "display:flex;gap:8px;margin:10px 0";
  const painel = document.createElement("div");

  const mostrarEstado = () => {
    painel.innerHTML = `<pre>${JSON.stringify(m.status, null, 1)}</pre>`;
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
      painel.innerHTML = `<p class="muted">${t("error")}: ${e.message}</p>`;
    }
  };

  for (const [chave, acao] of [["tab_state", mostrarEstado], ["tab_logs", mostrarLogs]]) {
    const b = document.createElement("button");
    b.className = "small";
    b.textContent =
      chave === "tab_logs" && m.logs?.bytes
        ? `${t(chave)} (${Math.round(m.logs.bytes / 1024)} kB)`
        : t(chave);
    b.onclick = () => {
      abas.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      acao();
    };
    abas.appendChild(b);
  }
  abas.firstChild.classList.add("on");
  mostrarEstado();
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
  for (const [cmd, campo] of Object.entries(d.blocked || {})) {
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
      await Promise.all(
        macs.map((mac) => api.post(`/api/v1/site-images/${api.imageId}/machines/${mac}/${cmd}`))
      );
    } else {
      await api.post(`/api/v1/site-images/${api.imageId}/commands`, { command: cmd, target: macs });
    }
    toast(t("command_sent", { n: macs.length }));
    loadAll();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function loadAll() {
  try {
    const data = await api.get(`/api/v1/site-images/${api.imageId}/machines`);
    machines = data.machines;
    rejeitadas = data.rejected || [];
    render();
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
  $("#imginfo").textContent = api.imageId;
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
  setInterval(loadAll, 30000); // rede de segurança se o SSE cair
}

main();
