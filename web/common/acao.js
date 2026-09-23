// Toda ação do console passa por aqui: o botão fica desligado enquanto a ação
// roda (dois cliques não criam duas imagens), e o erro aparece de UM jeito.
// Antes eram quatro: toast "Erro: …", toast com a mensagem crua, texto na
// linha e nada (handler sem try/catch: a promessa rejeitada ficava sem dono e
// o usuário não via coisa alguma).

import { t } from "/common/i18n.js";
import { toast } from "/common/ui.js";

let aoExpirar = null;

// 401 no meio do uso é sessão que caiu (para o sub-admin, pode ser rota que
// não é dele): quem monta a tela decide o que fazer
export const quandoExpirar = (fn) => {
  aoExpirar = fn;
};

export const mensagemDeErro = (e) => {
  if (!e || e.name === "AbortError") return "";
  // fetch sem resposta (rede caiu, servidor reiniciando) vira TypeError
  if (e instanceof TypeError) return t("err_network");
  return `${t("error")}: ${e.message || e}`;
};

// `alvo`: um elemento da própria seção ou diálogo, quando o erro precisa ficar
// ao lado do que o causou; sem alvo, vira toast
export const mostrarErro = (e, alvo = null) => {
  if (e && e.status === 401 && aoExpirar) {
    aoExpirar(e);
    return;
  }
  const msg = mensagemDeErro(e);
  if (!msg) return;
  if (alvo) {
    alvo.textContent = msg;
    alvo.className = "msg bad";
    alvo.hidden = false;
  } else {
    toast(msg, true);
  }
};

// `botao.onclick = acao(async () => …, { ok: t("saved_ok") })`. A ação que
// devolve `false` foi cancelada (o diálogo de confirmação disse não) e não
// ganha o aviso de sucesso.
export const acao = (fn, { ok = "", alvoErro = null } = {}) => async (ev) => {
  // capturado antes do primeiro await: depois dele o currentTarget é null
  const alvo = ev && ev.currentTarget;
  const botao = alvo && "disabled" in alvo ? alvo : null;
  if (botao) {
    if (botao.disabled) return undefined;
    botao.disabled = true;
    botao.setAttribute("aria-busy", "true");
  }
  try {
    const r = await fn(ev);
    if (ok && r !== false) toast(ok);
    return r;
  } catch (e) {
    mostrarErro(e, alvoErro);
    return undefined;
  } finally {
    if (botao) {
      botao.disabled = false;
      botao.removeAttribute("aria-busy");
    }
  }
};
