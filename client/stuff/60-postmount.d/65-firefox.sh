# shellcheck shell=sh
# Firefox ESR: política da organização e o carimbo de identidade no user-agent.
#
# A imagem deste ano traz o firefox-esr embarcado (era um tarball da Mozilla em
# /opt/firefox, numa camada à parte). Isso muda três caminhos:
#   * o binário é /usr/bin/firefox-esr, não /opt/firefox/firefox;
#   * `MOZ_APP_NAME=firefox-esr`, então a política de sistema é lida de
#     /etc/firefox-esr/policies/ — e não de /etc/firefox/policies/, que nem
#     existe nesta imagem;
#   * o autoconfig (firefox.cfg) mora junto da instalação, em /usr/lib/firefox-esr.
#
# O firefox.cfg não é luxo: `general.useragent.override` NÃO é alcançável por
# policies.json (a política Preferences só aceita general.autoScroll e
# general.smoothScroll de general.*). Sem ele não há como carimbar sede e
# máquina no user-agent, que é como o MOJ identifica de onde veio a submissão.
NB_FF_DIR=/usr/lib/firefox-esr
NB_FF_CFG=firefox.cfg

nb3_post_firefox() {
    [ -e "${rootmnt?}/usr/bin/firefox-esr" ] || return 0
    log_begin_msg "Configuring Firefox"

    _ffurl=$(nb3_json_escape "$DEFAULTBROWSERURL")

    # Nos DOIS caminhos: o de sistema é o que vale nesta build, e o da
    # instalação é o que funciona em qualquer uma. Escrever nos dois é barato e
    # idempotente — descobrir qual era o certo com a sala montada, não.
    for _ffpol in "${rootmnt?}/etc/firefox-esr/policies" "${rootmnt?}$NB_FF_DIR/distribution"; do
        mkdir -p "$_ffpol"
        cat > "$_ffpol/policies.json" << EOF
{
  "policies": {
    "TranslateEnabled": false,
    "BlockAboutConfig": true,
    "BlockAboutAddons": true,
    "BlockAboutProfiles": true,
    "DisableAppUpdate": true,
    "DisableFirefoxAccounts": true,
    "DisableFirefoxScreenshots": true,
    "DisableSystemAddonUpdate": true,
    "DisableFirefoxStudies": true,
    "DisablePocket": true,
    "DisableProfileImport": true,
    "DisableSetDesktopBackground": true,
    "DisableTelemetry": true,
    "DontCheckDefaultBrowser": true,
    "OverrideFirstRunPage": "$_ffurl",
    "OverridePostUpdatePage": "$_ffurl",
    "SkipTermsOfUse": true,
    "HardwareAcceleration": false,
    "ExtensionSettings": { "*": { "installation_mode": "blocked" } },
    "Homepage": {
      "URL": "$_ffurl",
      "Locked": true,
      "StartPage": "homepage-locked"
    },
    "Preferences": {
      "browser.tabs.warnOnClose": { "Value": false, "Status": "default" },
      "browser.sessionstore.resume_from_crash": { "Value": false, "Status": "locked" }
    }
  }
}
EOF
    done

    # O par do autoconfig. Um sem o outro não faz nada: o .js diz QUAL arquivo
    # ler, e o .cfg é lido antes de qualquer preferência de perfil.
    mkdir -p "${rootmnt?}$NB_FF_DIR/defaults/pref"
    cat > "${rootmnt?}$NB_FF_DIR/defaults/pref/autoconfig.js" << EOF
// gerado pelo NutellaBoot 3
pref("general.config.filename", "$NB_FF_CFG");
pref("general.config.obscure_value", 0);
pref("general.config.sandbox_enabled", false);
EOF

    # A PRIMEIRA LINHA DE UM .cfg É IGNORADA pelo Firefox, por desenho: tem que
    # ser comentário, senão a diretiva de cima some sem aviso.
    cat > "${rootmnt?}$NB_FF_DIR/$NB_FF_CFG" << 'EOF'
// gerado pelo NutellaBoot 3 — a primeira linha é ignorada de propósito
lockPref("general.useragent.override", "{{ UIDBROWSER }}");
EOF

    # o epiphany está registrado com prioridade 85 contra 40 do firefox-esr, e
    # é por isso que o link é forçado na mão em vez de update-alternatives
    mkdir -p "${rootmnt?}/etc/alternatives"
    rm -f "${rootmnt?}/etc/alternatives/x-www-browser" "${rootmnt?}/etc/alternatives/gnome-www-browser"
    ln -s /usr/bin/firefox-esr "${rootmnt?}/etc/alternatives/x-www-browser"
    ln -s /usr/bin/firefox-esr "${rootmnt?}/etc/alternatives/gnome-www-browser"
    sed -i 's+epiphany.desktop+firefox-esr.desktop+g' \
        "${rootmnt?}/etc/dconf/db/local.d/50-favorites" 2> /dev/null

    # O carimbo só pode ser feito com o sistema rodando: a identidade da
    # máquina (e do boot) é gerada pelo 15-machineid.sh e muda a cada ligada.
    cat > "${rootmnt?}/etc/rc.local.d/50-firefox-default" << EOF
#!/bin/bash
# gerado pelo NutellaBoot 3 — carimba a identidade da máquina no user-agent
FFVER=\$(sed -n 's/^Version=//p' $NB_FF_DIR/application.ini 2>/dev/null | sed -n 1p)
UIDBROWSER="Mozilla/5.0 (MLinux/\$(< /etc/imageroot-icpc)/\$(< /home/.machine-id)/\$(< /home/.machine-id-boot)) Gecko/20100101 Firefox/\${FFVER:-140.0}"
sed -i "s+{{ UIDBROWSER }}+\$UIDBROWSER+g" $NB_FF_DIR/$NB_FF_CFG
xdg-settings set default-web-browser firefox-esr.desktop
EOF
    chmod a+x "${rootmnt?}/etc/rc.local.d/50-firefox-default"

    # O Epiphany continua instalado, e quem o abrir submete sem identificação
    # nenhuma. O nb2 carimbava os dois; o nb3 tinha perdido este.
    cat > "${rootmnt?}/etc/rc.local.d/55-epiphany-uid" << 'EOF'
#!/bin/bash
# gerado pelo NutellaBoot 3 — o mesmo carimbo, no outro navegador
UID_EPI="Mozilla/5.0 (MLinux/$(< /etc/imageroot-icpc)/$(< /home/.machine-id)/$(< /home/.machine-id-boot)) Epiphany/42.1"
cat > /etc/dconf/db/local.d/90-epiphany-user-agent << INNER
[org/gnome/epiphany/web]
user-agent='$UID_EPI'
INNER
echo "/org/gnome/epiphany/web/user-agent" > /etc/dconf/db/local.d/locks/90-epiphany-user-agent
EOF
    chmod a+x "${rootmnt?}/etc/rc.local.d/55-epiphany-uid"

    log_end_msg
}
