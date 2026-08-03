// Página inicial: porta de entrada para as três funções (coordenador,
// administração, documentação). Guarda o último id/token no navegador para
// não obrigar a colar de novo.
import * as api from "/common/api.js";
import { init, t, apply } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);
const STORE = "nb3-home-coord";

let validado = false;

function currentCoord() {
  return {
    id: $("#cid").value.trim(),
    token: $("#ctoken").value.trim(),
  };
}

function setButtons(enabled) {
  $("#go_config").disabled = !enabled;
  $("#go_hot").disabled = !enabled;
}

// Confere id+token contra a API antes de liberar os botões: erro de digitação
// aparece na hora, em vez de abrir uma tela que não vai funcionar.
let debounce = null;
async function validate() {
  const { id, token } = currentCoord();
  validado = false;
  setButtons(false);
  $("#coord_status").textContent = "";
  $("#coord_status").className = "status";
  if (!id || !token) return;

  $("#coord_status").textContent = t("home_coord_checking");
  try {
    const resp = await fetch(`/api/v1/site-images/${encodeURIComponent(id)}/config`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) throw new Error();
    validado = true;
    setButtons(true);
    $("#coord_status").textContent = "";
    localStorage.setItem(STORE, JSON.stringify({ id, token }));
  } catch {
    $("#coord_status").textContent = t("home_coord_bad");
    $("#coord_status").className = "status err";
  }
}

function scheduleValidate() {
  clearTimeout(debounce);
  debounce = setTimeout(validate, 350);
}

function open(area) {
  if (!validado) return;
  const { id, token } = currentCoord();
  const q = `?id=${encodeURIComponent(id)}&tk=${encodeURIComponent(token)}`;
  location.href = `/${area}/${q}`;
}

async function main() {
  await init($("#lang"));

  // restaura o último coordenador
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) || "{}");
    if (saved.id) $("#cid").value = saved.id;
    if (saved.token) $("#ctoken").value = saved.token;
  } catch {
    /* ignora localStorage corrompido */
  }

  // um link já pronto (?id=&tk=) na própria home também funciona
  const params = new URLSearchParams(location.search);
  if (params.get("id")) $("#cid").value = params.get("id");
  if (params.get("tk")) $("#ctoken").value = params.get("tk");

  $("#cid").oninput = scheduleValidate;
  $("#ctoken").oninput = scheduleValidate;
  $("#go_config").onclick = () => open("configureitor");
  $("#go_hot").onclick = () => open("hotconfig");

  $("#go_admin").onclick = async () => {
    const key = $("#akey").value.trim();
    // sem chave: pode já haver sessão aberta, então o console decide
    if (!key) {
      location.href = "/admin/";
      return;
    }
    $("#go_admin").disabled = true;
    try {
      await api.login(key);
      $("#akey").value = "";
      location.href = "/admin/";
    } catch (e) {
      $("#go_admin").disabled = false;
      alert(`${t("error")}: ${e.message}`);
    }
  };
  $("#akey").onkeydown = (e) => e.key === "Enter" && $("#go_admin").click();

  document.addEventListener("nb3:langchange", apply);
  if ($("#cid").value && $("#ctoken").value) validate();
}

main();
