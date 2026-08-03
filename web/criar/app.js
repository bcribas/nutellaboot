// Criar imagem por auto-atendimento: com código de convite (cria na hora) ou
// sem código (envia um pedido para a administração aprovar).
import * as api from "/common/api.js";
import { init, t, apply } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function copyRow(label, value) {
  const tr = document.createElement("tr");
  const th = document.createElement("td");
  th.className = "muted";
  th.textContent = label;
  const td = document.createElement("td");
  const code = document.createElement("code");
  code.textContent = value;
  const btn = document.createElement("button");
  btn.className = "small";
  btn.textContent = t("copy");
  btn.onclick = async () => {
    await navigator.clipboard.writeText(value);
    btn.textContent = t("copied");
    setTimeout(() => (btn.textContent = t("copy")), 1500);
  };
  td.append(code, " ", btn);
  tr.append(th, td);
  return tr;
}

function showResult(info) {
  const box = $("#result");
  box.innerHTML = "";
  const card = document.createElement("div");
  card.className = "card";
  card.style.borderColor = "var(--accent)";
  card.style.marginTop = "16px";
  card.innerHTML = `<h2>${t("create_done")}</h2>`;
  const table = document.createElement("table");
  const rows = [
    [t("image"), info.id],
    [t("token"), info.token],
    [t("boot_key"), info.boot_key],
    [t("machine_key"), info.machine_key],
    [t("config_link"), info.configureitor_url],
    [t("manage_link"), info.hotconfig_url],
  ];
  for (const [k, v] of rows) if (v) table.appendChild(copyRow(k, v));
  card.appendChild(table);
  const open = document.createElement("a");
  open.className = "btn primary";
  open.style.marginTop = "12px";
  open.href = info.configureitor_url;
  open.textContent = t("home_coord_open_config");
  card.appendChild(open);

  if (info.console_code) {
    const console_ = document.createElement("button");
    console_.className = "btn";
    console_.style.marginTop = "12px";
    console_.style.marginLeft = "8px";
    console_.textContent = t("console_enter");
    console_.onclick = () => entrarNoConsole(info.console_code);
    card.appendChild(console_);
  }
  box.appendChild(card);
  box.scrollIntoView({ behavior: "smooth" });
}

async function loadTemplates() {
  try {
    const data = await (await fetch("/api/v1/public/models")).json();
    const sel = $("#ctpl");
    sel.innerHTML = "";
    for (const tpl of data.models) {
      const o = document.createElement("option");
      o.value = tpl.name;
      o.textContent = tpl.description ? `${tpl.name} — ${tpl.description}` : tpl.name;
      sel.appendChild(o);
    }
    // se não houver modelo público, o campo some (o código pode fixar um)
    $("#tplfield").style.display = data.models.length ? "" : "none";
  } catch {
    $("#tplfield").style.display = "none";
  }
}

async function create() {
  const body = {
    code: $("#code").value.trim(),
    id: $("#cname").value.trim(),
    fullname: $("#cfull").value.trim(),
    model: $("#ctpl").value || undefined,
  };
  $("#code_status").textContent = t("loading");
  try {
    const resp = await fetch("/api/v1/public/site-images", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || t("create_bad_code"));
    $("#code_status").textContent = "";
    showResult(data);
  } catch (e) {
    $("#code_status").textContent = "";
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function sendRequest() {
  const body = {
    wanted_name: $("#rname").value.trim(),
    contact: $("#rcontact").value.trim(),
    note: $("#rnote").value.trim(),
  };
  if (!body.wanted_name || !body.contact) {
    toast(t("request_wanted"), true);
    return;
  }
  $("#req_status").textContent = t("loading");
  try {
    const resp = await fetch("/api/v1/public/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "erro");
    $("#req_status").textContent = "";
    $("#rname").value = $("#rcontact").value = $("#rnote").value = "";
    toast(t("request_sent"));
  } catch (e) {
    $("#req_status").textContent = "";
    toast(`${t("error")}: ${e.message}`, true);
  }
}

// O mesmo código que cria a imagem é a credencial do console de sub-admin —
// quem já criou não precisa de outra senha para voltar.
// O mesmo código que cria a imagem abre o console de sub-admin. Ele é trocado
// por um cookie de sessão aqui, então não fica guardado no navegador.
async function entrarNoConsole(code) {
  code = (code || $("#code").value).trim().toUpperCase();
  if (!code) {
    toast(t("create_bad_code"), true);
    return;
  }
  try {
    await api.login(code);
    location.href = "/admin/";
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

function tab(which) {
  $("#tab_code").classList.toggle("on", which === "code");
  $("#tab_req").classList.toggle("on", which === "req");
  $("#pane_code").classList.toggle("on", which === "code");
  $("#pane_req").classList.toggle("on", which === "req");
}

async function main() {
  await init($("#lang"));
  await loadTemplates();
  $("#tab_code").onclick = () => tab("code");
  $("#tab_req").onclick = () => tab("req");
  $("#go").onclick = create;
  $("#go_console").onclick = () => entrarNoConsole();
  $("#send").onclick = sendRequest;
  document.addEventListener("nb3:langchange", apply);
}

main();
