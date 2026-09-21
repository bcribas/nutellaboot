// A visão Times: o roster da sede (quem a sede espera) e o vínculo de cada
// time com a máquina. O token da sede alcança todas essas rotas; o MOJ também
// escreve aqui, por isso a edição de uma linha usa o POST (upsert) e nunca
// regrava a lista inteira por baixo dele.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, toast, el, esc } from "/common/ui.js";

const CAMPOS = ["user_id", "name", "display_name", "org_id", "org_name", "country", "seat"];

// user_id -> entrada. O cartão da máquina mostra o NOME do time por aqui: o
// vínculo só guarda o user_id.
export const rosterPorId = new Map();
let logos = [];
let maquinas = [];
let editando = null;

export function nomeDoTime(userId) {
  const e = rosterPorId.get(userId);
  return e ? e.display_name || e.name || userId : "";
}

function base() {
  return `/api/v1/site-images/${encodeURIComponent(api.imageId)}`;
}

export async function carregarRoster() {
  const d = await api.get(`${base()}/roster`);
  rosterPorId.clear();
  for (const e of d.roster || []) rosterPorId.set(e.user_id, e);
  logos = d.logos || [];
  return d;
}

export function informarMaquinas(lista) {
  maquinas = lista;
}

function vinculos() {
  const porTime = new Map();
  for (const m of maquinas) {
    if (m.binding && m.binding.user_id) porTime.set(m.binding.user_id, m);
  }
  return porTime;
}

async function recarregar() {
  await carregarRoster();
  renderTimes();
  document.dispatchEvent(new CustomEvent("nb3:roster-mudou"));
}

function linha(e, porTime) {
  const m = porTime.get(e.user_id);
  const org = e.organization || {};
  const editar = el("button", { class: "small", type: "button" }, t("roster_edit"));
  editar.onclick = () => abrirForm(e);
  const remover = el("button", { class: "small danger", type: "button" }, t("roster_remove"));
  remover.onclick = async () => {
    const aviso = m ? `${t("roster_remove_confirm")}\n${t("roster_remove_bound_warn", { mac: m.mac })}` : t("roster_remove_confirm");
    if (!confirm(aviso)) return;
    try {
      await api.del(`${base()}/roster/${encodeURIComponent(e.user_id)}`);
      await recarregar();
    } catch (err) {
      toast(err.message, true);
    }
  };
  return el("tr", {},
    el("td", { class: "mono" }, e.user_id, e.source === "binding" ? el("span", { class: "pill", title: t("roster_from_binding_help") }, t("roster_from_binding")) : null),
    el("td", {}, el("b", {}, e.name || ""), e.display_name ? el("span", { class: "muted" }, ` ${e.display_name}`) : null),
    el("td", { class: "muted" }, org.name || org.id || "", e.country ? ` · ${e.country}` : ""),
    el("td", { class: "mono muted" }, e.seat || ""),
    el("td", { class: "mono" }, m ? m.mac : el("span", { class: "muted" }, "—")),
    el("td", {}, editar, " ", remover));
}

function renderLogos() {
  const box = $("#ros_logos");
  box.innerHTML = "";
  const orgs = new Map();
  for (const e of rosterPorId.values()) {
    const org = e.organization || {};
    if (org.id) orgs.set(org.id, org.name || org.id);
  }
  if (!orgs.size) {
    box.className = "muted";
    box.textContent = t("roster_logo_none");
    return;
  }
  box.className = "";
  for (const [id, nome] of orgs) {
    const tem = logos.includes(id);
    const img = tem ? el("img", { class: "logothumb", src: api.rosterLogoUrl(api.imageId, id, Date.now()), alt: "" }) : el("span", { class: "muted" }, "—");
    const arquivo = el("input", { type: "file", accept: ".svg,.png,image/svg+xml,image/png" });
    arquivo.onchange = () => enviarLogo(id, arquivo.files[0]);
    box.append(el("div", { class: "logorow" }, img, " ", el("b", {}, nome), " ", el("span", { class: "mono muted" }, id), " ", arquivo));
  }
}

export function renderTimes() {
  const box = $("#ros_table");
  if (!box) return;
  const porTime = vinculos();
  const q = $("#ros_search").value.trim().toLowerCase();
  const soSem = $("#ros_filter").value === "nomachine";
  const lista = [...rosterPorId.values()].filter((e) => {
    if (soSem && porTime.has(e.user_id)) return false;
    if (!q) return true;
    const org = e.organization || {};
    return `${e.user_id} ${e.name} ${e.display_name} ${org.name} ${org.id} ${e.seat}`.toLowerCase().includes(q);
  });
  $("#ros_summary").textContent = t("roster_count", { n: rosterPorId.size, bound: porTime.size });
  box.innerHTML = "";
  if (!rosterPorId.size) {
    box.className = "muted";
    box.append(el("p", {}, t("roster_empty")), el("p", { class: "help" }, t("roster_empty_hint")));
  } else if (!lista.length) {
    box.className = "muted";
    box.textContent = "—";
  } else {
    box.className = "";
    const tabela = el("table", { class: "rostable" },
      el("thead", {}, el("tr", {}, el("th", {}, "user_id"), el("th", {}, t("roster_name")),
        el("th", {}, t("roster_org_name")), el("th", {}, t("roster_seat")), el("th", {}, t("machine")), el("th", {}))));
    const corpo = el("tbody");
    for (const e of lista) corpo.append(linha(e, porTime));
    tabela.append(corpo);
    box.append(tabela);
  }
  renderLogos();
  renderOverview(porTime);
}

function renderOverview(porTime) {
  const semTime = maquinas.filter((m) => !(m.binding && (m.binding.user_id || m.binding.name)));
  const a = $("#bind_noteam");
  a.innerHTML = "";
  a.className = semTime.length ? "" : "muted";
  if (!semTime.length) a.textContent = "—";
  for (const m of semTime) {
    const b = el("button", { class: "small mono", type: "button" }, m.mac);
    b.onclick = () => document.dispatchEvent(new CustomEvent("nb3:abrir-time", { detail: m.mac }));
    a.append(b, " ");
  }
  const semMaq = [...rosterPorId.values()].filter((e) => !porTime.has(e.user_id));
  const b = $("#bind_nomachine");
  b.innerHTML = "";
  b.className = semMaq.length ? "" : "muted";
  if (!semMaq.length) b.textContent = "—";
  for (const e of semMaq) b.append(el("span", { class: "pill" }, e.display_name || e.name || e.user_id), " ");
}

// --- formulário de UM time ---

function abrirForm(e) {
  editando = e ? e.user_id : null;
  $("#ros_form_box").open = true;
  const org = (e && e.organization) || {};
  $("#ros_uid").value = e ? e.user_id : "";
  $("#ros_uid").readOnly = Boolean(e);
  $("#ros_name").value = e ? e.name || "" : "";
  $("#ros_display").value = e ? e.display_name || "" : "";
  $("#ros_orgid").value = org.id || "";
  $("#ros_orgname").value = org.name || "";
  $("#ros_country").value = e ? e.country || "" : "";
  $("#ros_seat").value = e ? e.seat || "" : "";
  $("#ros_uid").focus();
}

function lerForm() {
  const org = {};
  if ($("#ros_orgid").value.trim()) org.id = $("#ros_orgid").value.trim();
  if ($("#ros_orgname").value.trim()) org.name = $("#ros_orgname").value.trim();
  return {
    user_id: $("#ros_uid").value.trim(),
    name: $("#ros_name").value.trim(),
    display_name: $("#ros_display").value.trim(),
    organization: org,
    country: $("#ros_country").value.trim(),
    seat: $("#ros_seat").value.trim(),
  };
}

async function salvarForm() {
  const e = lerForm();
  if (!e.user_id) return toast(t("roster_need_user_id"), true);
  try {
    await api.post(`${base()}/roster`, e);
    toast(t("roster_saved"));
    abrirForm(null);
    $("#ros_form_box").open = false;
    await recarregar();
  } catch (err) {
    toast(err.message, true);
  }
}

// --- importar e exportar ---

// Aceita JSON (lista, ou {roster:[…]}) e CSV/TSV com ou sem cabeçalho.
// Colunas: user_id, name, display_name, org_id, org_name, country, seat
// (também organization.id / organization.name).
export function interpretar(texto) {
  const txt = texto.trim();
  if (!txt) return [];
  if (txt.startsWith("[") || txt.startsWith("{")) {
    const j = JSON.parse(txt);
    const lista = Array.isArray(j) ? j : j.roster || [];
    return lista.map(normaliza);
  }
  const linhas = txt.split(/\r?\n/).filter((l) => l.trim());
  const sep = linhas[0].includes("\t") ? "\t" : linhas[0].includes(";") ? ";" : ",";
  let cabecalho = CAMPOS;
  const primeira = linhas[0].split(sep).map((c) => c.trim().replace(/^"|"$/g, ""));
  if (primeira.includes("user_id")) {
    cabecalho = primeira.map((c) => c.replace("organization.id", "org_id").replace("organization.name", "org_name"));
    linhas.shift();
  }
  return linhas.map((l) => {
    const cols = l.split(sep).map((c) => c.trim().replace(/^"|"$/g, ""));
    const obj = {};
    cabecalho.forEach((c, i) => (obj[c] = cols[i] || ""));
    return normaliza(obj);
  });
}

function normaliza(o) {
  const org = { ...(o.organization || {}) };
  if (o.org_id) org.id = o.org_id;
  if (o.org_name) org.name = o.org_name;
  return {
    user_id: String(o.user_id || "").trim(),
    name: String(o.name || ""),
    display_name: String(o.display_name || ""),
    organization: org,
    country: String(o.country || ""),
    seat: String(o.seat || ""),
  };
}

function previa() {
  let lista;
  try {
    lista = interpretar($("#ros_paste").value);
  } catch (e) {
    $("#ros_preview").textContent = `${t("error")}: ${e.message}`;
    return [];
  }
  const validas = lista.filter((e) => e.user_id);
  const novas = validas.filter((e) => !rosterPorId.has(e.user_id)).length;
  $("#ros_preview").textContent = lista.length
    ? t("roster_preview_counts", { novas, alteradas: validas.length - novas, invalidas: lista.length - validas.length })
    : "";
  return validas;
}

async function mesclar() {
  const lista = previa();
  if (!lista.length) return;
  let ok = 0;
  for (const e of lista) {
    try {
      await api.post(`${base()}/roster`, e);
      ok++;
    } catch (err) {
      toast(`${e.user_id}: ${err.message}`, true);
    }
  }
  toast(t("roster_merged", { n: ok }));
  $("#ros_paste").value = "";
  $("#ros_preview").textContent = "";
  await recarregar();
}

async function substituir() {
  const lista = previa();
  if (!lista.length || !confirm(t("roster_replace_confirm", { n: lista.length }))) return;
  try {
    const r = await api.put(`${base()}/roster`, { roster: lista });
    toast(t("roster_replaced", { n: r.entries, kept: (r.kept_bound || []).length }));
    $("#ros_paste").value = "";
    $("#ros_preview").textContent = "";
    await recarregar();
  } catch (err) {
    toast(err.message, true);
  }
}

function baixar(nome, conteudo, tipo) {
  const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  a.click();
  URL.revokeObjectURL(url);
}

function csvCampo(v) {
  const s = String(v ?? "");
  const aspa = String.fromCharCode(34);
  const precisa = s.includes(aspa) || s.includes(",") || s.includes("\n");
  return precisa ? aspa + s.split(aspa).join(aspa + aspa) + aspa : s;
}

function exportarCsv() {
  const linhas = [CAMPOS.join(",")];
  for (const e of rosterPorId.values()) {
    const org = e.organization || {};
    linhas.push([e.user_id, e.name, e.display_name, org.id, org.name, e.country, e.seat].map(csvCampo).join(","));
  }
  baixar(`${api.imageId}-roster.csv`, linhas.join("\n") + "\n", "text/csv");
}

// --- logotipos ---

async function enviarLogo(org, arquivo) {
  if (!arquivo) return;
  if (arquivo.size > 2 * 1024 * 1024) return toast(t("roster_logo_too_big"), true);
  const fd = new FormData();
  fd.append("file", arquivo);
  try {
    await api.request("PUT", `${base()}/roster/logos/${encodeURIComponent(org)}`, { raw: fd });
    toast(t("roster_saved"));
    await recarregar();
  } catch (err) {
    toast(err.status === 413 ? t("roster_logo_too_big") : err.status === 400 ? t("roster_logo_bad_type") : err.message, true);
  }
}

// --- vínculo de uma máquina (a aba Time do detalhe) ---

export function abaTime(m, painel, aoMudar) {
  painel.innerHTML = "";
  const porTime = vinculos();
  const b = m.binding || {};
  const atual = b.user_id || b.name
    ? el("p", {}, el("b", {}, b.user_id ? nomeDoTime(b.user_id) || b.user_id : b.name),
        b.seat ? ` · #${b.seat}` : "", " ",
        el("span", { class: "muted" }, `${b.source || ""} ${b.by ? "· " + b.by : ""} ${b.bound_at ? "· " + new Date(b.bound_at * 1000).toLocaleString() : ""}`))
    : el("p", { class: "muted" }, t("bind_none"));
  painel.append(el("h3", {}, t("bind_current")), atual);

  const busca = el("input", { type: "text", placeholder: t("bind_search") });
  const sel = el("select", { size: 8, style: "width:100%" });
  const pinta = () => {
    const q = busca.value.trim().toLowerCase();
    sel.innerHTML = "";
    for (const e of rosterPorId.values()) {
      const org = e.organization || {};
      const texto = `${e.display_name || e.name || e.user_id} · ${e.user_id}${org.name ? " · " + org.name : ""}`;
      if (q && !texto.toLowerCase().includes(q)) continue;
      const outra = porTime.get(e.user_id);
      const rotulo = outra && outra.mac !== m.mac ? `${texto} ${t("bind_already_at", { mac: outra.mac })}` : texto;
      sel.append(el("option", { value: e.user_id }, rotulo));
    }
  };
  busca.oninput = pinta;
  pinta();
  const seat = el("input", { type: "text", placeholder: t("roster_seat"), value: b.seat || "", style: "max-width:100px" });
  const nota = el("input", { type: "text", placeholder: t("bind_note"), style: "max-width:220px" });
  const livre = el("input", { type: "text", placeholder: t("bind_free_name") });

  const vincular = el("button", { class: "primary small", type: "button" }, t("bind_team"));
  vincular.onclick = async () => {
    const uid = sel.value;
    const corpo = { seat: seat.value.trim(), note: nota.value.trim(), source: "hotconfig" };
    if (uid) {
      const outra = porTime.get(uid);
      if (outra && outra.mac !== m.mac) {
        if (!confirm(t("bind_move_confirm", { mac: outra.mac }))) return;
        await api.del(`${base()}/machines/${outra.mac}/binding`);
      }
      corpo.user_id = uid;
    } else if (livre.value.trim()) {
      corpo.name = livre.value.trim();
    } else {
      return toast(t("bind_pick_one"), true);
    }
    try {
      await api.put(`${base()}/machines/${m.mac}/binding`, corpo);
      toast(t("bind_done"));
      if (aoMudar) aoMudar();
    } catch (err) {
      toast(err.code === "user_not_in_roster" ? t("bind_not_in_roster") : err.message, true);
    }
  };
  const desvincular = el("button", { class: "small danger", type: "button" }, t("unbind_team"));
  desvincular.onclick = async () => {
    await api.del(`${base()}/machines/${m.mac}/binding`);
    toast(t("bind_done"));
    if (aoMudar) aoMudar();
  };
  painel.append(
    el("h3", {}, t("bind_team")), busca, sel,
    el("div", { class: "actions" }, seat, nota, vincular),
    el("p", { class: "muted" }, t("bind_free_hint")), livre,
    el("div", { class: "actions" }, desvincular));

  // histórico: a troca de máquina no meio da prova é informação
  const hist = el("div", { class: "muted" }, t("loading"));
  painel.append(el("h3", {}, t("bind_history")), hist);
  api.get(`${base()}/machines/${m.mac}/binding/history?n=50`).then((d) => {
    hist.innerHTML = "";
    const linhas = (d.history || []).slice().reverse();
    if (!linhas.length) {
      hist.textContent = "—";
      return;
    }
    hist.className = "";
    const tabela = el("table");
    let anterior = null;
    for (const h of linhas) {
      const quem = h.user_id ? nomeDoTime(h.user_id) || h.user_id : h.name || "";
      const trocou = h.event === "bound" && anterior && anterior !== (h.user_id || h.name);
      tabela.append(el("tr", {},
        el("td", { class: "muted" }, new Date((h.event === "bound" ? h.bound_at : h.at) * 1000).toLocaleString()),
        el("td", {}, t(h.event === "bound" ? "bind_ev_bound" : "bind_ev_unbound"), trocou ? el("span", { class: "pill warn" }, t("bind_swapped")) : null),
        el("td", {}, quem),
        el("td", { class: "muted" }, `${h.source || ""} ${h.by ? "· " + h.by : ""}`)));
      if (h.event === "bound") anterior = h.user_id || h.name;
    }
    hist.append(tabela);
  }).catch(() => (hist.textContent = "—"));
}

export function iniciarTimes() {
  $("#ros_search").oninput = renderTimes;
  $("#ros_filter").onchange = renderTimes;
  $("#ros_save").onclick = salvarForm;
  $("#ros_cancel").onclick = () => {
    abrirForm(null);
    $("#ros_form_box").open = false;
  };
  $("#ros_paste").oninput = previa;
  $("#ros_file").onchange = async () => {
    const f = $("#ros_file").files[0];
    if (!f) return;
    $("#ros_paste").value = await f.text();
    previa();
  };
  $("#ros_merge").onclick = mesclar;
  $("#ros_replace").onclick = substituir;
  $("#ros_export_csv").onclick = exportarCsv;
  $("#ros_export_json").onclick = () =>
    baixar(`${api.imageId}-roster.json`, JSON.stringify([...rosterPorId.values()], null, 1), "application/json");
}
