// Administração: imagens, criação em massa e credenciais.
import * as api from "/common/api.js";
import { init, t, apply, currentLang } from "/common/i18n.js";

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
    const cam = document.createElement("button");
    cam.className = "small";
    cam.textContent = t("layers_button");
    cam.onclick = () => showImageLayers(img.id);
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
    actions.append(perfil, " ", cam, " ", ver, " ", rot, " ", del);
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
  renderLayerTargets();
  loadInvites();
  loadRequests();
  loadLayerBuilds();
  loadPublish();
}

function renderTemplates() {
  const box = $("#tpllist");
  if (!box) return;
  box.innerHTML = "";
  const table = document.createElement("table");
  for (const tpl of templates) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><a href="#" class="mono tplname">${tpl.name}</a></td>
      <td><span class="pill ${tpl.public ? "ok" : ""}">${
        tpl.public ? t("template_public") : "—"
      }</span></td>`;
    tr.querySelector(".tplname").onclick = (e) => {
      e.preventDefault();
      showLocks(tpl.name);
    };
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

// ---------- camadas adicionais ----------

let layerTimer = null;

function parsePackages(texto) {
  return texto
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function stateLabel(estado) {
  return t(
    { queue: "layer_state_queue", running: "layer_state_running", done: "layer_state_done", failed: "layer_state_failed" }[
      estado
    ] || "layer_state_queue"
  );
}

async function loadLayerBuilds() {
  const box = $("#laylist");
  if (!box) return;
  let data;
  try {
    data = await api.get("/api/v1/layerbuilds", A);
  } catch {
    return;
  }
  if (!data.builds.length) {
    box.className = "muted";
    box.textContent = t("layer_none");
    return;
  }
  box.className = "";
  box.innerHTML = "";
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr><th>${t("layer_name")}</th><th>${t("packages")}</th>
    <th>${t("status")}</th><th></th></tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const b of data.builds) {
    const tr = document.createElement("tr");
    const cor = { done: "ok", failed: "bad", running: "warn" }[b.state] || "";
    tr.innerHTML = `<td><b>${b.name || ""}</b><br><span class="muted mono">${
      b.image || b.template || ""
    }</span></td>
      <td class="muted mono">${(b.packages || []).join(" ")}</td>
      <td><span class="pill ${cor}">${stateLabel(b.state)}</span>${
        b.error ? `<br><span class="muted">${String(b.error).slice(0, 80)}</span>` : ""
      }</td>`;
    const td = document.createElement("td");
    if (b.state === "done" && b.output) {
      const info = document.createElement("div");
      info.className = "muted mono";
      info.style.fontSize = "11px";
      info.textContent = `${b.output.file} · ${Math.round((b.output.size || 0) / 1024)} kB`;
      td.appendChild(info);
      const at = document.createElement("button");
      at.className = "small";
      at.textContent = t("layer_attach_now");
      at.onclick = async () => {
        const alvo = prompt(t("layer_attach_to"), (b.attach_to || []).join(" ") || "");
        if (!alvo) return;
        await api.post(
          `/api/v1/layerbuilds/${b.id}/attach`,
          { image_ids: alvo.split(/[\s,]+/).filter(Boolean) },
          A
        );
        toast(t("layer_attached"));
        loadLayerBuilds();
        loadPublish();
      };
      td.appendChild(at);
    }
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  box.appendChild(table);

  // enquanto houver build em andamento, atualiza sozinho
  const ativo = data.builds.some((b) => b.state === "queue" || b.state === "running");
  clearTimeout(layerTimer);
  if (ativo) layerTimer = setTimeout(loadLayerBuilds, 4000);
}

function renderLayerTargets() {
  const box = $("#lay_images");
  if (!box) return;
  box.innerHTML = "";
  for (const img of images) {
    const row = document.createElement("label");
    row.className = "list-item";
    row.innerHTML = `<input type="checkbox" value="${img.id}"><span class="grow mono">${img.id}</span>
      <span class="muted">${img.fullname || ""}</span>`;
    box.appendChild(row);
  }
  const sel = $("#layi_img");
  if (sel) {
    sel.innerHTML = "";
    for (const img of images) {
      const o = document.createElement("option");
      o.value = o.textContent = img.id;
      sel.appendChild(o);
    }
  }
  const tsel = $("#lay_tpl");
  if (tsel) {
    tsel.innerHTML = "";
    for (const tpl of templates) {
      const o = document.createElement("option");
      o.value = o.textContent = tpl.name;
      tsel.appendChild(o);
    }
  }
}

async function buildLayerFromTemplate() {
  const name = $("#lay_name").value.trim();
  const template = $("#lay_tpl").value;
  const packages = parsePackages($("#lay_pkgs").value);
  const attach_to = [...$("#lay_images").querySelectorAll("input:checked")].map((i) => i.value);
  if (!name || !packages.length) return;
  try {
    await api.post("/api/v1/layerbuilds", { name, template, packages, attach_to }, A);
    $("#lay_name").value = $("#lay_pkgs").value = "";
    toast(t("build_queued"));
    loadLayerBuilds();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function buildLayerForImage() {
  const image = $("#layi_img").value;
  const name = $("#layi_name").value.trim();
  const packages = parsePackages($("#layi_pkgs").value);
  if (!image || !name || !packages.length) return;
  try {
    await api.post(`/api/v1/images/${image}/layerbuilds`, { name, packages }, A);
    $("#layi_name").value = $("#layi_pkgs").value = "";
    toast(t("build_queued"));
    loadLayerBuilds();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function showImageLayers(image) {
  const [builds, layers] = await Promise.all([
    api.get(`/api/v1/images/${image}/layerbuilds`, A),
    api.get(`/api/v1/images/${image}/layers`, A),
  ]);
  const box = document.createElement("div");
  box.className = "detail";
  const inner = document.createElement("div");
  inner.innerHTML = `<h2>${t("layer_of_image")}: <span class="mono">${image}</span></h2>`;
  const lista = document.createElement("table");
  for (const c of layers.extra) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="mono">${c.file}</td><td class="muted mono">${(c.cdn_url || "").slice(0, 60)}</td>`;
    const td = document.createElement("td");
    const rm = document.createElement("button");
    rm.className = "small danger";
    rm.textContent = t("layer_remove");
    rm.onclick = async () => {
      await api.del(`/api/v1/images/${image}/layers/${c.file}`, A);
      box.remove();
      showImageLayers(image);
    };
    td.appendChild(rm);
    tr.appendChild(td);
    lista.appendChild(tr);
  }
  if (!layers.extra.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = t("layer_none");
    inner.appendChild(p);
  } else {
    inner.appendChild(lista);
  }
  const hist = document.createElement("p");
  hist.className = "muted";
  hist.textContent = `${builds.used}${builds.quota ? "/" + builds.quota : ""} builds`;
  inner.appendChild(hist);
  const fechar = document.createElement("button");
  fechar.textContent = t("close");
  fechar.onclick = () => box.remove();
  inner.appendChild(fechar);
  box.appendChild(inner);
  box.onclick = (e) => e.target === box && box.remove();
  document.body.appendChild(box);
}

// ---------- publicação ----------

async function loadPublish() {
  const box = $("#publist");
  if (!box) return;
  let data;
  try {
    data = await api.get("/api/v1/publish", A);
  } catch {
    return;
  }
  $("#pub_info").textContent = data.enabled
    ? `${data.host}`
    : t("publish_disabled_warn");
  if (!data.files.length) {
    box.className = "muted";
    box.textContent = t("publish_none");
    return;
  }
  box.className = "";
  box.innerHTML = "";
  const table = document.createElement("table");
  for (const f of data.files) {
    const cor = { done: "ok", failed: "bad" }[f.status] || "";
    const tr = document.createElement("tr");
    // chaves explícitas: montar o nome da chave em tempo de execução esconde
    // a tradução do verificador de i18n
    const rotulo =
      f.status === "done"
        ? t("publish_status_done")
        : f.status === "failed"
          ? t("publish_status_failed")
          : t("publish_status_disabled");
    tr.innerHTML = `<td class="mono">${f.file}</td>
      <td><span class="pill ${cor}">${rotulo}</span></td>
      <td class="muted mono">${(f.url || f.error || "").slice(0, 60)}</td>`;
    table.appendChild(tr);
  }
  box.appendChild(table);
}

// ---------- cadeados por campo (template) ----------

async function showLocks(template) {
  const box = $("#lockpanel");
  box.innerHTML = "";
  const data = await api.get(`/api/v1/templates/${template}/schema`, A);
  const card = document.createElement("div");
  card.innerHTML = `<h3 style="margin:0 0 4px">${t("locks_title")} — <span class="mono">${template}</span></h3>
    <p class="help muted">${t("locks_help")}</p>`;
  const table = document.createElement("table");
  const estado = {};
  for (const f of data.fields) {
    estado[f.key] = f.locked;
    const tr = document.createElement("tr");
    const td0 = document.createElement("td");
    td0.innerHTML = `<span class="mono">${f.key}</span><br><span class="muted">${tr_(f.label)}</span>`;
    const td1 = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "small";
    const pinta = () => {
      btn.textContent = estado[f.key] ? `🔒 ${t("field_locked")}` : `🔓 ${t("field_free")}`;
      btn.className = "small" + (estado[f.key] ? " danger" : "");
    };
    btn.onclick = () => {
      estado[f.key] = !estado[f.key];
      pinta();
    };
    pinta();
    td1.appendChild(btn);
    tr.append(td0, td1);
    table.appendChild(tr);
  }
  card.appendChild(table);
  const salvar = document.createElement("button");
  salvar.className = "primary";
  salvar.style.marginTop = "10px";
  salvar.textContent = t("locks_save");
  salvar.onclick = async () => {
    await api.put(`/api/v1/templates/${template}/schema/locks`, { locks: estado }, A);
    toast(t("locks_saved"));
  };
  card.appendChild(salvar);
  box.appendChild(card);
}

// rótulo do schema é {pt,en,es}
function tr_(label) {
  if (!label) return "";
  if (typeof label === "string") return label;
  return label[currentLang()] || label.en || label.pt || "";
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
    const wallpaper_locked = $("#newwalllock").checked;
    const info = await api.post(
      "/api/v1/images",
      { id, fullname, template, unlocked, wallpaper_locked },
      A
    );
    // wallpaper opcional já na criação: sobe logo depois que a imagem existe
    const arquivo = $("#newwall").files[0];
    if (arquivo) {
      $("#createstatus").textContent = t("uploading");
      const fd = new FormData();
      fd.append("file", arquivo);
      await api.request("PUT", `/api/v1/images/${id}/wallpaper`, { raw: fd, kind: "admin" });
      $("#newwall").value = "";
    }
    $("#createstatus").textContent = "";
    document.querySelector("main").prepend(credentialsCard(info));
    $("#newid").value = $("#newname").value = "";
    $("#newwalllock").checked = false;
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
  $("#lay_build").onclick = buildLayerFromTemplate;
  $("#layi_build").onclick = buildLayerForImage;
  $("#pub_retry").onclick = async () => {
    const r = await api.post("/api/v1/publish/retry", {}, A);
    toast(`${r.ok}/${r.retried}`);
    loadPublish();
  };
  $("#ltab_tpl").onclick = () => {
    $("#ltab_tpl").classList.add("on");
    $("#ltab_img").classList.remove("on");
    $("#lpane_tpl").classList.remove("hidden");
    $("#lpane_img").classList.add("hidden");
  };
  $("#ltab_img").onclick = () => {
    $("#ltab_img").classList.add("on");
    $("#ltab_tpl").classList.remove("on");
    $("#lpane_img").classList.remove("hidden");
    $("#lpane_tpl").classList.add("hidden");
  };
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
