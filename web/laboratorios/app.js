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

function hotconfigUrl(sede) {
  return `/hotconfig/?id=${encodeURIComponent(sede)}`;
}

// A faixa global: sala de controle. Cada alerta diz sede, máquina, time, tipo
// e hora; clicar abre o hotconfig da sede, onde se dispensa com registro.
function renderAlertas() {
  const caixa = $("#fleetalerts");
  const lista = $("#falist");
  const todos = sites.flatMap((s) =>
    (s.alert_list || []).map((a) => ({ ...a, sede: s.id }))
  );
  todos.sort((a, b) => (b.at || 0) - (a.at || 0));
  caixa.hidden = !todos.length;
  lista.innerHTML = "";
  for (const a of todos) {
    const row = document.createElement("a");
    row.className = "farow";
    row.href = hotconfigUrl(a.sede);
    row.target = "_blank";
    row.rel = "noopener";
    row.innerHTML = `<b class="fasede">${a.sede}</b>
      <span class="awhat">${t(KIND_LABEL[a.kind] || "usb_other")}</span>
      <span class="amac">${a.team ? `${a.team} · ` : ""}${a.mac || ""}</span>
      <span class="fadet">${a.vendor || a.detail || ""}</span>
      <span class="awhen">${hora(a.at)}</span>`;
    lista.appendChild(row);
  }
}

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
         <a class="gohot" href="${hotconfigUrl(s.id)}" target="_blank" rel="noopener"
            title="${t("fleet_open_hotconfig")}">\u2197</a>
         ${marcadas ? `<span class="sedenome"> · ${marcadas} ${t("fleet_picked")}</span>` : ""}
         <br><span class="sedenome">${s.fullname || ""}</span></td>` +
      num(s.machines) + num(s.active) + num(s.new) + num(s.online) +
      num(s.locked, "ntrava") + num(s.alerts, "nalerta");

    tr.querySelector(".expandir button").onclick = (e) => {
      e.stopPropagation();
      expandidas.has(s.id) ? expandidas.delete(s.id) : carregarMaquinas(s.id);
      render();
    };
    tr.querySelector(".gohot").onclick = (e) => e.stopPropagation();
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

  renderAlertas();
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
  // os alertas da sede, acima das máquinas — o detalhe que a linha não cabe
  const comAlerta = lista.flatMap((mq) => (mq.alerts || []).map((a) => ({ ...a, mq })));
  if (comAlerta.length) {
    const bloco = document.createElement("div");
    bloco.className = "sedealertas";
    for (const a of comAlerta) {
      const linha = document.createElement("div");
      linha.className = "farow";
      linha.innerHTML = `<span class="awhat">${t(KIND_LABEL[a.kind] || "usb_other")}</span>
        <span class="amac">${a.mq.binding?.name ? `${a.mq.binding.name} · ` : ""}${a.mq.mac}</span>
        <span class="fadet">${a.vendor || a.detail || ""}</span>
        <span class="awhen">${hora(a.at)}</span>`;
      bloco.appendChild(linha);
    }
    td.appendChild(bloco);
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
  carregarRelatorio();
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

// --- relatório da frota -----------------------------------------------------
//
// O botão pede e a tela pergunta; quem faz a conta é um subprocesso. A sondagem
// é a mesma de 5 s que já roda — enquanto está `building` ela mostra isso, e
// quando vira `done` os links aparecem sozinhos.

// Nome do arquivo → rótulo. Lista aqui e no servidor pelo mesmo motivo: o que
// não está nas duas não é oferecido nem servido.
const ARQ_LABEL = {
  "relatorio.html": "report_f_html",
  "inventario.csv": "report_f_inventario",
  "editores.csv": "report_f_editores",
  "recursos-hora.csv": "report_f_recursos_hora",
  "recursos-brutos.csv.gz": "report_f_recursos_brutos",
  "alertas.csv": "report_f_alertas",
  "resumo.json": "report_f_resumo",
};

let relatorio = null;
let podeRelatorio = true;
// sedes fora do relatório — pré-carregada do estado da última geração; o
// usuário mexe nas caixas e o POST leva a lista nova
let excluidas = new Set();
let excluidasCarregadas = false;

function tamanho(bytes) {
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${bytes} B`;
}

function renderExcluidas() {
  const caixa = $("#rexlist");
  caixa.innerHTML = "";
  for (const s of sites) {
    const lab = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = excluidas.has(s.id);
    cb.onchange = () => {
      cb.checked ? excluidas.add(s.id) : excluidas.delete(s.id);
      $("#rexn").textContent = excluidas.size ? `(${excluidas.size})` : "";
    };
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(` ${s.id}`));
    caixa.appendChild(lab);
  }
  $("#rexn").textContent = excluidas.size ? `(${excluidas.size})` : "";
}

function renderRelatorio() {
  const sec = $("#relatorio");
  sec.hidden = !podeRelatorio;
  if (!podeRelatorio) return;
  const r = relatorio || {};
  // a memória entre gerações: o estado guarda quem ficou fora da última
  if (!excluidasCarregadas && Array.isArray(r.excluded)) {
    excluidas = new Set(r.excluded);
    excluidasCarregadas = true;
  }
  renderExcluidas();
  const estado = $("#restado");
  const arquivos = $("#rfiles");
  estado.classList.toggle("err", r.status === "failed");
  $("#rgerar").disabled = r.status === "building";

  if (r.status === "building") {
    estado.textContent = t("report_fleet_building");
  } else if (r.status === "failed") {
    estado.textContent = t("report_fleet_failed", { erro: r.error || "" });
  } else if (r.status === "done") {
    const janela = Math.round(((r.until || 0) - (r.since || 0)) / 86400);
    estado.textContent =
      t("report_fleet_ready", {
        when: new Date((r.built_at || 0) * 1000).toLocaleString(),
        dias: janela,
      }) +
      ((r.excluded || []).length
        ? ` · ${t("report_fleet_excluded_n", { n: r.excluded.length })}`
        : "");
  } else {
    estado.textContent = t("report_fleet_none");
  }

  arquivos.innerHTML = "";
  for (const f of r.files || []) {
    const a = document.createElement("a");
    a.href = `/api/v1/labs/report/${encodeURIComponent(f.name)}`;
    // o HTML é para olhar, os dados são para levar embora
    if (f.name.endsWith(".html")) {
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "destaque";
    } else {
      a.setAttribute("download", "");
    }
    a.innerHTML = `<span>${t(ARQ_LABEL[f.name] || f.name)}</span><span class="tam">${tamanho(
      f.size || 0
    )}</span>`;
    arquivos.appendChild(a);
  }
}

async function carregarRelatorio() {
  if (!podeRelatorio) return;
  try {
    relatorio = await api.get("/api/v1/labs/report", { kind: "admin" });
  } catch (e) {
    // sub-admin não tem esta rota: some a seção em vez de piscar erro a cada
    // 5 s numa tela que, para ele, funciona
    if (e.status === 401 || e.status === 403) podeRelatorio = false;
    else return;
  }
  renderRelatorio();
}

async function pedirRelatorio() {
  $("#rgerar").disabled = true;
  try {
    relatorio = await api.post(
      "/api/v1/labs/report",
      { dias, excluir: [...excluidas] },
      { kind: "admin" }
    );
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
  renderRelatorio();
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
  $("#rgerar").onclick = pedirRelatorio;
  await carregar();
  timer = setInterval(carregar, SONDA_MS);
  window.addEventListener("beforeunload", () => clearInterval(timer));
}

main();
