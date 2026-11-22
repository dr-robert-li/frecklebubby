"""Plug-ins: extra Python packages that are installed with the app.

A plug-in is a package with an entry point in the group "frecklebubby.plugins". The entry point is a function that
gets the registry:

    def setup(reg):
        reg.setting("my_option", "A label", "Text that tells the parent what the option does.")
        reg.notice("my_message", "A title", "Text that the family owner sees one time.")
        reg.on("cry_analyzed", keep)      # keep(family_id=, child_id=, user_id=, samples=, result=)
        reg.router(my_router)             # a FastAPI router, added below /api/v1

Events:
    cry_analyzed    a recording of the cry helper was analysed. samples: mono float32 at 16 kHz, at most
                    cry.MAX_SECONDS long. The app itself keeps no audio.
    entry_saved     an entry was made or changed (entry=).
    entry_deleted   one entry was deleted (entry=). A deleted child or family deletes its entries with no event
                    for each entry.
    child_deleted   a child was deleted with all its entries (child_id=, family_id=).
    family_deleted  a family was deleted with all its data (family_id=).

A setting is a checkbox for the family. The app shows it in Settings and keeps the value; read it with enabled().
With no plug-in, the registry is empty and the app shows and keeps nothing more.
"""

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from typing import Any

from sqlalchemy.orm import Session

from .models import Family
from .services import Ctx, NotFound

log = logging.getLogger(__name__)
GROUP = "frecklebubby.plugins"


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    text: str
    default: bool = True


@dataclass(frozen=True)
class Notice:
    key: str
    title: str
    text: str


@dataclass
class Registry:
    settings: list[Setting] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    routers: list[Any] = field(default_factory=list)
    hooks: dict[str, list[Callable[..., None]]] = field(default_factory=dict)
    loaded: bool = False

    def setting(self, key: str, label: str, text: str, default: bool = True) -> None:
        self.settings.append(Setting(key, label, text, default))

    def notice(self, key: str, title: str, text: str) -> None:
        self.notices.append(Notice(key, title, text))

    def router(self, router: Any) -> None:
        self.routers.append(router)

    def on(self, event: str, fn: Callable[..., None]) -> None:
        self.hooks.setdefault(event, []).append(fn)

    def emit(self, event: str, **data: Any) -> None:
        """A fault in a plug-in must not break the request of the parent."""
        for fn in self.hooks.get(event, []):
            try:
                fn(**data)
            except Exception:
                log.exception("Plug-in hook for %s failed", event)

    @property
    def active(self) -> bool:
        return bool(self.settings or self.notices)


registry = Registry()


def load() -> None:
    if registry.loaded:
        return
    registry.loaded = True
    for ep in entry_points(group=GROUP):
        ep.load()(registry)
        log.info("Plug-in loaded: %s", ep.name)


def enabled(family: Family, key: str) -> bool:
    """The value of a plug-in setting for this family."""
    default = next((x.default for x in registry.settings if x.key == key), False)
    return bool(family.settings.get("plugins", {}).get(key, default))


def state(ctx: Ctx) -> dict:
    """The settings with their values, and the notices that the family owner has not seen. Carers get no notice."""
    seen = ctx.fam.settings.get("plugin_notices_seen", [])
    notices = [asdict(n) for n in registry.notices if n.key not in seen] if ctx.role == "owner" else []
    return {"settings": [{**asdict(x), "value": enabled(ctx.fam, x.key)} for x in registry.settings],
            "notices": notices}


def _save(s: Session, ctx: Ctx, **changes: Any) -> dict:
    ctx.fam.settings = {**ctx.fam.settings, **changes}  # new dict so SQLAlchemy sees the change
    s.commit()
    return state(ctx)


def set_value(s: Session, ctx: Ctx, key: str, value: bool) -> dict:
    ctx.require_owner()
    if not any(x.key == key for x in registry.settings):
        raise NotFound("Setting not found.")
    return _save(s, ctx, plugins={**ctx.fam.settings.get("plugins", {}), key: value})


def mark_seen(s: Session, ctx: Ctx, key: str) -> dict:
    ctx.require_owner()
    if not any(n.key == key for n in registry.notices):
        raise NotFound("Notice not found.")
    seen = ctx.fam.settings.get("plugin_notices_seen", [])
    return _save(s, ctx, plugin_notices_seen=sorted({*seen, key}))
