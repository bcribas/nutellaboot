// Painel da frota: todas as sedes de quem administra, numa tela.
//
// Não é o /hotconfig/ com mais linhas, e a razão é medida: a rota por sede
// chamada para 1890 máquinas custa 222 ms e 0,9 MB, e o painel por sede
// reatualiza 400 ms depois de qualquer evento. Repetir isso aqui seria 30% do
// worker ÚNICO, para sempre — o mesmo que atende o boot das salas.
//
// Daí o desenho: uma linha por SEDE (resumo enxuto, 119 ms), sondagem a cada
// 5 s em vez de SSE, e as máquinas de uma sede carregadas só quando alguém a
// expande — aí sim pela rota que já existe.
import * as api from "/common/api.js";
import { init, t, apply } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);

const SONDA_MS = 5000;
// acima disto, confirmar exige digitar o número de máquinas: um clique errado
// em "desligar" com a frota selecionada é a prova inteira no chão
const LIMITE_CONFIRMA = 50;

let sites = [];
let dias = 7;
let filtro = "all";
let expandidas = new Map(); // sede -> máquinas carregadas
let sedesSel = new Set();
let macsSel = new Map(); // sede -> Set(mac)
let timer = null;

const FILTROS = ["all", "alert", "locked", "offline"];
const FILTRO_LABEL = {
  all: "filter_all",
  alert: "filter_alert",
  locked: "filter_locked",
  offline: "filter_offline",
};

function toast(msg, isErro = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isErro ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function combina(s) {
  const q = $("#search").value.trim().toLowerCase();
  if (q && !`${s.id} ${s.fullname}`.toLowerCase().includes(q)) return false;
  if (filtro === "alert") return s.alerts > 0;
  if (filtro === "locked") return s.locked > 0;
  if (filtro === "offline") return s.online < s.machines;
  return true;
}

function num(v, classe = "") {
  return `<td class="${v ? classe : "n0"}">${v}</td>`;
}

// --- seleção ---------------------------------------------------------------
//
// Dois níveis ao mesmo tempo: sede inteira e máquina solta de outra. Marcar a
// sede vale por todas as máquinas dela, inclusive as que ainda não foram
// carregadas — por isso o alvo dela é "all" e não uma lista.

function macsDa(sede) {
  return macsSel.get(sede) || new Set();
}

function contaSelecionadas() {
  let n = 0;
  for (const s of sites) {
    if (sedesSel.has(s.id)) n += s.machines;
    else n += macsDa(s.id).size;
  }
  return n;
}

function alvos() {
  const out = {};
  for (const s of sites) {
    if (sedesSel.has(s.id)) out[s.id] = "all";
    else if (macsDa(s.id).size) out[s.id] = [...macsDa(s.id)];
  }
  return out;
}

function render() {
  const tabela = $("#sites");
  const lista = sites.filter(combina);
  tabela.innerHTML = `<tr>
    <th></th><th data-col="sede">${t("fleet_site")}</th>
    <th>${t("fleet_machines")}</th><th>${t("fleet_active")}</th><th>${t("fleet_new")}</th>
    <th>${t("online")}</th><th>${t("fleet_locked")}</th><th>${t("fleet_alerts")}</th>
  </tr>`;

  for (const s of lista) {
    const tr = document.createElement("tr");
    tr.className = "sede" + (sedesSel.has(s.id) ? " sel" : "");
    const marcadas = macsDa(s.id).size;
    tr.innerHTML =
      `<td class="expandir"><button type="button">${expandidas.has(s.id) ? "▾" : "▸"}</button></td>
       <td class="nome"><span class="sedeid">${s.id}</span>
         ${marcadas ? `<span class="sedenome"> · ${marcadas} ${t("fleet_picked")}</span>` : ""}
         <br><span class="sedenome">${s.fullname || ""}</span></td>` +
      num(s.machines) + num(s.active) + num(s.new) + num(s.online) +
      num(s.locked, "ntrava") + num(s.alerts, "nalerta");

    tr.querySelector(".expandir button").onclick = (e) => {
      e.stopPropagation();
      expandidas.has(s.id) ? expandidas.delete(s.id) : carregarMaquinas(s.id);
      render();
    };
    tr.onclick = () => {
      if (sedesSel.has(s.id)) sedesSel.delete(s.id);
      else {
        sedesSel.add(s.id);
        macsSel.delete(s.id); // a sede inteira substitui a escolha fina
      }
      render();
    };
    tabela.appendChild(tr);

    if (expandidas.has(s.id)) tabela.appendChild(linhaMaquinas(s));
  }

  $("#empty").textContent = lista.length ? "" : t("fleet_empty");
  const n = contaSelecionadas();
  $("#selcount").textContent = n ? t("selected_n", { n }) : t("select_hint");
  $("#actionbar").style.display = n ? "" : "none";
  const totais = sites.reduce(
    (a, s) => ({ m: a.m + s.machines, o: a.o + s.online, al: a.al + s.alerts }),
    { m: 0, o: 0, al: 0 }
  );
  $("#resumo").textContent = t("fleet_summary", {
    sites: sites.length, machines: totais.m, online: totais.o, alerts: totais.al,
  });
}

function linhaMaquinas(s) {
  const tr = document.createElement("tr");
  tr.className = "maquinas";
  const td = document.createElement("td");
  td.colSpan = 8;
  const lista = expandidas.get(s.id);
  if (!lista) {
    td.innerHTML = `<span class="muted small">${t("loading")}</span>`;
    tr.appendChild(td);
    return tr;
  }
  const caixa = document.createElement("div");
  caixa.className = "mlist";
  for (const mq of lista) {
    const chip = document.createElement("span");
    const marcado = sedesSel.has(s.id) || macsDa(s.id).has(mq.mac);
    chip.className =
      "mchip" + (marcado ? " sel" : "") + (mq.online ? "" : " off") +
      ((mq.alerts || []).length ? " alerta" : "");
    const time = mq.binding?.name || mq.binding?.user_id || "";
    chip.innerHTML = `<span class="mac">${mq.mac}</span>${
      time ? `<span class="time">${time}</span>` : ""
    }${mq.lock?.locked ? "🔒" : ""}`;
    chip.onclick = () => {
      // escolher máquina a máquina desmarca a sede inteira: os dois juntos
      // fariam a contagem mentir
      sedesSel.delete(s.id);
      const set = macsSel.get(s.id) || new Set();
      set.has(mq.mac) ? set.delete(mq.mac) : set.add(mq.mac);
      set.size ? macsSel.set(s.id, set) : macsSel.delete(s.id);
      render();
    };
    caixa.appendChild(chip);
  }
  td.appendChild(caixa);
  tr.appendChild(td);
  return tr;
}

async function carregarMaquinas(sede) {
  expandidas.set(sede, null);
  try {
    const d = await api.get(`/api/v1/site-images/${encodeURIComponent(sede)}/machines`);
    expandidas.set(sede, d.machines || []);
  } catch (e) {
    expandidas.delete(sede);
    toast(`${t("error")}: ${e.message}`, true);
  }
  render();
}

async function carregar() {
  try {
    const d = await api.get(`/api/v1/labs?dias=${dias}`, { kind: "admin" });
    sites = d.sites || [];
  } catch (e) {
    $("#empty").textContent = `${t("error")}: ${e.message}`;
    return;
  }
  // as sedes abertas continuam com as máquinas frescas
  for (const sede of [...expandidas.keys()]) {
    if (expandidas.get(sede) !== null) carregarMaquinas(sede);
  }
  render();
}

// --- comandos ---------------------------------------------------------------

async function confirmar(cmd, n) {
  if (n < LIMITE_CONFIRMA) return confirm(t("confirm_command", { cmd, n }));
  return new Promise((resolve) => {
    const fundo = document.createElement("div");
    fundo.className = "confirma";
    fundo.innerHTML = `<div class="cbox">
      <h3>${cmd}</h3>
      <p>${t("fleet_confirm_type", { n })}</p>
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

async function mandar(cmd) {
  const targets = alvos();
  const n = contaSelecionadas();
  if (!n) return;
  if (!(await confirmar(cmd, n))) return;

  try {
    // lock/unlock são estado, não fila: têm rota própria por sede
    const corpo =
      cmd === "lock" || cmd === "unlock"
        ? null
        : { command: cmd, targets };
    if (corpo) {
      const d = await api.post("/api/v1/commands", corpo, { kind: "admin" });
      const falhas = d.failed || [];
      toast(
        falhas.length
          ? t("fleet_partial", { n: d.machines, falhas: falhas.join(", ") })
          : t("command_sent", { n: d.machines }),
        falhas.length > 0
      );
      for (const sede of falhas) {
        const motivo = d.results[sede]?.error;
        if (motivo) toast(`${sede}: ${motivo}`, true);
      }
    } else {
      const sedes = Object.keys(targets);
      await Promise.all(
        sedes.map((sede) =>
          api.post(`/api/v1/site-images/${encodeURIComponent(sede)}/${cmd}`, {}, { kind: "admin" })
        )
      );
      toast(t("command_sent", { n }));
    }
    carregar();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

function renderFiltros() {
  const box = $("#filters");
  box.innerHTML = "";
  for (const f of FILTROS) {
    const b = document.createElement("button");
    b.className = "small" + (filtro === f ? " on" : "");
    b.textContent = t(FILTRO_LABEL[f]);
    b.onclick = () => {
      filtro = f;
      renderFiltros();
      render();
    };
    box.appendChild(b);
  }
}

function atualizarCsv() {
  $("#csv").href = `/api/v1/labs?dias=${dias}&format=csv`;
  $("#csv").setAttribute("download", "");
}

async function main() {
  await init($("#lang"));
  apply(document);
  renderFiltros();
  atualizarCsv();
  $("#search").oninput = render;
  $("#dias").onchange = () => {
    dias = Number($("#dias").value);
    atualizarCsv();
    carregar();
  };
  for (const b of document.querySelectorAll("[data-cmd]")) {
    b.onclick = () => mandar(b.dataset.cmd);
  }
  await carregar();
  timer = setInterval(carregar, SONDA_MS);
  window.addEventListener("beforeunload", () => clearInterval(timer));
}

main();
