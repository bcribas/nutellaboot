// Base compartilhada pelos temas da tela de bloqueio.
//
// ATENÇÃO: script CLÁSSICO de propósito (window.NB3Lock), não módulo ES.
// Os temas são carregados de file:// dentro do WebKit; imports de módulo são
// bloqueados por CORS nesse esquema (origem "null") e a tela abriria em
// branco na máquina do competidor.
//
// Os dados chegam por query string (o maratona-wait injeta), então a tela
// funciona sem rede — requisito de sala de prova.

(function (global) {
  const MSG = {
    pt: {
      title: "Aguarde",
      dont_touch: "NÃO mexa no mouse nem no teclado",
      wait: "A prova vai começar. Aguarde a orientação da equipe.",
      seat: "Lugar",
    },
    en: {
      title: "Please wait",
      dont_touch: "Do NOT touch the mouse or the keyboard",
      wait: "The contest is about to start. Please wait for the staff.",
      seat: "Seat",
    },
    es: {
      title: "Espere",
      dont_touch: "NO toque el ratón ni el teclado",
      wait: "La prueba va a comenzar. Espere las indicaciones del equipo.",
      seat: "Puesto",
    },
  };

  const params = new URLSearchParams(location.search);
  const lang = MSG[params.get("lang")] ? params.get("lang") : "pt";

  function info() {
    try {
      return JSON.parse(decodeURIComponent(params.get("info") || "{}"));
    } catch (e) {
      return {};
    }
  }

  // Avisa quando alguém encosta no mouse/teclado, com escalada visual.
  function watchInput(onTouch) {
    let level = 0;
    let timer = null;
    const bump = function () {
      level = Math.min(level + 1, 3);
      onTouch(level);
      clearTimeout(timer);
      timer = setTimeout(function () {
        level = 0;
        onTouch(0);
      }, 4000);
    };
    let lastMove = 0;
    addEventListener("mousemove", function () {
      const now = Date.now();
      if (now - lastMove > 400) {
        lastMove = now;
        bump();
      }
    });
    addEventListener("keydown", bump);
    addEventListener("mousedown", bump);
    addEventListener("wheel", bump);
  }

  // Trilíngue: a mensagem principal aparece nos três idiomas, com destaque no
  // idioma configurado — a sala pode ter gente de vários países.
  function allLanguages(key) {
    return ["pt", "en", "es"].map(function (l) {
      return { lang: l, text: MSG[l][key], primary: l === lang };
    });
  }

  // Preenche os elementos comuns a todos os temas.
  function fillCommon(data, t) {
    const set = function (sel, text) {
      const el = document.querySelector(sel);
      if (el) el.textContent = text;
    };
    const team = data.team || {};
    const org = data.organization || {};
    set("#teamname", team.display_name || team.name || t.title);
    set("#org", org.name || "");
    set("#seat", data.seat ? t.seat + " " + data.seat : "");
    set("#site", data.site || "");
    const logo = document.querySelector("#logo");
    if (logo && org.logo_url) {
      logo.innerHTML = '<img src="' + org.logo_url + '" alt="">';
    }
    const messages = document.querySelector("#messages");
    if (messages) {
      messages.innerHTML = allLanguages("wait")
        .map(function (m) {
          return '<div class="line' + (m.primary ? " primary" : "") + '">' + m.text + "</div>";
        })
        .join("");
    }
    const alertBox = document.querySelector("#alert");
    if (alertBox) {
      const txt = alertBox.querySelector(".txt");
      if (txt) {
        txt.innerHTML = allLanguages("dont_touch")
          .map(function (m) {
            return m.text;
          })
          .join("<br>");
      }
    }
  }

  global.NB3Lock = {
    MSG: MSG,
    lang: lang,
    t: MSG[lang],
    info: info,
    watchInput: watchInput,
    allLanguages: allLanguages,
    fillCommon: fillCommon,
  };
})(window);
