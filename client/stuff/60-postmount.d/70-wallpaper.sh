# shellcheck shell=sh
# Wallpaper servido pela API (upload feito no configureitor, md5 conhecido),
# com o nome da sede carimbado por cima.
#
# No nb2 a URL era colada à mão pelo operador e o boot ficava preso num
# `read -p "Continue anyway?"` quando o download falhava — numa sala sem
# ninguém olhando, isso significa máquina parada. Aqui, falha só avisa.
#
# O baixado fica em .wallpaper-orig.png e o carimbado em .wallpaper.png, que é
# o apontado pelo dconf. Carimbar sobre o carimbado empilharia tarja sobre
# tarja a cada boot, e a home é persistente.
nb3_post_wallpaper() {
    [ -z "$NB_WALLPAPER_MD5" ] && return 0
    _orig=${rootmnt?}/home/.wallpaper-orig.png
    _target=${rootmnt?}/home/.wallpaper.png
    _link=${rootmnt?}/usr/share/maratona-background/maratona-common-wallpaper.png

    rm -f "$_link"
    ln -s /home/.wallpaper.png "$_link"

    if ! [ -e "$_orig" ] || ! nutella_md5sum "$NB_WALLPAPER_MD5" "$_orig"; then
        rm -f "$_orig"
        if ! nb_download "$_orig" 1 "$NB_SERVER/boot/v3/$IMAGEROOT/wallpaper"; then
            nb_warn "wallpaper could not be downloaded - keeping the default one"
            rm -f "$_link"
            return 0
        fi
        if ! nutella_md5sum "$NB_WALLPAPER_MD5" "$_orig"; then
            nb_warn "wallpaper MD5 mismatch - keeping the default one"
            rm -f "$_orig" "$_target" "$_link"
            return 0
        fi
        # imagem nova: o carimbo tem que ser refeito
        rm -f "$_target"
    fi

    # O carimbo em si é desenhado com o sistema rodando (rc.local.d): quem tem
    # Pillow é a máquina, não o initrd — aqui não há python nem fonte nenhuma.
    # Enquanto ele não roda, vale o original, para a sala nunca ficar sem
    # papel de parede.
    [ -e "$_target" ] || cp "$_orig" "$_target"
    nb3_wallpaper_stamp_script
    return 0
}

# Script que redesenha a tarja a cada boot. Fica em rc.local.d porque depende
# de python3+Pillow (que a imagem base tem: 10.2.0, com freetype e a DejaVu).
nb3_wallpaper_stamp_script() {
    cat > "${rootmnt?}/etc/rc.local.d/60-wallpaper-stamp" << 'EOF'
#!/bin/bash
# gerado pelo NutellaBoot 3 — carimba a sede no papel de parede
[ -e /home/.wallpaper-orig.png ] || exit 0
SEDE=$(cat /etc/imageroot-icpc 2>/dev/null) || exit 0
[ -n "$SEDE" ] || exit 0

python3 - "$SEDE" << 'PY'
import sys

from PIL import Image, ImageDraw, ImageFont

sede = sys.argv[1]
orig = "/home/.wallpaper-orig.png"
alvo = "/home/.wallpaper.png"

img = Image.open(orig).convert("RGBA")
larg, alt = img.size

# a tarja ocupa uma faixa do rodapé, proporcional à imagem: o papel de parede
# de uma sede pode ser 1920x1080 ou 1280x1024, e altura fixa ficaria ou
# invisível ou enorme
faixa = max(48, alt // 12)
corpo = int(faixa * 0.62)
# a DejaVu Bold vem na imagem base; a lista é para o dia em que o pacote de
# fontes mudar de nome, e o último recurso não pode ser a fonte embutida em
# tamanho fixo (sai com 11 px, ilegível a um metro do monitor)
fonte = None
for caminho in (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
):
    try:
        fonte = ImageFont.truetype(caminho, corpo)
        break
    except OSError:
        continue
if fonte is None:
    try:
        fonte = ImageFont.load_default(size=corpo)
    except TypeError:  # Pillow antigo, sem tamanho na fonte embutida
        fonte = ImageFont.load_default()

tarja = Image.new("RGBA", (larg, faixa), (0, 0, 0, 170))
d = ImageDraw.Draw(tarja)
caixa = d.textbbox((0, 0), sede, font=fonte)
d.text(
    (faixa // 2, (faixa - (caixa[3] - caixa[1])) // 2 - caixa[1]),
    sede,
    font=fonte,
    fill=(255, 255, 255, 255),
)

img.alpha_composite(tarja, (0, alt - faixa))
img.convert("RGB").save(alvo, "PNG")
PY
EOF
    chmod a+x "${rootmnt?}/etc/rc.local.d/60-wallpaper-stamp"
}
