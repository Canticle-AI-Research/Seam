"""Registry-driven Settings screen: every SEAM env var, editable in one place.

Nothing here is hardcoded per variable. The screen walks `config.SETTINGS` and
picks a widget from each row's `kind`, so adding a knob to the registry is the
whole job of making it settable.

Two behaviours are deliberate and worth stating, because both are easy to get
wrong in a way that only hurts later:

* A value inherited from the process environment is shown, badged `env`, and
  saving does not silently rewrite it into the settings file. Env wins at
  runtime; a UI that pretended otherwise would show one value and run another.
* Secrets render masked and are only sent back to the file if the operator
  actually edits them. An untouched secret field round-trips its stored value
  rather than the mask.
"""

from __future__ import annotations

import re
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from .. import config
from .keys import SeamInput

__all__ = ["SettingsPanel"]

#: Sentinel shown in a secret field that has a stored value the operator has
#: not edited. Submitting it unchanged means "keep what is stored".
_UNCHANGED = "••••••••"

#: Textual's "nothing selected" sentinel. It was renamed `BLANK` -> `NULL`, and
#: the old name now evaluates to `False`, which `Select` rejects as a value.
#: Resolved once here so the screen works across both spellings.
_NO_SELECTION = getattr(Select, "NULL", getattr(Select, "BLANK", None))


#: Every character Textual will not accept inside a widget id.
_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _slug(group: str) -> str:
    """Return a DOM-safe id fragment for a group name."""
    return _ID_SAFE.sub("-", group.replace("&", "and").lower())


class SettingRow(Horizontal):
    """One registry row rendered as label + source badge + editor."""

    def __init__(self, setting: config.Setting) -> None:
        super().__init__(classes="settings-row")
        self.setting = setting
        self._editor: Any = None

    def compose(self) -> ComposeResult:
        setting = self.setting
        source = config.value_source(setting.name)
        current = config.effective_value(setting.name)

        label_class = "settings-name-secret" if setting.secret else "settings-name"
        yield Label(setting.name, classes=label_class)
        yield Static(source, classes=f"badge-{source}")

        if setting.kind == "bool":
            switch = Switch(value=current.strip().lower() in {"1", "true", "yes", "on"})
            switch.id = self._widget_id
            self._editor = switch
            yield switch
            return

        choices = setting.resolved_choices() if setting.kind == "enum" else ()
        if choices:
            options = [(c or "(unset)", c) for c in choices if c]
            if current and current not in choices:
                # An out-of-vocabulary current value must stay visible rather
                # than being silently coerced to the first legal choice. Empty
                # is not out-of-vocabulary -- it is "unset", which the blank
                # option already represents.
                options.insert(0, (f"{current} (current)", current))
            select: Any = Select(
                options, value=current if current else _NO_SELECTION,
                allow_blank=True, id=self._widget_id, classes="settings-input",
            )
            self._editor = select
            yield select
            return

        display = _UNCHANGED if (setting.secret and current) else current
        field = SeamInput(
            value=display,
            placeholder=setting.placeholder or setting.default,
            password=bool(setting.secret),
            id=self._widget_id,
            classes="settings-input",
        )
        self._editor = field
        yield field

    @property
    def _widget_id(self) -> str:
        # Textual rejects an id containing anything but letters, digits, `_`
        # and `-`, and raises at construction -- which takes down the whole
        # app at mount, not just this row. Setting names reaching here can
        # come from the hand-edited config file, so every other character is
        # folded to `-` rather than trusted.
        slug = _ID_SAFE.sub("-", self.setting.name.replace("_", "-").lower())
        return f"set-{slug}"

    def raw_value(self) -> str:
        """Return the editor's current value as a string."""
        editor = self._editor
        if editor is None:
            return ""
        if isinstance(editor, Switch):
            return "1" if editor.value else ""
        value = getattr(editor, "value", "")
        if value is _NO_SELECTION or value is None or isinstance(value, bool):
            return ""
        return str(value)

    def is_untouched_secret(self) -> bool:
        """Return whether this is a secret the operator left alone."""
        return bool(self.setting.secret) and self.raw_value() == _UNCHANGED

    def set_invalid(self, message: str) -> None:
        """Mark the editor invalid and surface ``message``."""
        if self._editor is not None and hasattr(self._editor, "add_class"):
            self._editor.add_class("-invalid")
        self.tooltip = message

    def clear_invalid(self) -> None:
        if self._editor is not None and hasattr(self._editor, "remove_class"):
            self._editor.remove_class("-invalid")
        self.tooltip = self.setting.description or None


class SettingsPanel(Vertical):
    """Scrollable, searchable view over the entire settings registry."""

    def compose(self) -> ComposeResult:
        yield SeamInput(
            placeholder="Filter settings…  (name, description, or group)",
            id="settings-search",
        )
        with VerticalScroll(id="settings-body"):
            for group in config.GROUPS:
                rows = config.settings_in_group(group)
                if group == "Custom Keys":
                    rows = config.custom_settings()
                if not rows and group != "Custom Keys":
                    continue
                yield Static(f"── {group} ", classes="settings-group",
                             id=f"group-{_slug(group)}")
                for setting in rows:
                    row = SettingRow(setting)
                    yield row
                    if setting.description:
                        yield Static(setting.description, classes="settings-help")
                if group == "Custom Keys":
                    yield from self._compose_add_key()
        with Horizontal(id="settings-actions"):
            yield Button("Save", id="settings-save", classes="-primary")
            yield Button("Reload", id="settings-reload")
            yield Static("", id="settings-status")

    def _compose_add_key(self) -> ComposeResult:
        """Render the form for adding a variable SEAM does not ship."""
        with Horizontal(classes="settings-row", id="add-key-row"):
            yield SeamInput(placeholder="NEW_PROVIDER_API_KEY", id="add-key-name",
                        classes="settings-input")
            yield SeamInput(placeholder="value", password=True, id="add-key-value",
                        classes="settings-input")
            yield Button("Add", id="add-key-btn")
        yield Static(
            "Add any environment variable. Names containing KEY, TOKEN, SECRET, "
            "PASSWORD, DSN, or CREDENTIAL are masked automatically.",
            classes="settings-help",
        )

    @on(Button.Pressed, "#add-key-btn")
    def _add_key(self) -> None:
        name_field = self.query_one("#add-key-name", Input)
        value_field = self.query_one("#add-key-value", Input)
        status = self.query_one("#settings-status", Static)

        name = name_field.value.strip()
        ok, message = config.valid_custom_name(name)
        if not ok:
            status.update(f"[b]{name or 'name'}[/b] — {message}")
            return
        if not value_field.value:
            status.update(f"[b]{name}[/b] — value is required")
            return

        stored = config.load_persisted()
        stored[name] = value_field.value
        try:
            config.save_persisted(stored)
        except OSError as exc:
            status.update(f"[b]Save failed[/b] — {exc}")
            return

        name_field.value = ""
        value_field.value = ""
        status.update(f"Added {name}. It appears under Custom Keys on next open.")

    # -- filtering ---------------------------------------------------------

    @on(Input.Changed, "#settings-search")
    def _filter(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        visible_groups: set[str] = set()

        for row in self.query(SettingRow):
            setting = row.setting
            hit = (
                not query
                or query in setting.name.lower()
                or query in setting.description.lower()
                or query in setting.group.lower()
            )
            row.display = hit
            help_text = row.next_sibling
            if isinstance(help_text, Static) and "settings-help" in help_text.classes:
                help_text.display = hit
            if hit:
                visible_groups.add(setting.group)

        for group in config.GROUPS:
            try:
                header = self.query_one(f"#group-{_slug(group)}", Static)
            except Exception:
                continue
            header.display = group in visible_groups

    # -- actions -----------------------------------------------------------

    @on(Button.Pressed, "#settings-save")
    def _save(self) -> None:
        stored = config.load_persisted()
        pending: dict[str, str] = {}
        errors: list[str] = []

        for row in self.query(SettingRow):
            setting = row.setting
            row.clear_invalid()

            if row.is_untouched_secret():
                existing = stored.get(setting.name, "")
                if existing:
                    pending[setting.name] = existing
                continue

            raw = row.raw_value()
            ok, message = config.validate(setting, raw)
            if not ok:
                row.set_invalid(message)
                errors.append(f"{setting.name}: {message}")
                continue

            # A value inherited from the environment is not ours to persist:
            # writing it back would freeze a transient shell override into the
            # user's config file.
            if config.value_source(setting.name) == "env" and raw == config.effective_value(setting.name):
                continue
            if raw:
                pending[setting.name] = raw

        status = self.query_one("#settings-status", Static)
        if errors:
            status.update(f"[b]{len(errors)} invalid[/b] — {errors[0]}")
            return

        try:
            path = config.save_persisted(pending)
        except OSError as exc:
            status.update(f"[b]Save failed[/b] — {exc}")
            return
        status.update(f"Saved {len(pending)} settings → {path} (0600)")

    @on(Button.Pressed, "#settings-reload")
    def _reload(self) -> None:
        applied = config.apply_persisted_to_environ()
        status = self.query_one("#settings-status", Static)
        status.update(
            f"Applied {len(applied)} setting(s) to this process. "
            "Values already in the environment were left as-is."
        )


class SettingsScreen(Screen):
    """Full-screen settings view, used when the panel is opened standalone."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield SettingsPanel()
