# shellcheck shell=sh
nb3_post_firefox() {
    [ -e "${rootmnt?}/opt/firefox/firefox" ] || return 0
    log_begin_msg "Configurando o Firefox"
    cat > "${rootmnt?}/etc/firefox/policies/policies.json" << EOF
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
    "OverrideFirstRunPage": "$DEFAULTBROWSERURL",
    "OverridePostUpdatePage": "$DEFAULTBROWSERURL",
    "SkipTermsOfUse": true,
    "HardwareAcceleration": false,
    "ExtensionSettings": { "*": { "installation_mode": "blocked" } },
    "Homepage": {
      "URL": "$DEFAULTBROWSERURL",
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
    rm -f "${rootmnt?}/etc/alternatives/x-www-browser" "${rootmnt?}/etc/alternatives/gnome-www-browser"
    ln -s /opt/firefox/firefox "${rootmnt?}/etc/alternatives/x-www-browser"
    ln -s /opt/firefox/firefox "${rootmnt?}/etc/alternatives/gnome-www-browser"
    sed -i 's+epiphany.desktop+firefox.desktop+g' \
        "${rootmnt?}/etc/dconf/db/local.d/50-favorites" 2>/dev/null

    cat > "${rootmnt?}/etc/rc.local.d/50-firefox-default" << 'EOF'
#!/bin/bash
UIDBROWSER="Mozilla/5.0 (MLinux/$(</etc/imageroot-icpc)/$(</home/.machine-id)/$(</home/.machine-id-boot)) Gecko/20100101 Firefox/148.0"
sed -i "s+{{ UIDBROWSER }}+$UIDBROWSER+g" /opt/firefox/firefox.cfg
xdg-settings set default-web-browser firefox.desktop
EOF
    chmod a+x "${rootmnt?}/etc/rc.local.d/50-firefox-default"
    log_end_msg
}
