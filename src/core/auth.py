import time

import requests


CLIENT_ID = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"
SCOPES = "XboxLive.signin offline_access"
AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"

XBL_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_AUTH = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE = "https://api.minecraftservices.com/minecraft/profile"


class AuthError(RuntimeError):
    pass


class Account:
    def __init__(self, data=None):
        data = data or {}
        self.refresh_token = data.get("refresh_token", "")
        self.access_token = data.get("access_token", "")
        self.mc_access = data.get("mc_access", "")
        self.mc_expires = data.get("mc_expires", 0)
        self.name = data.get("name", "")
        self.uuid = data.get("uuid", "")

    @property
    def signed_in(self):
        return bool(self.name and self.mc_access)

    def to_dict(self):
        return {
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "mc_access": self.mc_access,
            "mc_expires": self.mc_expires,
            "name": self.name,
            "uuid": self.uuid,
        }

    def refresh(self):
        if not self.refresh_token:
            raise AuthError("no refresh token")
        r = requests.post(
            f"{AUTHORITY}/token",
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self.refresh_token,
                "scope": SCOPES,
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise AuthError(f"refresh failed: {r.status_code}")
        tok = r.json()
        self.access_token = tok["access_token"]
        self.refresh_token = tok.get("refresh_token", self.refresh_token)
        self._xbox_and_minecraft()

    def _xbox_and_minecraft(self):
        r = requests.post(
            XBL_AUTH,
            json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"d={self.access_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise AuthError(f"Xbox Live auth failed: {r.status_code}")
        xbl = r.json()

        r = requests.post(
            XSTS_AUTH,
            json={
                "Properties": {"SandboxId": "RETAIL",
                               "UserTokens": [xbl["Token"]]},
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT",
            },
            timeout=30,
        )
        if r.status_code == 401:
            code = r.json().get("XErr")
            hints = {
                2148916233: "no Xbox account linked to this Microsoft account",
                2148916235: "Xbox Live not available in your region",
                2148916236: "adult verification required",
                2148916237: "adult verification required",
                2148916238: "account is under 18",
            }
            raise AuthError(hints.get(code, f"XSTS error {code}"))
        r.raise_for_status()
        xsts = r.json()
        uhs = xsts["DisplayClaims"]["xui"][0]["uhs"]

        r = requests.post(
            MC_AUTH,
            json={"identityToken": f"XBL3.0 x={uhs};{xsts['Token']}"},
            timeout=30,
        )
        if r.status_code == 403:
            raise AuthError("Minecraft rejected the client ID (403)")
        r.raise_for_status()
        mc = r.json()
        self.mc_access = mc["access_token"]
        self.mc_expires = time.time() + mc.get("expires_in", 86400)

        r = requests.get(
            MC_PROFILE,
            headers={"Authorization": f"Bearer {self.mc_access}"},
            timeout=30,
        )
        if r.status_code == 404:
            raise AuthError(
                "this Microsoft account does not own Minecraft")
        r.raise_for_status()
        prof = r.json()
        self.name = prof["name"]
        self.uuid = prof["id"]

    def ensure_valid(self):
        if not self.signed_in:
            return False
        if time.time() > self.mc_expires - 60:
            try:
                self.refresh()
            except Exception:
                return False
        return self.signed_in


def sign_in_webview(parent=None, log=print):
    from PyQt6.QtCore import QUrl, QTimer, Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    )
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except Exception:
        raise AuthError(
            "PyQt6-WebEngine is not installed. "
            "Install it with: pip install PyQt6-WebEngine")

    dc = None
    try:
        r = requests.post(
            f"{AUTHORITY}/devicecode",
            data={"client_id": CLIENT_ID, "scope": SCOPES},
            timeout=15,
        )
        if r.status_code == 200:
            dc = r.json()
            log("info", f"device code: {dc.get('user_code')}")
        else:
            log("warn", f"devicecode request: {r.status_code} "
                        f"{r.text[:200]}")
    except Exception as e:
        log("warn", f"device-code fetch failed: {e}")

    if not dc:
        raise AuthError("could not get a device code from Microsoft")

    user_code = dc["user_code"]
    device_code = dc["device_code"]
    interval = max(1, int(dc.get("interval", 5)))

    device_result = {"token": None}

    dlg = QDialog(parent)
    dlg.setWindowTitle("Sign in with Microsoft")
    dlg.resize(560, 780)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)

    panel = QFrame()
    panel.setStyleSheet("QFrame{background:#1a1a1a}")
    pl = QVBoxLayout(panel)
    pl.setContentsMargins(14, 12, 14, 12)
    pl.setSpacing(6)

    top = QHBoxLayout()
    lbl = QLabel("Sign-in code:")
    lbl.setStyleSheet(
        "background:transparent;color:#999;font-size:10pt")
    top.addWidget(lbl)

    code_lbl = QLabel(user_code)
    code_lbl.setStyleSheet(
        "background:transparent;color:#fff;font-size:10pt")
    code_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    top.addWidget(code_lbl)
    top.addStretch()

    copy_btn = QPushButton("Copy")
    copy_btn.setStyleSheet(
        "QPushButton{background:#333;color:#fff;border:none;"
        "padding:6px 14px}QPushButton:hover{background:#444}")

    def _copy():
        QGuiApplication.clipboard().setText(user_code)
        copy_btn.setText("Copied")
        QTimer.singleShot(1500, lambda: copy_btn.setText("Copy"))

    copy_btn.clicked.connect(_copy)
    top.addWidget(copy_btn)
    pl.addLayout(top)
    v.addWidget(panel)

    view = QWebEngineView(dlg)
    view.load(QUrl("https://microsoft.com/link"))
    v.addWidget(view, 1)

    poll_timer = QTimer(dlg)
    poll_timer.setInterval(interval * 1000)

    def poll_device_code():
        try:
            pr = requests.post(
                f"{AUTHORITY}/token",
                data={
                    "grant_type":
                        "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": CLIENT_ID,
                    "device_code": device_code,
                },
                timeout=15,
            )
            if pr.status_code == 200:
                device_result["token"] = pr.json()
                QTimer.singleShot(0, dlg.accept)
                return
            err = pr.json().get("error", "")
            if err in ("authorization_pending", "slow_down"):
                return
            log("warn", f"device-code poll: {err}")
        except Exception:
            pass

    poll_timer.timeout.connect(poll_device_code)
    poll_timer.start()

    log("info", "opening sign-in window…")
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    poll_timer.stop()

    if not accepted:
        log("warn", "sign-in cancelled")
        return None

    if device_result["token"]:
        tok = device_result["token"]
        acc = Account()
        acc.access_token = tok["access_token"]
        acc.refresh_token = tok.get("refresh_token", "")
        acc._xbox_and_minecraft()
        return acc

    raise AuthError("no token returned")
