// Campo de chave de console, compartilhado pela home e pelo /admin/: o olho
// para conferir a colagem (chave mascarada não deixa ver o que entrou) e a
// limpeza do que vem com espaço ou quebra de linha — copiar uma linha do
// terminal traz o \n junto, e a chave "errada" era só isso.

export function ligarOlho(input, botao, { mostrar, ocultar }) {
  const aplicar = (aberto) => {
    input.type = aberto ? "text" : "password";
    botao.setAttribute("aria-pressed", String(aberto));
    botao.title = aberto ? ocultar() : mostrar();
  };
  botao.onclick = () => aplicar(input.type === "password");
  aplicar(false);
}

export function apararColagem(input) {
  input.addEventListener("paste", () => setTimeout(() => (input.value = input.value.trim()), 0));
}
