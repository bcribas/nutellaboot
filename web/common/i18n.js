// i18n das telas do NutellaBoot 3 — português, inglês e espanhol.
//
// Uso no HTML:
//   <span data-i18n="save"></span>            texto do elemento
//   <input data-i18n-placeholder="search">    atributo
//   <span data-i18n-title="refresh">          title
// No JS: t('save'), t('machines_online', {n: 12})

export const LANGS = { pt: "Português", en: "English", es: "Español" };

let dict = {};
let lang = "pt";

export function currentLang() {
  return lang;
}

export function t(key, vars) {
  let s = dict[key];
  if (s === undefined) {
    console.warn("i18n: chave sem tradução:", key);
    return key;
  }
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  }
  return s;
}

// Rótulos vindos da API (esquema de configuração) são objetos {pt,en,es}.
export function tr(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return value[lang] || value.en || value.pt || Object.values(value)[0] || "";
}

function detect() {
  const saved = localStorage.getItem("nb3-lang");
  if (saved && LANGS[saved]) return saved;
  for (const l of navigator.languages || [navigator.language || "en"]) {
    const code = String(l).slice(0, 2).toLowerCase();
    if (LANGS[code]) return code;
  }
  return "en";
}

export function apply(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.documentElement.lang = lang;
}

export async function setLang(next) {
  lang = LANGS[next] ? next : "en";
  localStorage.setItem("nb3-lang", lang);
  // os dicionários só mudam a cada deploy — deixar o cache do navegador
  // reaproveitá-los evita revalidar a cada carga e reduz o "pisca" de texto
  // vazio antes da tradução aparecer.
  const resp = await fetch(`/common/locales/${lang}.json`);
  dict = await resp.json();
  apply();
  document.dispatchEvent(new CustomEvent("nb3:langchange", { detail: { lang } }));
}

// Monta o seletor de idioma no elemento indicado.
export function mountSwitcher(el) {
  el.innerHTML = "";
  el.className = "langswitch";
  for (const [code, name] of Object.entries(LANGS)) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = code.toUpperCase();
    b.title = name;
    b.setAttribute("aria-label", name);
    b.className = code === lang ? "on" : "";
    b.onclick = async () => {
      await setLang(code);
      mountSwitcher(el);
    };
    el.appendChild(b);
  }
}

export async function init(switcherEl) {
  await setLang(detect());
  if (switcherEl) mountSwitcher(switcherEl);
}
