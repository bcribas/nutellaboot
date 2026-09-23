// Console de administração: entrada, sessão e a barra do topo. O conteúdo de
// cada aba mora no módulo dela; quem troca de página é o rotas.js.
import * as api from "/common/api.js";
import { apararColagem, ligarOlho } from "/common/chave.js";
import { init, t, apply } from "/common/i18n.js";
import { $, toast } from "/common/ui.js";
import { mostrarErro, quandoExpirar } from "/common/acao.js";
import { A, definirEu, eu, ehAdmin, esquecerRascunhos } from "./comum.js";
import * as rotas from "./rotas.js";

let iniciado = false;

async function mostrarSaude() {
  try {
    const h = await api.get("/api/v1/health", A);
    const saude = $("#healthinfo");
    saude.textContent = t("health_info", { v: h.version, gb: Math.round(h.disk_free_gb) });
    saude.classList.toggle("warn", h.disk_free_gb < 20);
    saude.classList.remove("hidden");
  } catch {
    /* sem a saúde, a tela segue */
  }
}

// Quem sou e, para o sub-admin, quanto das cotas já usou. Era um cartão
// inteiro no alto da página; é uma linha.
function atualizarTopo() {
  const x = eu();
  if (!x) return;
  const admin = ehAdmin();
  for (const no of document.querySelectorAll("[data-admin-only]")) no.classList.toggle("hidden", !admin);
  const quem = $("#quem");
  quem.textContent = `${x.label || ""} · ${admin ? t("who_admin") : t("who_subadmin")}`;
  quem.title = admin ? t("who_admin_help") : t("who_subadmin_help");
  quem.classList.remove("hidden");
  const cota = $("#cota");
  if (admin) {
    cota.classList.add("hidden");
    return;
  }
  const q = x.quotas || {};
  const u = x.usage || {};
  const parte = (rotulo, usado, limite) => `${rotulo}: ${usado ?? 0}/${limite ?? "∞"}`;
  cota.textContent = [
    parte(t("nav_models"), u.models, q.models),
    parte(t("nav_images"), u.site_images, q.site_images),
    parte(t("quota_builds"), u.builds, q.builds),
  ].join("  ·  ");
  cota.classList.remove("hidden");
}

export async function atualizarEu() {
  definirEu(await api.get("/api/v1/whoami", A));
  atualizarTopo();
}

function abrirPainel() {
  $("#login").classList.add("hidden");
  $("#panel").classList.remove("hidden");
  for (const id of ["#logout", "#gofrota", "#godash"]) $(id).classList.remove("hidden");
}

function mostrarLogin() {
  $("#panel").classList.add("hidden");
  for (const id of ["#logout", "#gofrota", "#godash", "#quem", "#healthinfo"]) $(id).classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#key").focus();
}

async function entrarNoPainel() {
  const antes = eu() ? eu().owner : null;
  await atualizarEu();
  abrirPainel();
  mostrarSaude();
  if (!iniciado) {
    iniciado = true;
    rotas.iniciar();
    return;
  }
  // voltou depois de a sessão cair: a mesma pessoa continua de onde parou
  // (com os rascunhos); outra pessoa começa do começo
  if (antes !== eu().owner) {
    esquecerRascunhos();
    location.hash = "#imagens";
  }
  rotas.renderizar({ forcar: true });
}

// Troca a chave digitada por um cookie de sessão. Daí em diante o navegador
// manda o cookie sozinho: recarregar a página não pede nada de novo.
async function enter(ev) {
  if (ev) ev.preventDefault(); // é o submit do <form>: a API responde com o cookie
  const chave = $("#key").value.trim();
  if (!chave) return;
  // um "usuário" por tipo de credencial, para o gerenciador guardar as duas
  $("#login_user").value = chave.toLowerCase().startsWith("nb3-") ? "convite" : "admin";
  try {
    await api.login(chave);
    $("#key").value = "";
    await entrarNoPainel();
  } catch (e) {
    if (e.status === 429) toast(t("home_admin_wait"), true);
    else if (e.status === 401) toast(t("home_admin_bad"), true);
    else toast(`${t("error")}: ${e.message}`, true);
  }
}

// No carregamento: se já há sessão, entra direto.
//
// A versão anterior chamava enter() aqui, e enter() começava gravando o campo
// de login — vazio num carregamento novo — por cima da credencial guardada.
// Ou seja, a tentativa automática de entrar era exatamente o que deslogava.
async function retomarSessao() {
  try {
    await entrarNoPainel();
  } catch (e) {
    // só falta de credencial volta para o login; um erro de rede não pode
    // derrubar quem já está dentro
    if (e.status === 401) mostrarLogin();
    else {
      abrirPainel();
      toast(`${t("error")}: ${e.message}`, true);
    }
  }
}

// 401 no meio do uso: ou a sessão caiu (mostra o login, mantendo a página e o
// que foi digitado), ou é rota que este console não pode (sub-admin), e aí é
// só um aviso.
async function aoReceber401() {
  try {
    await api.session();
    toast(t("err_no_permission"), true);
  } catch {
    toast(t("err_session_expired"), true);
    mostrarLogin();
  }
}

async function main() {
  await init($("#lang"));
  $("#login").onsubmit = enter;
  ligarOlho($("#key"), $("#key_eye"), { mostrar: () => t("key_show"), ocultar: () => t("key_hide") });
  apararColagem($("#key"));
  quandoExpirar(aoReceber401);
  // promessa rejeitada sem dono é defeito, mas o usuário precisa saber que
  // alguma coisa não aconteceu
  window.addEventListener("unhandledrejection", (ev) => mostrarErro(ev.reason));
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
    atualizarTopo();
    if (iniciado && eu()) rotas.renderizar({ forcar: true });
  });
  // quem gasta cota (criar imagem, modelo, construção) avisa, e a linha da
  // cota do sub-admin se atualiza
  document.addEventListener("nb3:eu-mudou", () => {
    atualizarEu().catch(() => {});
  });
  // salvou algo que muda a página inteira (o cabeçalho, as pílulas): ela se
  // redesenha com os dados novos, e os rascunhos das outras seções continuam
  document.addEventListener("nb3:redesenhar", () => rotas.renderizar({ forcar: true }));
  await retomarSessao();
}

main();
