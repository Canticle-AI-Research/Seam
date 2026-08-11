"""What `alt+1`..`alt+9` actually arrive as, and the Input that lets them through.

Terminals using the classic "Alt sends Escape" convention -- xterm and its
many descendants, and `tmux send-keys M-3` -- send `ESC` followed by the
digit rather than a distinct modified keycode. textual's
`ANSI_SEQUENCES_KEYS` resolves that pair to the macOS Option-digit
character, so `alt+3` is delivered as the ordinary printable key
`pound_sign` and is typed into the focused field as a literal `£` instead of
switching tabs.

Binding those characters is necessary but not sufficient. `Screen._binding_chain`
deletes every App-level binding whose key the focused widget reports it would
consume, and it does so *before* `App._check_bindings(priority=True)` runs, so
a `priority=True` binding cannot outrank a focused `Input` for a printable
key the way `ctrl+right` outranks it for a non-printable one. Declining to
consume those nine keys is the only hook that runs early enough.
"""

from __future__ import annotations

from textual.widgets import Input

#: Indexed by tab number minus one. Verified against textual 8.2.8 by feeding
#: `"\x1b" + digit` to `XTermParser`; `test_tui_input_modes.py` asserts this
#: transcription against the parser so a textual upgrade that renames a key
#: fails loudly instead of silently un-fixing the defect.
META_DIGIT_KEYS: tuple[str, ...] = (
    "inverted_exclamation_mark",  # alt+1  ¡
    "trade_mark_sign",  # alt+2  ™
    "pound_sign",  # alt+3  £
    "cent_sign",  # alt+4  ¢
    "infinity",  # alt+5  ∞
    "section_sign",  # alt+6  §
    "pilcrow_sign",  # alt+7  ¶
    "bullet",  # alt+8  •
    "ª",  # alt+9  ª  (textual leaves this one as the character itself)
)


class SeamInput(Input):
    """`Input` that yields the `META_DIGIT_KEYS` back to the app's tab jumps.

    Every `Input` the TUI mounts uses this, because "alt+3 switches to the
    third tab" should not depend on which field happens to hold focus.

    Nothing above textual's parser can distinguish `alt+3` on an xterm from a
    UK keyboard's genuine `shift+3` -- both arrive as `pound_sign` carrying
    `£`. `SEAM_TUI_META_DIGITS=off` clears `App.meta_digits_jump`, at which
    point this consumes the characters normally again and only real `alt+N`
    jumps.
    """

    def check_consume_key(self, key: str, character: str | None) -> bool:
        if key in META_DIGIT_KEYS and self._meta_digits_jump():
            return False
        return super().check_consume_key(key, character)

    def _meta_digits_jump(self) -> bool:
        try:
            app = self.app
        except Exception:
            # Unmounted, so there is no App binding to protect and no
            # binding chain being built; consume as an ordinary Input.
            return False
        return bool(getattr(app, "meta_digits_jump", False))
