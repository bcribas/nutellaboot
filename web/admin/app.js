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

function credentialsCard(info, title) {
  const card = document.createElement("div");
  card.className = "card";
  card.style.borderColor = "var(--accent)";
  // links prontos: preferimos os que vêm do servidor (já com o token e a base
  // corretos); se não vierem, montamos a partir da origem atual.
  const configUrl =
    info.configureitor_url || `${location.origin}/configureitor/?id=${info.id}&tk=${info.token}`;
  const hotUrl =
    info.hotconfig_url || `${location.origin}/hotconfig/?id=${info.id}&tk=${info.token}`;
  const rows = [
    [t("image"), info.id],
    [t("token"), info.token],
    [t("machine_key"), info.machine_key],
    [t("boot_key"), info.boot_key],
    [t("config_link"), configUrl],
    [t("manage_link"), hotUrl],
  ];
  card.innerHTML = `<h2>${title || t("created")}: ${info.id}</h2>`;
  const table = document.createElement("table");
  for (const [k, v] of rows) {
    if (!v || v === "—") continue;
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
  const fechar = document.createElement("button");
  fechar.className = "small";
  fechar.style.marginTop = "10px";
  fechar.textContent = t("close");
  fechar.onclick = () => card.remove();
  card.appendChild(fechar);
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
    const livre = Boolean(img.unlocked);
    tr.innerHTML = `
      <td class="mono">${img.id}</td>
      <td>${img.fullname || ""}</td>
      <td class="muted">${img.template || ""}</td>
      <td><span class="pill ${reserved ? "warn" : ""}">${
        reserved ? t("reserved_namespace") : t("personal_namespace")
      }</span>
      <span class="pill ${livre ? "ok" : ""}" title="${
        livre ? t("profile_free") : t("profile_official")
      }">${livre ? t("profile_free_short") : t("profile_official_short")}</span></td>`;
    const actions = document.createElement("td");
    // alterna Oficial <-> Livre: é assim que se "volta uma imagem com tudo
    // liberado" sem recriar nada
    const perfil = document.createElement("button");
    perfil.className = "small";
    perfil.textContent = livre ? t("make_official") : t("make_free");
    perfil.onclick = async () => {
      await api.patch(`/api/v1/images/${img.id}`, { unlocked: !livre }, A);
      load();
    };
    const ver = document.createElement("button");
    ver.className = "small";
    ver.textContent = t("view_credentials");
    ver.onclick = async () => {
      // lê as credenciais atuais sem rotacionar nada (não invalida links já
      // distribuídos) — é o caminho fácil para pegar o token e o link da sede
      const cred = await api.get(`/api/v1/images/${img.id}/credentials`, A);
      document.querySelector("main").prepend(credentialsCard(cred, t("view_credentials")));
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    const rot = document.createElement("button");
    rot.className = "small";
    rot.textContent = t("rotate_token");
    rot.onclick = async () => {
      const r = await api.post(`/api/v1/images/${img.id}/token/rotate`, undefined, A);
      document.querySelector("main").prepend(
        credentialsCard({ id: img.id, token: r.token }, t("rotate_token"))
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
    actions.append(perfil, " ", ver, " ", rot, " ", del);
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
  // /templates agora devolve [{name, public}]
  templates = tpls.templates.map((tpl) => (typeof tpl === "string" ? { name: tpl, public: false } : tpl));
  const sel = $("#newtpl");
  sel.innerHTML = "";
  for (const tpl of templates) {
    const o = document.createElement("option");
    o.value = o.textContent = tpl.name;
    sel.appendChild(o);
  }
  // template opcional do convite (vazio = a pessoa escolhe entre os públicos)
  const invsel = $("#inv_tpl");
  if (invsel) {
    invsel.innerHTML = '<option value="">—</option>';
    for (const tpl of templates) {
      const o = document.createElement("option");
      o.value = o.textContent = tpl.name;
      invsel.appendChild(o);
    }
  }
  renderImages();
  renderTemplates();
  loadInvites();
  loadRequests();
}

function renderTemplates() {
  const box = $("#tpllist");
  if (!box) return;
  box.innerHTML = "";
  const table = document.createElement("table");
  for (const tpl of templates) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="mono">${tpl.name}</td>
      <td><span class="pill ${tpl.public ? "ok" : ""}">${
        tpl.public ? t("template_public") : "—"
      }</span></td>`;
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "small";
    btn.textContent = tpl.public ? t("make_private") : t("make_public");
    btn.onclick = async () => {
      await api.patch(`/api/v1/templates/${tpl.name}`, { public: !tpl.public }, A);
      load();
    };
    td.appendChild(btn);
    tr.appendChild(td);
    table.appendChild(tr);
  }
  box.appendChild(table);
}

async function loadInvites() {
  const box = $("#invlist");
  if (!box) return;
  const data = await api.get("/api/v1/invites", A);
  box.innerHTML = "";
  if (!data.invites.length) {
    box.className = "muted";
    box.textContent = "—";
    return;
  }
  box.className = "";
  const table = document.createElement("table");
  for (const inv of data.invites) {
    const tr = document.createElement("tr");
    const td0 = document.createElement("td");
    td0.appendChild(copyable(t("create_code"), inv.code));
    tr.appendChild(td0);
    const meta = document.createElement("td");
    meta.className = "muted";
    const perfil = inv.unlocked === false ? t("profile_official_short") : t("profile_free_short");
    meta.textContent = `${inv.remaining} ${t("invite_remaining")} · ${perfil}${inv.template ? " · " + inv.template : ""}${inv.note ? " · " + inv.note : ""}`;
    tr.appendChild(meta);
    const td2 = document.createElement("td");
    const rev = document.createElement("button");
    rev.className = "small danger";
    rev.textContent = t("invite_revoke");
    rev.onclick = async () => {
      await api.del(`/api/v1/invites/${inv.code}`, A);
      loadInvites();
    };
    td2.appendChild(rev);
    tr.appendChild(td2);
    table.appendChild(tr);
  }
  box.appendChild(table);
}

async function generateInvite() {
  const body = {
    count: parseInt($("#inv_count").value) || 1,
    max_images: parseInt($("#inv_max").value) || 1,
    build_quota: parseInt($("#inv_quota").value) || 5,
    template: $("#inv_tpl").value || undefined,
    note: $("#inv_note").value.trim(),
    unlocked: $("#inv_profile").value === "free",
  };
  const r = await api.post("/api/v1/invites", body, A);
  for (const inv of r.invites) {
    document.querySelector("main").prepend(
      credentialsCard({ id: inv.code, token: inv.code }, t("invites"))
    );
  }
  loadInvites();
}

async function loadRequests() {
  const box = $("#reqlist");
  if (!box) return;
  const data = await api.get("/api/v1/requests", A);
  const pend = data.requests.filter((r) => r.status === "pending");
  box.innerHTML = "";
  if (!pend.length) {
    box.className = "muted";
    box.textContent = t("requests_none");
    return;
  }
  box.className = "";
  const table = document.createElement("table");
  for (const req of pend) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><b>${req.wanted_name}</b><br><span class="muted mono">${req.contact}</span></td>
      <td class="muted">${req.note || ""}</td>`;
    const td = document.createElement("td");
    const ap = document.createElement("button");
    ap.className = "small primary";
    ap.textContent = t("request_approve_code");
    ap.onclick = async () => {
      const r = await api.post(`/api/v1/requests/${req.id}/approve`, { action: "issue_code" }, A);
      document.querySelector("main").prepend(
        credentialsCard({ id: r.issued.code, token: r.issued.code }, t("invites"))
      );
      loadRequests();
    };
    const rj = document.createElement("button");
    rj.className = "small danger";
    rj.textContent = t("request_reject");
    rj.onclick = async () => {
      await api.post(`/api/v1/requests/${req.id}/reject`, {}, A);
      loadRequests();
    };
    td.append(ap, " ", rj);
    tr.appendChild(td);
    table.appendChild(tr);
  }
  box.appendChild(table);
}

async function createImage() {
  const id = $("#newid").value.trim();
  const fullname = $("#newname").value.trim();
  const template = $("#newtpl").value;
  const unlocked = $("#newprofile").value === "free";
  if (!id) return;
  try {
    const info = await api.post("/api/v1/images", { id, fullname, template, unlocked }, A);
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
  $("#inv_gen").onclick = generateInvite;
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
