// Configureitor — ajustes offline da imagem (valem no próximo boot).
import * as api from "/common/api.js";
import { init, t, tr, apply } from "/common/i18n.js";
import { usbBlock } from "/common/usb.js";

const $ = (sel) => document.querySelector(sel);
let schema = null;
let values = {};
let canEditLocked = false;
let canEditWallpaper = true;

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function fieldWrapper(field, locked) {
  const div = document.createElement("div");
  div.className = "field" + (locked ? " locked" : "");
  const label = document.createElement("div");
  label.className = "flabel";
  label.textContent = tr(field.label);
  if (locked) {
    const mark = document.createElement("span");
    mark.className = "lockmark";
    mark.textContent = t("locked_field");
    label.appendChild(mark);
  }
  div.appendChild(label);
  if (field.help) {
    const help = document.createElement("div");
    help.className = "help";
    help.textContent = tr(field.help);
    div.appendChild(help);
  }
  return div;
}

function renderBool(field, locked) {
  const div = fieldWrapper(field, locked);
  const box = document.createElement("div");
  box.className = "radios";
  for (const [val, key] of [[true, "yes"], [false, "no"]]) {
    const lab = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = field.key;
    input.disabled = locked;
    input.checked = Boolean(values[field.key]) === val;
    input.onchange = () => {
      values[field.key] = val;
      box.querySelectorAll("label").forEach((l, i) => l.classList.toggle("on", (i === 0) === val));
    };
    lab.appendChild(input);
    lab.append(t(key));
    if (input.checked) lab.className = "on";
    box.appendChild(lab);
  }
  div.appendChild(box);
  return div;
}

function renderSelect(field, locked) {
  const div = fieldWrapper(field, locked);
  const sel = document.createElement("select");
  sel.disabled = locked;
  for (const opt of field.options || []) {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    o.selected = String(values[field.key]) === String(opt.value);
    sel.appendChild(o);
  }
  sel.onchange = () => (values[field.key] = sel.value);
  div.appendChild(sel);
  return div;
}

function renderText(field, locked, type = "text") {
  const div = fieldWrapper(field, locked);
  const input = document.createElement("input");
  input.type = type;
  input.disabled = locked;
  input.value = type === "password" ? "" : values[field.key] || "";
  input.oninput = () => (values[field.key] = input.value);
  div.appendChild(input);
  return div;
}

function renderList(field, locked) {
  const div = fieldWrapper(field, locked);
  const box = document.createElement("div");
  box.className = "list-editor";
  const current = Array.isArray(values[field.key]) ? [...values[field.key]] : [];

  const redraw = () => {
    box.innerHTML = "";
    current.forEach((item, i) => {
      const row = document.createElement("div");
      row.className = "list-item";
      const label = (field.options || []).find((o) => o.value === item);
      const span = document.createElement("span");
      span.className = "grow mono";
      span.textContent = label ? label.label : item;
      row.appendChild(span);
      if (!locked) {
        const up = document.createElement("button");
        up.className = "small";
        up.textContent = "↑";
        up.disabled = i === 0;
        up.onclick = () => {
          [current[i - 1], current[i]] = [current[i], current[i - 1]];
          values[field.key] = current;
          redraw();
        };
        const rm = document.createElement("button");
        rm.className = "small danger";
        rm.textContent = "×";
        rm.onclick = () => {
          current.splice(i, 1);
          values[field.key] = current;
          redraw();
        };
        row.append(up, rm);
      }
      box.appendChild(row);
    });

    if (locked) return;
    const add = document.createElement("div");
    add.className = "list-item";
    const opts = (field.options || []).filter((o) => !current.includes(o.value));
    if (opts.length) {
      const sel = document.createElement("select");
      sel.className = "grow";
      opts.forEach((o) => {
        const el = document.createElement("option");
        el.value = o.value;
        el.textContent = o.label;
        sel.appendChild(el);
      });
      const btn = document.createElement("button");
      btn.className = "small";
      btn.textContent = "+";
      btn.onclick = () => {
        current.push(sel.value);
        values[field.key] = current;
        redraw();
      };
      add.append(sel, btn);
      box.appendChild(add);
    } else if (!(field.options || []).length) {
      // lista livre (ex.: liberados no firewall)
      const inp = document.createElement("input");
      inp.type = "text";
      inp.className = "grow";
      const btn = document.createElement("button");
      btn.className = "small";
      btn.textContent = "+";
      btn.onclick = () => {
        if (!inp.value.trim()) return;
        current.push(inp.value.trim());
        values[field.key] = current;
        redraw();
      };
      add.append(inp, btn);
      box.appendChild(add);
    }
  };
  redraw();
  div.appendChild(box);
  return div;
}

function renderForm() {
  const form = $("#form");
  form.innerHTML = "";
  for (const field of schema.fields) {
    const locked = Boolean(field.locked) && !canEditLocked;
    let el;
    if (field.type === "bool") el = renderBool(field, locked);
    else if (field.type === "select") el = renderSelect(field, locked);
    else if (field.type === "list") el = renderList(field, locked);
    else if (field.type === "password") el = renderText(field, locked, "password");
    else el = renderText(field, locked);
    form.appendChild(el);
  }
}

function renderWallpaper(meta) {
  const box = $("#wallpreview");
  box.innerHTML = "";
  // wallpaper travado pela organização: mostra, mas não deixa trocar
  if (!canEditWallpaper) {
    for (const id of ["#wallchoose", "#wallsend", "#wallremove"]) $(id).disabled = true;
    $("#wallstatus").textContent = t("wallpaper_locked_msg");
    $("#wallcard").classList.add("locked");
  }
  if (!meta) {
    box.innerHTML = `<span class="muted">${t("wallpaper_none")}</span>`;
    $("#wallremove").disabled = true;
    return;
  }
  $("#wallremove").disabled = !canEditWallpaper;
  const img = document.createElement("img");
  img.src = api.wallpaperUrl(api.imageId, meta.md5);
  img.style.cssText = "max-width:320px;border-radius:8px;border:1px solid var(--line)";
  const info = document.createElement("div");
  info.className = "muted mono";
  info.textContent = `${(meta.size / 1024).toFixed(0)} kB · md5 ${meta.md5.slice(0, 12)}…`;
  // sem isto, prévia quebrada é um ícone mudo — foi assim que ninguém percebeu
  // que ela apontava para a rota da chave de boot
  img.onerror = () => {
    img.remove();
    const aviso = document.createElement("div");
    aviso.className = "muted";
    aviso.textContent = t("wallpaper_preview_failed");
    box.prepend(aviso);
  };
  box.append(img, info);
}

function renderUsb() {
  // o pendrive é o que a sede precisa antes de qualquer outra coisa desta
  // tela: sem ele nenhuma máquina liga
  const box = $("#usbbox");
  box.className = "";
  box.innerHTML = "";
  box.appendChild(usbBlock(api.imageId));
}

async function loadSeeders() {
  try {
    const data = await api.get(`/api/v1/site-images/${api.imageId}/seeders`);
    const box = $("#seeders");
    if (!data.seeders.length) {
      box.className = "muted";
      box.textContent = t("seeders_none");
      return;
    }
    box.className = "";
    box.innerHTML =
      "<table><tbody>" +
      data.seeders
        .map((s) => `<tr><td class="mono">${s.ip}</td><td class="muted">${s.ttl_left}s</td></tr>`)
        .join("") +
      "</tbody></table>";
  } catch (e) {
    $("#seeders").textContent = e.message;
  }
}

async function save() {
  const btn = $("#save");
  btn.disabled = true;
  $("#savestatus").textContent = t("saving");
  try {
    const payload = {};
    for (const f of schema.fields) {
      if (f.locked && !canEditLocked) continue;
      if (f.type === "password" && !values[f.key]) continue;
      payload[f.key] = values[f.key] ?? f.default;
    }
    const resp = await api.put(`/api/v1/site-images/${api.imageId}/config`, { values: payload });
    values = { ...values, ...resp.values };
    $("#savestatus").textContent = "";
    toast(t("saved"));
  } catch (e) {
    $("#savestatus").textContent = "";
    toast(`${t("error")}: ${e.message}`, true);
  } finally {
    btn.disabled = false;
  }
}

async function uploadWallpaper() {
  const file = $("#wallfile").files[0];
  if (!file) return;
  $("#wallstatus").textContent = t("uploading");
  try {
    const fd = new FormData();
    fd.append("file", file);
    const meta = await api.request("PUT", `/api/v1/site-images/${api.imageId}/wallpaper`, { raw: fd });
    renderWallpaper(meta);
    $("#wallstatus").textContent = t("wallpaper_current");
    $("#wallsend").disabled = true;
    $("#wallfile").value = "";
  } catch (e) {
    $("#wallstatus").textContent = "";
    toast(`${t("error")}: ${e.message}`, true);
  }
}

async function main() {
  await init($("#lang"));
  if (!api.imageId) {
    $("#form").innerHTML = `<p class="muted">${t("no_token")}</p>`;
    $("#gohot").remove();
    return;
  }
  $("#gohot").href = api.telaIrma("hotconfig");
  try {
    const data = await api.get(`/api/v1/site-images/${api.imageId}/config`);
    schema = data.schema;
    values = data.values;
    canEditLocked = data.can_edit_locked;
    canEditWallpaper = data.can_edit_wallpaper !== false;
    $("#identid").textContent = data.image.id;
  $("#identname").textContent = data.image.fullname || "";
  document.title = `${data.image.id}${data.image.fullname ? ` · ${data.image.fullname}` : ""} — configureitor`;
    renderForm();
    renderWallpaper(data.wallpaper);
    renderUsb();
    loadSeeders();
  } catch (e) {
    $("#form").innerHTML = `<p class="muted">${e.status === 401 ? t("no_token") : e.message}</p>`;
    return;
  }

  $("#save").onclick = save;
  $("#wallchoose").onclick = () => $("#wallfile").click();
  $("#wallfile").onchange = () => ($("#wallsend").disabled = !$("#wallfile").files[0]);
  $("#wallsend").onclick = uploadWallpaper;
  $("#wallremove").onclick = async () => {
    await api.del(`/api/v1/site-images/${api.imageId}/wallpaper`);
    renderWallpaper(null);
  };
  document.addEventListener("nb3:langchange", () => {
    apply();
    if (schema) renderForm();
    renderUsb();
    loadSeeders();
  });
}

main();
