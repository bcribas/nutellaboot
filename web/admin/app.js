// Administração: imagens, criação em massa e credenciais.
import * as api from "/common/api.js";
import { init, t, apply, currentLang } from "/common/i18n.js";
import { usbBlock } from "/common/usb.js";

const $ = (s) => document.querySelector(s);
const A = { kind: "admin" };
let images = [];
let modelos = [];
let eu = null;
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
  // o pendrive é o único jeito de a máquina ligar: sai junto das credenciais,
  // e não escondido numa tela que ninguém sabe que existe
  if (info.token && info.machine_key) card.appendChild(usbBlock(info.id));
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
      <td class="muted">${img.model || ""}</td>
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
      await api.patch(`/api/v1/site-images/${img.id}`, { unlocked: !livre }, A);
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
      const cred = await api.get(`/api/v1/site-images/${img.id}/credentials`, A);
      document.querySelector("main").prepend(credentialsCard(cred, t("view_credentials")));
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    const rot = document.createElement("button");
    rot.className = "small";
    rot.textContent = t("rotate_token");
    rot.onclick = async () => {
      const r = await api.post(`/api/v1/site-images/${img.id}/token/rotate`, undefined, A);
      document.querySelector("main").prepend(
        credentialsCard({ id: img.id, token: r.token }, t("rotate_token"))
      );
    };
    const del = document.createElement("button");
    del.className = "small danger";
    del.textContent = t("delete");
    del.onclick = async () => {
      if (!confirm(t("confirm_delete", { id: img.id }))) return;
      await api.del(`/api/v1/site-images/${img.id}`, A);
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
  eu = await api.get("/api/v1/whoami", A);
  aplicarPerfil();

  const [imgs, mods] = await Promise.all([
    api.get("/api/v1/site-images", A),
    api.get("/api/v1/models", A),
  ]);
  images = imgs.images;
  modelos = mods.models;

  // derivar site-image só faz sentido de um modelo com camada; o que não tem
  // continua listado (para receber camadas), mas fora dos selects de criação
  preencherSelect($("#newtpl"), modelos.filter((m) => m.layers > 0));
  preencherSelect($("#mod_from"), modelos, { vazio: t("model_from_blank") });
  preencherSelect($("#lay_tpl"), modelos.filter((m) => m.can_manage));
  // modelo opcional do convite (vazio = a pessoa escolhe entre os públicos)
  if ($("#inv_tpl")) preencherSelect($("#inv_tpl"), modelos.filter((m) => m.public), { vazio: "—" });

  renderImages();
  renderModels();
  renderLayerTargets();
  if (ehAdmin()) {
    loadInvites();
    loadRequests();
  }
  loadLayerBuilds();
  if (ehAdmin()) {
    loadUsb();
    loadPublish();
  }
}

function ehAdmin() {
  return !eu || eu.kind === "admin";
}

function preencherSelect(sel, lista, { vazio } = {}) {
  if (!sel) return;
  const antes = sel.value;
  sel.innerHTML = vazio === undefined ? "" : `<option value="">${vazio}</option>`;
  for (const m of lista) {
    const o = document.createElement("option");
    o.value = m.name;
    o.textContent = m.description ? `${m.name} — ${m.description}` : m.name;
    sel.appendChild(o);
  }
  if (antes && lista.some((m) => m.name === antes)) sel.value = antes;
}

// Sub-admin não vê convites, pedidos, publicação nem criação em massa: são
// operações globais. Esconder é mais honesto que deixar clicar e tomar 401.
function aplicarPerfil() {
  const admin = ehAdmin();
  for (const el of document.querySelectorAll("[data-admin-only]")) {
    el.classList.toggle("hidden", !admin);
  }
  $("#who_label").textContent = eu.label || "";
  $("#who_kind").textContent = admin ? t("who_admin") : t("who_subadmin");
  $("#who_kind").className = "pill" + (admin ? " ok" : "");
  $("#who_help").textContent = admin ? t("who_admin_help") : t("who_subadmin_help");
  $("#who_quotas").textContent = admin
    ? ""
    : [
        `${t("models_section")}: ${eu.usage.models}/${eu.quotas.models}`,
        `${t("images")}: ${eu.usage.site_images}/${eu.quotas.site_images}`,
      ].join("   ·   ");
}

function renderModels() {
  const box = $("#modlist");
  if (!box) return;
  box.innerHTML = "";
  box.className = "";
  if (!modelos.length) {
    box.className = "muted";
    box.textContent = t("models_none");
    return;
  }
  const table = document.createElement("table");
  for (const m of modelos) {
    const tr = document.createElement("tr");
    const nome = document.createElement("td");
    const a = document.createElement("a");
    a.href = "#";
    a.className = "mono";
    a.textContent = m.name;
    a.onclick = (e) => {
      e.preventDefault();
      showModel(m);
    };
    nome.appendChild(a);
    if (m.description) {
      const d = document.createElement("div");
      d.className = "muted";
      d.textContent = m.description;
      nome.appendChild(d);
    }

    const info = document.createElement("td");
    info.className = "muted";
    info.textContent = `${m.layers} ${t("model_layers_count")} · ${m.used_by} ${t("model_used_by")}`;

    const marca = document.createElement("td");
    if (m.public) marca.innerHTML = `<span class="pill ok">${t("template_public")}</span>`;
    else if (!m.mine) marca.innerHTML = `<span class="pill">${t("model_of_admin")}</span>`;

    const acoes = document.createElement("td");
    acoes.style.textAlign = "right";
    if (ehAdmin()) {
      const pub = document.createElement("button");
      pub.className = "small";
      pub.textContent = m.public ? t("make_private") : t("make_public");
      pub.onclick = async () => {
        await api.patch(`/api/v1/models/${m.name}`, { public: !m.public }, A);
        load();
      };
      acoes.append(pub, " ");
    }
    const dup = document.createElement("button");
    dup.className = "small";
    dup.textContent = t("model_duplicate");
    dup.onclick = () => {
      $("#mod_from").value = m.name;
      $("#mod_name").focus();
      toast(t("model_duplicate_hint"));
    };
    acoes.append(dup, " ");
    if (m.can_manage) {
      const del = document.createElement("button");
      del.className = "small danger";
      del.textContent = t("delete");
      del.onclick = () => removeModel(m);
      acoes.appendChild(del);
    }

    tr.append(nome, info, marca, acoes);
    table.appendChild(tr);
  }
  box.appendChild(table);
}

async function createModel() {
  const nome = $("#mod_name").value.trim();
  if (!nome) return;
  try {
    const criado = await api.post(
      "/api/v1/models",
      {
        name: nome,
        description: $("#mod_desc").value.trim(),
        from: $("#mod_from").value || undefined,
      },
      A,
    );
    $("#mod_name").value = $("#mod_desc").value = "";
    toast(criado.warning ? `${t("model_created")} — ${t("model_empty_warning")}` : t("model_created"));
    await load();
    showModel(modelos.find((m) => m.name === criado.name) || { name: criado.name, can_manage: true });
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function removeModel(m) {
  if (!confirm(t("model_delete_confirm").replace("{n}", m.name))) return;
  try {
    await api.del(`/api/v1/models/${m.name}`, A);
    $("#modpanel").innerHTML = "";
    load();
  } catch (e) {
    // 409 = tem site-image usando; a mensagem do servidor diz quais
    toast(`${t("error")}: ${e.message}`, true);
  }
}

// ---------- painel de um modelo: camadas + formulário ----------

async function showModel(m) {
  const box = $("#modpanel");
  box.innerHTML = "";
  const card = document.createElement("div");
  card.className = "card";
  card.style.borderColor = "var(--accent)";
  card.innerHTML = `<h3 style="margin:0 0 4px">${t("model_panel_title")} — <span class="mono">${m.name}</span></h3>`;
  if (!m.can_manage) {
    const aviso = document.createElement("p");
    aviso.className = "help muted";
    aviso.textContent = t("model_readonly");
    card.appendChild(aviso);
  }
  box.appendChild(card);

  const modelo = await api.get(`/api/v1/models/${m.name}`, A);
  card.appendChild(layersEditor(m, modelo.layers || []));
  card.appendChild(wallpaperEditor(m, modelo));
  card.appendChild(await locksEditor(m));
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

const ROLE_LABEL = {
  base: "role_base",
  telemetry: "role_telemetry",
  wifi: "role_wifi",
  extra: "role_extra",
};

function layersEditor(m, layers) {
  const wrap = document.createElement("div");
  wrap.innerHTML = `<h4 style="margin:14px 0 2px">${t("model_layers")}</h4>
    <p class="help muted">${t("model_layers_help")}</p>`;
  const table = document.createElement("table");

  layers.forEach((c, idx) => {
    const tr = document.createElement("tr");
    const papel = c.role || "extra";
    tr.innerHTML = `<td style="width:32px" class="muted">${idx + 1}</td>
      <td class="mono">${c.file}</td>
      <td><span class="pill ${papel === "base" ? "warn" : ""}">${t(ROLE_LABEL[papel] || "role_extra")}</span></td>
      <td class="muted mono">${(c.md5 || "").slice(0, 10)}…</td>`;
    const acoes = document.createElement("td");
    acoes.style.textAlign = "right";
    if (m.can_manage) {
      const sobe = document.createElement("button");
      sobe.className = "small";
      sobe.textContent = "↑";
      sobe.disabled = idx === 0;
      sobe.onclick = async () => {
        const ordem = layers.map((x) => x.file);
        [ordem[idx - 1], ordem[idx]] = [ordem[idx], ordem[idx - 1]];
        await api.put(`/api/v1/models/${m.name}/layers/order`, { files: ordem }, A);
        showModel(m);
      };
      const del = document.createElement("button");
      del.className = "small danger";
      del.textContent = t("remove");
      del.onclick = async () => {
        await api.del(`/api/v1/models/${m.name}/layers/${encodeURIComponent(c.file)}`, A);
        showModel(m);
      };
      acoes.append(sobe, " ", del);
    }
    tr.appendChild(acoes);
    table.appendChild(tr);
  });
  if (!layers.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="5" class="muted">${t("model_empty_warning")}</td>`;
    table.appendChild(tr);
  }
  wrap.appendChild(table);

  if (m.can_manage) {
    const linha = document.createElement("div");
    linha.className = "actions";
    linha.style.marginTop = "10px";
    linha.style.flexWrap = "wrap";
    const sel = document.createElement("select");
    sel.style.maxWidth = "320px";
    const arquivo = document.createElement("input");
    arquivo.placeholder = "base.squashfs";
    arquivo.style.maxWidth = "200px";
    const md5 = document.createElement("input");
    md5.placeholder = "md5";
    md5.style.maxWidth = "260px";
    md5.className = "mono";
    const papelSel = document.createElement("select");
    papelSel.style.maxWidth = "150px";
    for (const r of ["extra", "base", "telemetry", "wifi"]) {
      const o = document.createElement("option");
      o.value = r;
      o.textContent = t(ROLE_LABEL[r]);
      papelSel.appendChild(o);
    }

    const add = document.createElement("button");
    add.className = "primary";
    add.textContent = t("model_layer_add");

    api.get("/api/v1/layers/catalog", A).then((cat) => {
      sel.innerHTML = `<option value="">${t("model_layer_manual")}</option>`;
      for (const c of cat.layers) {
        const o = document.createElement("option");
        o.value = JSON.stringify({ file: c.file, md5: c.md5, cdn_url: c.cdn_url, role: c.role });
        o.textContent = `${c.file} (${c.used_by.join(", ")})`;
        sel.appendChild(o);
      }
    });
    sel.onchange = () => {
      const escolhido = sel.value ? JSON.parse(sel.value) : null;
      arquivo.value = escolhido ? escolhido.file : "";
      md5.value = escolhido ? escolhido.md5 : "";
      if (escolhido?.role) papelSel.value = escolhido.role;
    };
    add.onclick = async () => {
      const corpo = sel.value
        ? JSON.parse(sel.value)
        : { file: arquivo.value.trim(), md5: md5.value.trim() };
      corpo.role = papelSel.value;
      // trocar a base substitui a que já está lá: duas bases no mesmo modelo
      // fazem a máquina baixar duas raízes e montá-las sobrepostas
      if (papelSel.value === "base") corpo.replace_role = "base";
      try {
        await api.post(`/api/v1/models/${m.name}/layers`, corpo, A);
        showModel(m);
        load();
      } catch (e) {
        toast(`${t("error")}: ${e.message}`, true);
      }
    };
    linha.append(sel, arquivo, md5, papelSel, add);
    wrap.appendChild(linha);
  }
  return wrap;
}

async function locksEditor(m) {
  const wrap = document.createElement("div");
  wrap.innerHTML = `<h4 style="margin:18px 0 2px">${t("locks_title")}</h4>
    <p class="help muted">${t("locks_help")}</p>`;
  const data = await api.get(`/api/v1/models/${m.name}/schema`, A);
  const table = document.createElement("table");
  const estado = {};
  const padrao = {};
  const original = {};
  for (const f of data.fields) {
    estado[f.key] = f.locked;
    padrao[f.key] = f.default;
    original[f.key] = JSON.stringify(f.default ?? null);
    const tr = document.createElement("tr");
    const td0 = document.createElement("td");
    td0.innerHTML = `<span class="mono">${f.key}</span><br><span class="muted">${tr_(f.label)}</span>`;

    // O valor padrão importa DUAS vezes: é o que a sede vê ao abrir o
    // formulário, e — quando o campo está trancado — é o valor que vai para
    // TODA máquina da sala, sem ninguém poder mudar.
    const td1 = document.createElement("td");
    const ed = editorDePadrao(f, (v) => {
      padrao[f.key] = v;
    });
    ed.disabled = !m.can_manage;
    td1.appendChild(ed);

    const td2 = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "small";
    btn.disabled = !m.can_manage;
    const pinta = () => {
      btn.textContent = estado[f.key] ? `🔒 ${t("field_locked")}` : `🔓 ${t("field_free")}`;
      btn.className = "small" + (estado[f.key] ? " danger" : "");
    };
    btn.onclick = () => {
      estado[f.key] = !estado[f.key];
      pinta();
    };
    pinta();
    td2.appendChild(btn);
    tr.append(td0, td1, td2);
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  if (m.can_manage) {
    const salvar = document.createElement("button");
    salvar.className = "primary";
    salvar.style.marginTop = "10px";
    salvar.textContent = t("locks_save");
    salvar.onclick = async () => {
      try {
        // um PATCH por campo ALTERADO: o servidor valida o padrão pelo mesmo
        // caminho que valida o que a sede digita, e mandar todos faria uma
        // recusa de um campo parecer recusa de tudo
        for (const f of data.fields) {
          if (JSON.stringify(padrao[f.key] ?? null) === original[f.key]) continue;
          await api.patch(
            `/api/v1/models/${m.name}/schema/fields/${encodeURIComponent(f.key)}`,
            { default: padrao[f.key] },
            A,
          );
          original[f.key] = JSON.stringify(padrao[f.key] ?? null);
        }
        await api.put(`/api/v1/models/${m.name}/schema/locks`, { locks: estado }, A);
        toast(t("locks_saved"));
      } catch (e) {
        toast(`${t("error")}: ${e.message}`, true);
      }
    };
    wrap.appendChild(salvar);
  }
  return wrap;
}

// O controle do valor padrão, do tipo do campo. Uma caixa de texto para tudo
// deixaria alguém digitar "sim" num campo booleano e só descobrir na sala.
function editorDePadrao(f, aoMudar) {
  if (f.type === "bool") {
    const s = document.createElement("select");
    for (const [v, rot] of [[true, t("yes")], [false, t("no")]]) {
      const o = document.createElement("option");
      o.value = String(v);
      o.textContent = rot;
      s.appendChild(o);
    }
    s.value = String(!!f.default);
    s.onchange = () => aoMudar(s.value === "true");
    return s;
  }
  if (f.type === "select") {
    const s = document.createElement("select");
    for (const op of f.options || []) {
      const o = document.createElement("option");
      o.value = typeof op === "string" ? op : op.value;
      o.textContent = tr_(typeof op === "string" ? op : op.label) || o.value;
      s.appendChild(o);
    }
    s.value = f.default ?? "";
    s.onchange = () => aoMudar(s.value);
    return s;
  }
  const i = document.createElement("input");
  i.type = f.type === "int" ? "number" : "text";
  i.className = "mono";
  i.style.width = "18ch";
  // lista vira texto separado por vírgula, que é o mesmo separador do stuff
  i.value = Array.isArray(f.default) ? f.default.join(",") : (f.default ?? "");
  i.oninput = () => {
    if (f.type === "list") aoMudar(i.value ? i.value.split(",").map((s) => s.trim()) : []);
    else if (f.type === "int") aoMudar(i.value === "" ? null : Number(i.value));
    else aoMudar(i.value);
  };
  return i;
}

// Papel de parede do MODELO: definido uma vez pela organização e herdado por
// toda sede dele. Com a trava, nenhuma delas troca.
function wallpaperEditor(m, modelo) {
  const wrap = document.createElement("div");
  wrap.innerHTML = `<h4 style="margin:18px 0 2px">${t("model_wallpaper")}</h4>
    <p class="help muted">${t("model_wallpaper_help")}</p>`;

  const img = document.createElement("img");
  img.style.maxWidth = "260px";
  img.style.borderRadius = "6px";
  img.alt = "";
  img.src = `/api/v1/models/${encodeURIComponent(m.name)}/wallpaper?v=${Date.now()}`;
  img.onerror = () => {
    img.remove();
  };
  wrap.appendChild(img);

  const acoes = document.createElement("div");
  acoes.className = "actions";
  acoes.style.marginTop = "10px";

  const file = document.createElement("input");
  file.type = "file";
  file.accept = "image/png,image/jpeg";
  file.hidden = true;
  const enviar = document.createElement("button");
  enviar.className = "small";
  enviar.textContent = t("wallpaper_choose");
  enviar.disabled = !m.can_manage;
  enviar.onclick = () => file.click();
  file.onchange = async () => {
    if (!file.files[0]) return;
    const fd = new FormData();
    fd.append("file", file.files[0]);
    try {
      await api.request("PUT", `/api/v1/models/${encodeURIComponent(m.name)}/wallpaper`, {
        raw: fd,
        kind: "admin",
      });
      toast(t("saved"));
      showModel(m);
    } catch (e) {
      toast(`${t("error")}: ${e.message}`, true);
    }
  };

  const remover = document.createElement("button");
  remover.className = "small danger";
  remover.textContent = t("wallpaper_remove");
  remover.disabled = !m.can_manage;
  remover.onclick = async () => {
    await api.del(`/api/v1/models/${encodeURIComponent(m.name)}/wallpaper`, A);
    showModel(m);
  };

  const trava = document.createElement("button");
  trava.className = "small";
  trava.disabled = !m.can_manage;
  let travado = !!modelo.wallpaper_locked;
  const pinta = () => {
    trava.textContent = travado ? `🔒 ${t("model_wallpaper_locked")}` : `🔓 ${t("model_wallpaper_free")}`;
    trava.className = "small" + (travado ? " danger" : "");
  };
  trava.onclick = async () => {
    travado = !travado;
    pinta();
    await api.patch(`/api/v1/models/${encodeURIComponent(m.name)}`, { wallpaper_locked: travado }, A);
    toast(t("saved"));
  };
  pinta();

  acoes.append(file, enviar, remover, trava);
  wrap.appendChild(acoes);
  return wrap;
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
    meta.textContent = `${inv.remaining} ${t("invite_remaining")} · ${perfil}${inv.model ? " · " + inv.model : ""}${inv.note ? " · " + inv.note : ""}`;
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
    model: $("#inv_tpl").value || undefined,
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
      b.image || b.model || ""
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
}

async function buildLayerFromTemplate() {
  const name = $("#lay_name").value.trim();
  const model = $("#lay_tpl").value;
  const packages = parsePackages($("#lay_pkgs").value);
  const attach_to = [...$("#lay_images").querySelectorAll("input:checked")].map((i) => i.value);
  if (!name || !packages.length) return;
  try {
    await api.post("/api/v1/layerbuilds", { name, model, packages, attach_to }, A);
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
    await api.post(`/api/v1/site-images/${image}/layerbuilds`, { name, packages }, A);
    $("#layi_name").value = $("#layi_pkgs").value = "";
    toast(t("build_queued"));
    loadLayerBuilds();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function showImageLayers(image) {
  // sem este try, uma das duas chamadas falhando deixava a promessa sem dono:
  // o botão não abria painel nenhum e não dizia por quê
  let builds, layers;
  try {
    [builds, layers] = await Promise.all([
      api.get(`/api/v1/site-images/${image}/layerbuilds`, A),
      api.get(`/api/v1/site-images/${image}/layers`, A),
    ]);
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
    return;
  }
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
      await api.del(`/api/v1/site-images/${image}/layers/${c.file}`, A);
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

// ---------- pendrive ----------

let usbTimer = null;

function usbEstadoTexto(e) {
  // chaves explícitas: montar o nome em tempo de execução esconde a tradução
  // do verificador de i18n
  if (e.status === "building") return t("usb_building");
  if (e.status === "failed") return t("usb_failed");
  if (e.status === "done") return t("usb_published");
  return t("usb_not_generated");
}

async function loadUsb() {
  const box = $("#usbstate");
  if (!box) return;
  let d;
  try {
    d = await api.get("/api/v1/usb", A);
  } catch {
    return;
  }
  box.className = "";
  box.innerHTML = "";

  // 1. o par kernel+initrd, que é compartilhado por todas as sedes e é o único
  // passo do sistema que precisa de root
  const kernel = document.createElement("p");
  if (d.kernel.ok) {
    const v = d.kernel.files["vmlinuz"];
    const i = d.kernel.files["initrd.img"];
    const data = new Date(i.mtime * 1000).toLocaleString();
    kernel.className = "muted";
    kernel.textContent = `${t("usb_kernel")}: vmlinuz ${Math.round(v.size / 1048576)} MB · initrd.img ${Math.round(i.size / 1048576)} MB · ${data}`;
  } else {
    kernel.className = "warn";
    kernel.innerHTML = `${t("usb_no_kernel")}<br><code>${d.kernel.hint}</code>`;
  }
  box.appendChild(kernel);

  // 2. a imagem genérica: uma só, para todas as sedes
  const g = document.createElement("p");
  g.innerHTML =
    `<strong>${t("usb_generic_image")}</strong>: ` +
    (d.generic.status === "done"
      ? `<span class="mono">${d.generic.file}</span> · ${Math.round((d.generic.size || 0) / 1048576)} MB · ` +
        (d.generic.published
          ? `<span class="pill ok">${t("usb_published")}</span> <span class="muted mono">${d.generic.public_url}</span>`
          : `<span class="muted">${t("usb_local")}</span>`)
      : `<span class="muted">${usbEstadoTexto(d.generic)}</span>`);
  box.appendChild(g);
  if (d.generic.error) {
    const e = document.createElement("p");
    e.className = "muted small";
    e.textContent = d.generic.error.slice(0, 200);
    box.appendChild(e);
  }

  if (!d.auto_generate) {
    const aviso = document.createElement("p");
    aviso.className = "muted small";
    aviso.textContent = t("usb_auto_off");
    box.appendChild(aviso);
  }

  // 3. o que cada sede tem
  const titulo = document.createElement("p");
  titulo.className = "muted";
  titulo.textContent = t("usb_per_site");
  box.appendChild(titulo);

  if (!d.images.length) {
    const vazio = document.createElement("p");
    vazio.className = "muted";
    vazio.textContent = t("usb_none");
    box.appendChild(vazio);
  } else {
    const table = document.createElement("table");
    for (const img of d.images) {
      const cor = { done: "ok", failed: "bad", building: "warn" }[img.status] || "";
      const tr = document.createElement("tr");
      const aviso = img.stale
        ? `<br><span class="warn small">${t("usb_stale_boot_key")}</span>`
        : "";
      tr.innerHTML = `<td class="mono">${img.id}</td>
        <td><span class="pill ${cor}">${usbEstadoTexto(img)}</span>${aviso}</td>`;
      const td = document.createElement("td");
      if (img.status === "done") {
        const a = document.createElement("a");
        a.className = "btn small";
        // a rota decide entre redirecionar e compactar na hora
        a.href = api.usbImageUrl(img.id);
        a.setAttribute("download", "");
        a.textContent = t("usb_download");
        td.appendChild(a);
      }
      const gerar = document.createElement("button");
      gerar.className = "small";
      gerar.textContent = img.status === "done" ? t("usb_regenerate") : t("usb_generate");
      gerar.onclick = async () => {
        gerar.disabled = true;
        try {
          await api.post(`/api/v1/site-images/${img.id}/usb`, {}, A);
        } finally {
          loadUsb();
        }
      };
      td.append(" ", gerar);
      tr.appendChild(td);
      table.appendChild(tr);
    }
    box.appendChild(table);
  }

  // enquanto algo está sendo gerado, volta a perguntar; parado, não bate no
  // servidor (mesmo padrão dos builds de camada)
  clearTimeout(usbTimer);
  const ativo =
    d.generic.status === "building" || d.images.some((i) => i.status === "building");
  if (ativo) usbTimer = setTimeout(loadUsb, 4000);
}

async function buildGenericUsb() {
  $("#usb_info").textContent = t("usb_building");
  try {
    await api.post("/api/v1/usb/generic", {}, A);
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
  $("#usb_info").textContent = "";
  loadUsb();
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
  const model = $("#newtpl").value;
  const unlocked = $("#newprofile").value === "free";
  if (!id) return;
  let info;
  try {
    const wallpaper_locked = $("#newwalllock").checked;
    info = await api.post(
      "/api/v1/site-images",
      { id, fullname, model, unlocked, wallpaper_locked },
      A
    );
  } catch (e) {
    $("#createstatus").textContent = "";
    toast(`${t("error")}: ${e.message}`, true);
    return;
  }

  // Daqui para baixo a imagem JÁ EXISTE, com token e chaves que só aparecem
  // uma vez. O wallpaper falhando (não é PNG, passa de 12 MB) não pode levar o
  // cartão de credenciais junto: antes, quem escolhia um arquivo inválido via
  // só um toast de erro e ia embora achando que nada tinha sido criado.
  let aviso = "";
  const arquivo = $("#newwall").files[0];
  if (arquivo) {
    $("#createstatus").textContent = t("uploading");
    try {
      const fd = new FormData();
      fd.append("file", arquivo);
      await api.request("PUT", `/api/v1/site-images/${id}/wallpaper`, { raw: fd, kind: "admin" });
      $("#newwall").value = "";
    } catch (e) {
      aviso = `${t("wallpaper_upload_failed")}: ${e.message}`;
      toast(aviso, true);
    }
  }
  $("#createstatus").textContent = "";
  const cartao = credentialsCard(info);
  if (aviso) {
    const p = document.createElement("p");
    p.className = "warn";
    p.textContent = aviso;
    cartao.prepend(p);
  }
  document.querySelector("main").prepend(cartao);
  $("#newid").value = $("#newname").value = "";
  $("#newwalllock").checked = false;
  load();
}

async function bulkCreate() {
  const tsv = $("#bulktsv").value.trim();
  if (!tsv) return;
  $("#bulkstatus").textContent = t("loading");
  try {
    lastBulkCsv = await api.request("POST", "/api/v1/site-images/bulk?format=csv", {
      kind: "admin",
      raw: tsv,
      contentType: "text/tab-separated-values",
    });
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

function abrirPainel() {
  $("#login").classList.add("hidden");
  $("#panel").classList.remove("hidden");
  $("#logout").classList.remove("hidden");
  $("#gofrota").classList.remove("hidden");
}

function pedirChave() {
  $("#panel").classList.add("hidden");
  $("#logout").classList.add("hidden");
  $("#gofrota").classList.add("hidden");
  $("#login").classList.remove("hidden");
}

// Troca a chave digitada por um cookie de sessão. Daí em diante o navegador
// manda o cookie sozinho: recarregar a página não pede nada de novo.
async function enter() {
  const chave = $("#key").value.trim();
  if (!chave) return;
  try {
    await api.login(chave);
    $("#key").value = "";
    await load();
    abrirPainel();
  } catch (e) {
    toast(`${t("error")}: ${e.message}`, true);
  }
}

// No carregamento: se já há sessão, entra direto.
//
// A versão anterior chamava enter() aqui, e enter() começava gravando o campo
// de login — vazio num carregamento novo — por cima da credencial guardada.
// Ou seja, a tentativa automática de entrar era exatamente o que deslogava.
async function retomarSessao() {
  try {
    await load();
    abrirPainel();
  } catch (e) {
    // só falta de credencial volta para o login; um erro de rede ou uma
    // seção que falhou não podem derrubar quem já está dentro
    if (e.status === 401) {
      pedirChave();
    } else {
      abrirPainel();
      toast(`${t("error")}: ${e.message}`, true);
    }
  }
}

async function main() {
  await init($("#lang"));
  $("#enter").onclick = enter;
  $("#key").onkeydown = (e) => e.key === "Enter" && enter();
  $("#create").onclick = createImage;
  $("#mod_create").onclick = createModel;
  $("#bulkgo").onclick = bulkCreate;
  $("#bulkcsv").onclick = downloadCsv;
  $("#reload").onclick = load;
  $("#filter").oninput = renderImages;
  $("#inv_gen").onclick = generateInvite;
  $("#lay_build").onclick = buildLayerFromTemplate;
  $("#layi_build").onclick = buildLayerForImage;
  $("#usb_build").onclick = buildGenericUsb;
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
  $("#logout").onclick = async () => {
    try {
      await api.logout();
    } catch {
      /* sessão já podia estar encerrada; o reload mostra o login de qualquer jeito */
    }
    location.reload();
  };
  document.addEventListener("nb3:langchange", () => {
    apply();
    if (eu) aplicarPerfil();
    if (images.length) renderImages();
    if (modelos.length) renderModels();
  });
  await retomarSessao();
}

main();
