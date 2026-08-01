// Administração: imagens, criação em massa e credenciais.
import * as api from "/common/api.js";
import { init, t, apply } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);
const A = { kind: "admin" };
let images = [];
let templates = [];
let lastBulkCsv = "";

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function copyable(label, value) {
  const wrap = document.createElement("span");
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
  wrap.append(code, " ", btn);
  return wrap;
}

function credentialsCard(info) {
  const card = document.createElement("div");
  card.className = "card";
  card.style.borderColor = "var(--accent)";
  const url = `${location.origin}/configureitor/?id=${info.id}&tk=${info.token}`;
  const rows = [
    [t("image"), info.id],
    [t("token"), info.token],
    [t("machine_key"), info.machine_key],
    [t("config_link"), url],
  ];
  card.innerHTML = `<h2>${t("created")}: ${info.id}</h2>`;
  const table = document.createElement("table");
  for (const [k, v] of rows) {
    const tr = document.createElement("tr");
    const th = document.createElement("td");
    th.className = "muted";
    th.textContent = k;
    const td = document.createElement("td");
    td.appendChild(copyable(k, v));
    tr.append(th, td);
    table.appendChild(tr);
  }
  card.appendChild(table);
  return card;
}

function renderImages() {
  const q = $("#filter").value.trim().toLowerCase();
  const list = images.filter(
    (i) => !q || i.id.includes(q) || (i.fullname || "").toLowerCase().includes(q)
  );
  $("#imgcount").textContent = `(${list.length})`;
  const box = $("#imglist");
  if (!list.length) {
    box.className = "muted";
    box.textContent = "—";
    return;
  }
  box.className = "";
  box.innerHTML = "";
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr>
    <th>${t("image_id")}</th><th>${t("image_name")}</th>
    <th>${t("template")}</th><th></th><th></th></tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const img of list) {
    const tr = document.createElement("tr");
    const reserved = img.namespace === "contest";
    tr.innerHTML = `
      <td class="mono">${img.id}</td>
      <td>${img.fullname || ""}</td>
      <td class="muted">${img.template || ""}</td>
      <td><span class="pill ${reserved ? "warn" : ""}">${
        reserved ? t("reserved_namespace") : t("personal_namespace")
      }</span></td>`;
    const actions = document.createElement("td");
    const rot = document.createElement("button");
    rot.className = "small";
    rot.textContent = t("rotate_token");
    rot.onclick = async () => {
      const r = await api.post(`/api/v1/images/${img.id}/token/rotate`, undefined, A);
      document.querySelector("main").prepend(
        credentialsCard({ id: img.id, token: r.token, machine_key: "—" })
      );
    };
    const del = document.createElement("button");
    del.className = "small danger";
    del.textContent = t("delete");
    del.onclick = async () => {
      if (!confirm(t("confirm_delete", { id: img.id }))) return;
      await api.del(`/api/v1/images/${img.id}`, A);
      load();
    };
    actions.append(rot, " ", del);
    tr.appendChild(actions);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  box.appendChild(table);
}

async function load() {
  const [imgs, tpls] = await Promise.all([
    api.get("/api/v1/images", A),
    api.get("/api/v1/templates", A),
  ]);
  images = imgs.images;
  templates = tpls.templates;
  const sel = $("#newtpl");
  sel.innerHTML = "";
  for (const name of templates) {
    const o = document.createElement("option");
    o.value = o.textContent = name;
    sel.appendChild(o);
  }
  renderImages();
}

async function createImage() {
  const id = $("#newid").value.trim();
  const fullname = $("#newname").value.trim();
  const template = $("#newtpl").value;
  if (!id) return;
  try {
    const info = await api.post("/api/v1/images", { id, fullname, template }, A);
    document.querySelector("main").prepend(credentialsCard(info));
    $("#newid").value = $("#newname").value = "";
    load();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function bulkCreate() {
  const tsv = $("#bulktsv").value.trim();
  if (!tsv) return;
  $("#bulkstatus").textContent = t("loading");
  try {
    const resp = await fetch("/api/v1/images/bulk?format=csv", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${api.adminKey()}`,
        "Content-Type": "text/tab-separated-values",
      },
      body: tsv,
    });
    lastBulkCsv = await resp.text();
    if (!resp.ok) throw new Error(lastBulkCsv);
    const rows = lastBulkCsv.trim().split("\n").slice(1);
    const ok = rows.filter((r) => r.split(",")[1] === "True").length;
    $("#bulkstatus").textContent = t("bulk_result", { ok, fail: rows.length - ok });
    $("#bulkcsv").classList.remove("hidden");
    load();
  } catch (e) {
    $("#bulkstatus").textContent = "";
    toast(`${t("error")}: ${e.message}`, true);
  }
}

function downloadCsv() {
  const blob = new Blob([lastBulkCsv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "nutellaboot3-credenciais.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function enter() {
  api.setAdminKey($("#key").value.trim());
  try {
    await load();
    $("#login").classList.add("hidden");
    $("#panel").classList.remove("hidden");
    $("#logout").classList.remove("hidden");
  } catch (e) {
    api.clearAdminKey();
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function main() {
  await init($("#lang"));
  $("#enter").onclick = enter;
  $("#key").onkeydown = (e) => e.key === "Enter" && enter();
  $("#create").onclick = createImage;
  $("#bulkgo").onclick = bulkCreate;
  $("#bulkcsv").onclick = downloadCsv;
  $("#reload").onclick = load;
  $("#filter").oninput = renderImages;
  $("#logout").onclick = () => {
    api.clearAdminKey();
    location.reload();
  };
  document.addEventListener("nb3:langchange", () => {
    apply();
    if (images.length) renderImages();
  });
  if (api.adminKey()) enter();
}

main();
