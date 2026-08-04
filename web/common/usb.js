// O bloco do pendrive, usado por três telas: o cartão de credenciais do
// console, a tela de auto-atendimento e o configureitor da sede.
//
// Mora aqui, e não copiado em cada uma, porque o cartão de credenciais já é
// duplicado entre /admin/ e /criar/ e mexer nele exige lembrar dos dois. A
// ordem dos itens é de propósito: a imagem genérica primeiro (uma só, igual
// para todas as sedes) e a "já configurada" como alternativa — o contrário
// desfaz o redesenho que tirou as ~45 imagens de 400 MB do NutellaBoot 2.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";

const RECARGA_MS = 4000;

function mb(bytes) {
  if (!bytes) return "";
  return `${Math.round(bytes / 1024 / 1024)} MB`;
}

function linha(rotulo, ajuda, acao) {
  const tr = document.createElement("tr");
  const td1 = document.createElement("td");
  td1.innerHTML = `${rotulo}<br><span class="muted small">${ajuda}</span>`;
  const td2 = document.createElement("td");
  if (acao) td2.appendChild(acao);
  tr.append(td1, td2);
  return tr;
}

function botaoBaixar(url, rotulo) {
  const a = document.createElement("a");
  a.className = "btn small";
  a.href = url;
  a.setAttribute("download", "");
  a.textContent = rotulo;
  return a;
}

// O comando de gravar sai da URL do botão, não fixo: o que está no servidor de
// arquivos vem compactado (400 MB viram 205), e mandar `dd` num .gz grava o
// arquivo compactado no pendrive — que não boota, e não diz por quê.
// O download vem sempre compactado — pela rota, que redireciona para o `.gz`
// do servidor de arquivos ou compacta na hora. Então o comando é um só.
function comandoGravar(nome) {
  return `zcat ${nome || "nutellaboot3.img.gz"} | sudo dd of=/dev/sdX bs=4M status=progress oflag=sync`;
}

function motivoDesatualizada(razoes) {
  if (razoes.includes("boot_key")) return t("usb_stale_boot_key");
  if (razoes.includes("kernel")) return t("usb_stale_kernel");
  return t("usb_stale_server");
}

// `token` é para quem tem o token em mãos mas não na URL (a tela de criação).
export function usbBlock(imageId, token = "") {
  const caixa = document.createElement("div");
  caixa.className = "usb";
  let timer = null;

  async function carregar() {
    let dados;
    try {
      // `kind` padrão de propósito: assim o api.js manda o token da URL
      // quando ele existe (configureitor e auto-atendimento) e cai no cookie
      // quando não existe (console). Com `kind: "admin"` ele NÃO mandava o
      // token da URL, e o configureitor — que se autentica só por `?tk=` —
      // recebia 401 e ficava sem o bloco do pendrive inteiro.
      dados = await api.get(`/api/v1/site-images/${encodeURIComponent(imageId)}/usb`, { token });
    } catch (e) {
      caixa.innerHTML = `<p class="muted">${t("usb_title")}: ${e.message}</p>`;
      return;
    }
    desenhar(dados);
  }

  function desenhar(d) {
    caixa.innerHTML = `<h3>${t("usb_title")}</h3><p class="help muted">${t("usb_help")}</p>`;

    if (!d.kernel.ok) {
      const aviso = document.createElement("p");
      aviso.className = "warn";
      aviso.innerHTML = `${t("usb_no_kernel")}<br><code>${d.kernel.hint}</code>`;
      caixa.appendChild(aviso);
      return;
    }

    const tabela = document.createElement("table");

    // 1. a imagem genérica — a mesma para todas as sedes
    const g = d.generic;
    // sempre a rota da API: é ela que sabe se a cópia publicada corresponde a
    // esta construção e redireciona para o servidor de arquivos. Ler
    // `public_url` aqui entregaria o arquivo VELHO quando a imagem foi regerada
    // sem republicar — com a chave de boot anterior, que é uma sede que não
    // boota e ninguém entende por quê.
    const urlGenerica = api.usbGenericUrl(imageId, token);
    tabela.appendChild(
      linha(
        `1. ${t("usb_generic")} <span class="muted mono">${mb(g.size)}</span>`,
        t("usb_generic_help"),
        g.status === "done"
          ? botaoBaixar(urlGenerica, t("usb_download"))
          : estadoSimples(g)
      )
    );

    // 2. o arquivo de configuração desta sala
    tabela.appendChild(
      linha(
        `2. <span class="mono">nutellaboot.conf</span>`,
        t("usb_conf_help"),
        botaoBaixar(api.usbConfUrl(imageId, token), t("usb_download"))
      )
    );
    // o wifi.conf mora na mesma partição e é editado à mão. Desde que a camada
    // wifis.squash saiu, ele é a ÚNICA fonte de rede sem fio — inclusive para o
    // sistema já rodando, não só para o boot.
    tabela.appendChild(
      linha(`3. <span class="mono">wifi.conf</span>`, t("usb_wifi_help"), null)
    );
    caixa.appendChild(tabela);

    const como = document.createElement("p");
    como.className = "help";
    como.innerHTML = `${t("usb_howto")}<br><code>${comandoGravar(`${g.file || "nutellaboot3.img"}.gz`)}</code>`;
    caixa.appendChild(como);

    // 3. a alternativa: já configurada, sem nada para copiar
    const ou = document.createElement("p");
    ou.className = "muted small";
    ou.textContent = `— ${t("usb_or")} —`;
    caixa.appendChild(ou);

    const i = d.image;
    const tabela2 = document.createElement("table");
    const urlSala = api.usbImageUrl(imageId, token);
    const acao =
      i.status === "done"
        ? botaoBaixar(urlSala, t("usb_download"))
        : estadoSimples(i);
    tabela2.appendChild(
      linha(
        `${t("usb_ready_made")} <span class="muted mono">${mb(i.size)}</span>`,
        t("usb_ready_made_help"),
        acao
      )
    );
    caixa.appendChild(tabela2);

    if (i.status === "done") {
      const comoSala = document.createElement("p");
      comoSala.className = "help";
      comoSala.innerHTML = `<code>${comandoGravar(`${i.file}.gz`)}</code>`;
      caixa.appendChild(comoSala);
    }

    if (i.status === "done" && i.stale) {
      const aviso = document.createElement("p");
      aviso.className = "warn";
      aviso.textContent = motivoDesatualizada(i.stale_reason || []);
      caixa.appendChild(aviso);
    }
    if (i.error) {
      const erro = document.createElement("p");
      erro.className = "muted small";
      erro.textContent = i.error.slice(0, 200);
      caixa.appendChild(erro);
    }
    if (i.status !== "building") {
      const gerar = document.createElement("button");
      gerar.className = "small";
      gerar.textContent = i.status === "done" ? t("usb_regenerate") : t("usb_generate");
      gerar.onclick = async () => {
        gerar.disabled = true;
        try {
          await api.post(
            `/api/v1/site-images/${encodeURIComponent(imageId)}/usb`,
            {},
            { token }
          );
        } finally {
          carregar();
        }
      };
      caixa.appendChild(gerar);
    }

    // enquanto está gerando, volta a perguntar; parado, não bate no servidor
    clearTimeout(timer);
    if (i.status === "building" || d.generic.status === "building") {
      timer = setTimeout(carregar, RECARGA_MS);
    }
  }

  function estadoSimples(estado) {
    const span = document.createElement("span");
    span.className = "muted small";
    span.textContent =
      estado.status === "building"
        ? t("usb_building")
        : estado.status === "failed"
          ? t("usb_failed")
          : t("usb_not_generated");
    return span;
  }

  carregar();
  return caixa;
}
