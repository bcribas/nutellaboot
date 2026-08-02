// Painel de gestão do laboratório: estado quase em tempo real (SSE) e ações
// em massa. O hotconfig do nb2 recarregava a lista inteira por polling manual
// (0/1/5/10 min) — aqui o servidor empurra as mudanças.
import * as api from "/common/api.js";
import { init, t, apply } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);
let machines = [];
let selected = new Set();
let filter = "all";
let source = null;
let refreshTimer = null;

const FILTERS = ["all", "locked", "alert", "unbound", "offline"];
const FILTER_LABEL = {
  all: "filter_all",
  locked: "filter_locked",
  alert: "filter_alert",
  unbound: "filter_unbound",
  offline: "filter_offline",
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
  if (filter === "alert") return isAlert(m);
  if (filter === "unbound") return !m.binding;
  if (filter === "offline") return !m.online;
  return true;
}

function card(m) {
  const el = document.createElement("div");
  const st = state(m);
  el.className = `mcard ${st}` + (m.lock?.locked ? " locked" : "") + (selected.has(m.mac) ? " sel" : "");
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

function render() {
  const list = machines.filter(matches);
  const grid = $("#grid");
  grid.innerHTML = "";
  list.forEach((m) => grid.appendChild(card(m)));
  $("#empty").classList.toggle("hidden", machines.length > 0);

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
    <h2>${teamLabel(m) || t("no_team")} <span class="mono muted">${m.mac}</span></h2>
    <pre>${JSON.stringify(m.status, null, 1)}</pre>`;
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

async function sendCommand(cmd) {
  const macs = [...selected];
  if (!macs.length) return;
  const label = $(`[data-cmd="${cmd}"]`).textContent;
  if (!confirm(t("confirm_command", { cmd: label, n: macs.length }))) return;
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
    render();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
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
    return;
  }
  $("#imginfo").textContent = api.imageId;
  renderFilters();
  $("#search").oninput = render;
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
    render();
  });

  await loadAll();
  connectEvents();
  setInterval(loadAll, 30000); // rede de segurança se o SSE cair
}

main();
