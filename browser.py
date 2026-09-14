"""Playwright tools with a minimal semantic view and context-wide policy guard."""
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from outcomes import HardFailure, RecoverableError, PolicyBlocked
from policy import Policy
from surface import CONTROLS, ROUTES

class ControlNotFound(RecoverableError):
    pass

class AmbiguousControl(HardFailure):
    pass

class Browser:
    def __init__(self, base_url="http://127.0.0.1:8000", headless=True, timeout=3000, policy=None):
        self.base_url = base_url.rstrip("/")
        self.headless, self.timeout = headless, timeout
        self.policy = policy or Policy(allowed_domains=[urlsplit(self.base_url).netloc])
        self.owner = "automation"
        self.violation = None
        self.problem = None
        self.human_events = []
        self._pw = self._browser = self.page = self.context = None

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self.context = self._browser.new_context(service_workers="block", accept_downloads=False)
        self.context.set_default_timeout(self.timeout)
        self.context.set_default_navigation_timeout(self.timeout)
        self.context.route("**/*", self._guard_request)
        self.context.route_web_socket("**/*", lambda ws: ws.close())
        self.context.on("page", self._new_page)
        self.context.expose_binding("recordHumanAction", self._human_event)
        # Serialize only a closed semantic ID. Never capture text, values, HTML or URLs.
        import json
        selectors = json.dumps({key: val[0] for key, val in CONTROLS.items()})
        self.context.add_init_script("""(() => {
          const selectors = SELECTORS;
          for (const kind of ['click', 'change']) document.addEventListener(kind, e => {
            if (!e.isTrusted) return;
            let control = 'unknown';
            for (const [key, selector] of Object.entries(selectors))
              if (e.target.closest(selector)) { control = key; break; }
            window.recordHumanAction({kind, control});
          }, true);
        })();""".replace("SELECTORS", selectors))
        self.page = self.context.new_page()
        return self

    def _new_page(self, page):
        if self.page is not None:
            self.violation = "new_tab_blocked"
            page.close()
            return
        page.on("dialog", self._dialog)
        page.on("download", lambda download: download.cancel())
        page.on("pageerror", lambda error: setattr(self, "problem", "application_error"))
        page.on("framenavigated", self._navigated)

    def _navigated(self, frame):
        if frame.parent_frame is not None:
            self.violation = "iframe_unsupported"
        if self.owner == "human":
            self.human_events.append({"kind": "navigation", "control": "route"})

    def _human_event(self, source, event):
        if self.owner != "human" or not isinstance(event, dict):
            return
        kind = event.get("kind")
        control = event.get("control")
        self.human_events.append({"kind": kind if kind in {"click", "change"} else "unknown",
                                  "control": control if control in CONTROLS else "unknown"})

    def _dialog(self, dialog):
        known = dialog.type == "alert" and dialog.message == "Session notice"
        dialog.dismiss()
        if not known:
            self.problem = "unknown_dialog"

    def _guard_request(self, route):
        request = route.request
        if not self.policy.url_allowed(request.url, self.base_url, request.method):
            self.violation = "prohibited_navigation"
            route.abort()
            return
        # Fetch redirects one hop at a time: every Location is independently
        # intercepted/validated. Raw responses never enter model or telemetry.
        try:
            response = route.fetch(max_redirects=0, timeout=self.timeout)
            if response.status >= 500:
                self.problem = "application_error"
            elif response.status == 403:
                self.problem = "permission_denied"
            route.fulfill(response=response)
        except Exception:
            self.problem = "network_failure"
            route.abort()

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self):
        try:
            return self.start()
        except Exception:
            self.stop()
            raise HardFailure("browser_unavailable") from None

    def __exit__(self, *exc):
        self.stop()

    def guard(self, acting=False):
        if acting and self.owner != "automation":
            raise HardFailure("automation_paused")
        if not self.page or self.page.is_closed():
            raise HardFailure("browser_closed")
        if self.violation:
            raise PolicyBlocked(self.violation)
        if self.problem == "permission_denied":
            raise HardFailure("permission_denied")
        if self.problem:
            raise RecoverableError(self.problem)
        if len(self.page.frames) != 1:
            raise HardFailure("iframe_unsupported")
        if self.page.url != "about:blank" and not self.policy.url_allowed(self.page.url, self.base_url):
            raise PolicyBlocked("prohibited_navigation")

    def _route(self):
        return urlsplit(self.page.url).path or "/"

    def goto(self, path="/"):
        self.guard(acting=True)
        url = self.base_url + path
        if not self.policy.url_allowed(url, self.base_url):
            raise PolicyBlocked("prohibited_navigation")
        self.page.goto(url, wait_until="domcontentloaded")
        self.guard()

    def resolve(self, target, by="css", visible=True):
        if by == "css":
            loc = self.page.locator(target)
        elif by == "label":
            loc = self.page.get_by_label(target, exact=True)
        elif by == "text":
            loc = self.page.get_by_text(target, exact=True)
        else:
            raise HardFailure("invalid_locator")
        # Never pick .first or use positional fallback, including hidden duplicates.
        if loc.count() > 1:
            raise AmbiguousControl("ambiguous_control")
        if loc.count() == 0:
            raise ControlNotFound("missing_control")
        if visible and not loc.is_visible():
            raise ControlNotFound("hidden_control")
        if not loc.is_enabled():
            raise ControlNotFound("disabled_control")
        return loc

    def observe(self, sanitize=True):
        self.guard()
        if not sanitize:
            raise HardFailure("raw_observation_disabled")
        route = ROUTES.get(self._route(), "unknown")
        controls = []
        for key, (selector, label) in CONTROLS.items():
            loc = self.page.locator(selector)
            if loc.count():
                if loc.count() > 1:
                    raise AmbiguousControl("ambiguous_control")
                controls.append({"id": key, "label": label,
                                 "visible": loc.is_visible(), "enabled": loc.is_enabled()})
        return {"surface_version": 1, "route": route, "controls": controls,
                "untrusted_page_data": True}

    def click(self, target, by="text", index=None):
        self.guard(acting=True)
        if index is not None:
            raise AmbiguousControl("positional_locator_denied")
        self.resolve(target, by).click(timeout=self.timeout)
        self.guard()

    def fill(self, target, value, by="css"):
        self.guard(acting=True)
        self.resolve(target, by).fill(value, timeout=self.timeout)
        self.guard()

    def wait_for(self, target, by="text", timeout=None):
        self.guard(acting=True)
        try:
            # Locator resolution is repeated after the bounded wait, so duplicates
            # or a late hidden replacement cannot be silently accepted.
            loc = self.page.locator(target) if by == "css" else self.page.get_by_text(target, exact=True)
            loc.wait_for(state="visible", timeout=timeout or self.timeout)
            self.resolve(target, by)
            self.guard()
            return True
        except PlaywrightTimeout:
            return False

    def extract(self, target, by="css"):
        self.guard(acting=True)
        return self.resolve(target, by).inner_text(timeout=self.timeout).strip()

    def check(self, target, by="text"):
        self.guard()
        self.resolve(target, by)
        return True

    def backend_state(self):
        self.guard()
        try:
            response = self.context.request.get(self.base_url + "/api/session",
                                                timeout=self.timeout, max_redirects=0)
            if response.status == 401:
                raise RecoverableError("session_expired")
            if response.status != 200:
                raise HardFailure("verification_failed")
            return response.json()
        except (RecoverableError, HardFailure):
            raise
        except Exception:
            raise RecoverableError("verification_unavailable") from None
