// Página inicial: porta de entrada para as três funções (coordenador,
// administração, documentação). Guarda o último id/token no navegador para
// não obrigar a colar de novo.
import * as api from "/common/api.js";
import { apararColagem, ligarOlho } from "/common/chave.js";
import { init, t, apply, currentLang } from "/common/i18n.js";

const $ = (s) => document.querySelector(s);
const STORE = "nb3-home-coord";
const LOCALE = { pt: "pt-BR", en: "en", es: "es" };

let validado = false;
let sessao = null; // resposta de GET /api/v1/session, ou null

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

// --- administração: a sessão de 30 dias já existe? -------------------------
//
// A sessão do servidor sempre durou 30 dias, mas a home mostrava o campo de
// chave vazio mesmo com ela viva — e a pessoa concluía que tinha sido
// deslogada e saía atrás da chave. Agora a home pergunta e diz.

function fmtData(epoch) {
  return new Date(epoch * 1000).toLocaleDateString(LOCALE[currentLang()] || "en", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function mostrarAdmin() {
  $("#admin_checking").classList.add("hidden");
  const dentro = Boolean(sessao);
  $("#admin_in").classList.toggle("hidden", !dentro);
  $("#admin_form").classList.toggle("hidden", dentro);
  if (dentro) {
    const quem = `${sessao.label} (${t(sessao.kind === "admin" ? "who_admin" : "who_subadmin")})`;
    $("#admin_who").textContent = t("home_admin_logged", { who: quem, until: fmtData(sessao.expires_at) });
  }
}

async function carregarSessao() {
  try {
    sessao = await api.session();
  } catch {
    sessao = null; // 401 (ou rede): mostra o formulário
  }
  mostrarAdmin();
}

function erroAdmin(e) {
  const el = $("#admin_status");
  el.className = "status err";
  el.textContent = e && e.status === 429 ? t("home_admin_wait") : t("home_admin_bad");
}

async function entrarAdmin(ev) {
  ev.preventDefault(); // o navegador não navega: a API responde com o cookie
  const key = $("#akey").value.trim();
  if (!key) return;
  // um "usuário" por tipo de credencial, para o gerenciador guardar as duas
  $("#admin_user").value = key.toLowerCase().startsWith("nb3-") ? "convite" : "admin";
  $("#go_admin").disabled = true;
  $("#admin_status").textContent = "";
  try {
    await api.login(key);
    $("#akey").value = "";
    // navegar depois do submit é o que faz o navegador oferecer "salvar senha?"
    location.href = "/admin/";
  } catch (e) {
    $("#go_admin").disabled = false;
    erroAdmin(e);
  }
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

  $("#admin_form").onsubmit = entrarAdmin;
  ligarOlho($("#akey"), $("#akey_eye"), { mostrar: () => t("key_show"), ocultar: () => t("key_hide") });
  apararColagem($("#akey"));
  $("#admin_logout").onclick = async () => {
    try {
      await api.logout();
    } catch {
      /* a sessão já podia ter acabado */
    }
    sessao = null;
    mostrarAdmin();
  };
  $("#admin_other").onclick = () => {
    $("#admin_form").classList.remove("hidden");
    $("#akey").focus();
  };

  document.addEventListener("nb3:langchange", () => {
    apply();
    mostrarAdmin();
  });
  if ($("#cid").value && $("#ctoken").value) validate();
  carregarSessao();
}

main();
