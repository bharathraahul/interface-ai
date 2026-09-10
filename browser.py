"""Browser interaction layer.

A thin wrapper over Playwright that gives the backend six primitive tools for
driving a web UI:

    observe()   -> see the current page (url, title, text, clickable controls)
    click()     -> click an identified control
    fill()      -> type a value into a field
    wait_for()  -> block until a UI condition is true
    extract()   -> read a value out of the page
    check()     -> confirm the expected state was reached

Controls can be identified two ways (the `by` argument):
    by="text"  -> human-visible label, e.g. "Platinum Credit Card"  (default)
    by="css"   -> a CSS selector, e.g. '[data-field="payment-due"]'
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# What counts as an actionable control. Text that isn't inside one of these
# (headings, banners, labels) is never a click target — this is the core
# disambiguation rule that keeps a text match from hitting decorative copy.
CLICKABLE = "a, button, [role=button], input[type=button], input[type=submit]"


class ControlNotFound(Exception):
    """No control matched the identifier."""


class AmbiguousControl(Exception):
    """Several equally-specific controls matched; caller must narrow it down."""


class Browser:
    def __init__(self, base_url="http://127.0.0.1:8000", headless=True, timeout=5000):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout = timeout          # default wait, in milliseconds
        self._pw = None
        self._browser = None
        self.page = None

    # --- lifecycle -------------------------------------------------------
    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self.page = self._browser.new_page()
        return self

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def goto(self, path="/"):
        self.page.goto(self.base_url + path)

    # --- internal helpers ------------------------------------------------
    def _locate(self, target, by):
        """Return a Playwright locator for reading (extract/check/wait)."""
        if by == "css":
            return self.page.locator(target)
        if by == "label":
            return self.page.get_by_label(target)
        return self.page.get_by_text(target, exact=False)

    def _resolve_click(self, target, index):
        """Apply the disambiguation rules and return one control to click.

        Rules, in order:
          1. Only interactive controls are candidates (CLICKABLE).
          2. Only visible ones.
          3. If the caller passed an explicit `index`, use it.
          4. If exactly one candidate, use it.
          5. Otherwise prefer the most specific — the control whose own text is
             shortest (least surrounding chrome).
          6. If several are equally specific, refuse and report the choices.
        """
        loc = self.page.locator(CLICKABLE).filter(has_text=target)
        candidates = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]

        if not candidates:
            raise ControlNotFound(f"No clickable control matching {target!r}")
        if index is not None:
            return candidates[index]
        if len(candidates) == 1:
            return candidates[0]

        candidates.sort(key=lambda el: len(el.inner_text().strip()))
        shortest = len(candidates[0].inner_text().strip())
        tied = [c for c in candidates if len(c.inner_text().strip()) == shortest]
        if len(tied) > 1:
            texts = [c.inner_text().strip() for c in candidates]
            raise AmbiguousControl(
                f"{target!r} matched {len(candidates)} controls: {texts}. "
                f"Pass index= to choose."
            )
        return candidates[0]

    # --- the six tools ---------------------------------------------------
    def observe(self):
        """Snapshot the current page: what it is and what can be acted on.

        `controls` lists the actionable elements with an index, so a caller can
        disambiguate by passing that index back to click().
        """
        loc = self.page.locator(CLICKABLE)
        controls = []
        for i in range(loc.count()):
            el = loc.nth(i)
            if not el.is_visible():
                continue
            controls.append({
                "index": len(controls),
                "text": (el.inner_text() or "").strip(),
                "tag": el.evaluate("e => e.tagName.toLowerCase()"),
                "href": el.get_attribute("href"),
            })
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "text": self.page.locator("body").inner_text().strip(),
            "controls": controls,
        }

    def click(self, target, by="text", index=None):
        """Click an identified control.

        by="text" (default) applies the disambiguation rules above.
        by="css"  clicks the first match of an explicit selector, as given.
        `index` forces a specific candidate when text matches several.
        """
        if by == "css":
            self.page.locator(target).first.click(timeout=self.timeout)
            return
        self._resolve_click(target, index).click(timeout=self.timeout)

    def fill(self, target, value, by="label"):
        """Type `value` into an identified field."""
        self._locate(target, by).first.fill(value, timeout=self.timeout)

    def wait_for(self, target, by="text", timeout=None):
        """Block until a control/condition is visible. Returns True/False."""
        try:
            self._locate(target, by).first.wait_for(
                state="visible", timeout=timeout or self.timeout
            )
            return True
        except PlaywrightTimeout:
            return False

    def extract(self, target, by="css"):
        """Read the text of an identified element. Returns None if absent."""
        locator = self._locate(target, by).first
        if locator.count() == 0:
            return None
        return locator.inner_text().strip()

    def check(self, target, by="text"):
        """Confirm the expected state exists on the page. Returns True/False."""
        return self._locate(target, by).count() > 0
