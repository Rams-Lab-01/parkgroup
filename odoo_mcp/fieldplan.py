"""Dynamic field planning: which columns the exporters should request.

Why dynamic
-----------
This database is heavily customised - real-estate, brokerage, loan, PD-cheque and
Studio modules all add fields to ``account.move`` / ``account.move.line`` /
``account.payment``.  A hardcoded field list silently drops all of them, so the
exporters must request whatever the live schema actually offers.

Custom-field detection
----------------------
A field is custom when **every** module that defines it is non-core, or when it
carries the Studio ``x_`` prefix.  Caveat, stated plainly: a field can be *core*
yet *extended* by a custom module (``account.move.state`` is touched by
``vendor_bill_customization``), and such a field is reported as custom here.
That is harmless, because classification is **annotation only** - exports
request every exportable field regardless of classification, so nothing is ever
dropped because we failed to classify it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from pgre_client import OdooClient, OdooError

PLAN_PATH = Path("field_plan.json")

DEFAULT_MODELS: tuple[str, ...] = (
    "account.move", "account.move.line", "account.payment", "account.journal",
    "account.account", "account.tax", "account.payment.term",
    "account.analytic.account", "res.partner", "res.company", "res.users",
    "product.product", "product.template",
)

# Odoo 18 official module technical names. Anything outside this set that
# defines a field makes that field custom. Keep in sync when upgrading.
CORE_MODULES: frozenset[str] = frozenset({
    "base", "base_setup", "base_automation", "web", "web_editor", "portal",
    "mail", "mail_thread", "mail_disable_manager", "sms", "phone_validation",
    "contacts", "digest", "bus", "web_tour", "web_gantt", "web_calendar",
    "web_list", "web_view", "web_kanban", "web_graph", "web_client",
    "account", "account_accountant", "account_debit_note", "account_followup",
    "account_payment", "account_asset", "account_check", "account_edi",
    "account_reports", "account_sepa", "account_banking", "account_transfer",
    "account_qr_code_sepa", "account_payment_term", "account_accountant_reports",
    "sale", "sale_management", "sale_stock", "sale_pdf",
    "purchase", "purchase_stock", "purchase_manage", "purchase_pdf",
    "stock", "stock_account", "stock_landed_costs", "stock_picking_batch",
    "stock_delivery", "stock_barcode", "stock_dashboard", "product",
    "uom", "delivery", "rating", "crm", "project", "hr", "resource",
    "employee", "hr_timesheet", "website", "website_form", "website_sale",
    "website_sale_manage", "analytic", "survey", "im_livechat", "utm",
    "auth_signup", "auth_totp", "base_import", "base_export", "base_location",
    "base_geo", "base_calendar", "base_hierarchy", "base_privacy",
    "base_security", "l10n_generic_coa", "account_chart_templates",
    "product_pricelist", "repair", "quality", "point_of_sale", "mrp",
})

#: Types never exported (binary blobs).
SKIP_TYPES: frozenset[str] = frozenset({"binary"})

#: Name fragments marking chatter / UI-widget / magic fields that bloat exports.
SKIP_NAME_HINTS: tuple[str, ...] = (
    "_widget", "_statusbar", "_kanban_state", "_attachment", "_message",
    "_mail_", "_track_", "_rating", "_activity", "_checklist", "_stat",
    "image_", "_placeholder", "_warning", "_order", "_display_name",
    "display_name", "has_message", "message_", "website_published",
    "starred_message", "_icon", "_color", "_priority", "_access",
    "_cron", "_sql", "_process", "_unlink", "_read_group", "_smtp",
)

#: Relation types excluded unless explicitly requested (large, usually derivable).
HEAVY_RELATIONS: frozenset[str] = frozenset({"one2many", "many2many"})


def _as_names(value: Any) -> list[str]:
    """Normalise an m2m read into a list of technical names.

    Odoo may return ``[[4, 'account'], [7, 'sale']]``, a bare string
    ``'account'``, or ``False``. Sorting a raw string would iterate its
    characters, so normalise first.
    """
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    names: list[str] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            names.append(str(item[1]))
        elif isinstance(item, str):
            names.append(item)
        else:
            names.append(str(item))
    return sorted(set(names))


def is_exportable(name: str, meta: dict[str, Any], *, include_heavy: bool = False) -> str | None:
    """Return ``None`` when exportable, else the reason it was skipped."""
    ftype = str(meta.get("type") or "")
    if ftype in SKIP_TYPES:
        return f"binary"
    if any(h in name for h in SKIP_NAME_HINTS):
        return "chatter/widget"
    if ftype in HEAVY_RELATIONS and not include_heavy:
        return f"{ftype} (use include_heavy)"
    return None


def classify(name: str, meta: dict[str, Any],
             defs: dict[str, dict[str, Any]]) -> tuple[str, str | None]:
    """Return ``(classification, defining_module)``.

    classification is ``custom``, ``standard`` or ``unknown``.
    """
    if name.startswith("x_"):
        return "custom", "studio"
    d = defs.get(name)
    if not d:
        return "standard", None          # framework/base field, not in ir_model_fields
    defining = d.get("modules") or []
    if not defining:
        return "unknown", None
    non_core = [m for m in defining if m not in CORE_MODULES]
    if non_core:
        return "custom", ",".join(non_core)
    return "standard", ",".join(defining)


def installed_modules(client: OdooClient) -> dict[str, dict[str, Any]]:
    """Installed (or being-upgraded) modules keyed by technical name."""
    rows = client.search_read(
        "ir.module.module",
        [("state", "in", ["installed", "to upgrade"])],
        ["name", "shortdesc", "application", "state"], limit=0)
    return {r["name"]: r for r in rows if r.get("name")}


def field_definitions(client: OdooClient, model: str) -> dict[str, dict[str, Any]]:
    """name -> metadata from ``ir.model.fields`` for one model."""
    rows = client.search_read(
        "ir.model.fields", [("model", "=", model)],
        ["name", "ttype", "field_description", "modules", "relation", "store"],
        limit=0)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not r.get("name"):
            continue
        rel = r.get("relation")
        out[r["name"]] = {
            "ttype": r.get("ttype"),
            "label": r.get("field_description"),
            "modules": _as_names(r.get("modules")),
            "relation": (rel[1] if isinstance(rel, (list, tuple)) and len(rel) >= 2 else rel),
            "store": r.get("store"),
        }
    return out


def build_plan(
    client: OdooClient,
    models: Iterable[str] = DEFAULT_MODELS,
    *,
    include_heavy: bool = False,
) -> dict[str, Any]:
    """Discover the full export field plan from the live database."""
    installed = installed_modules(client)
    non_core = sorted(m for m in installed if m not in CORE_MODULES)

    plan: dict[str, Any] = {
        "database": client.db,
        "server_version": client.about().get("server_version"),
        "include_heavy": include_heavy,
        "installed_modules": len(installed),
        "non_core_modules": non_core,
        "models": {},
    }

    for model in models:
        try:
            fields_all = client.fields_get(model, attributes=["type", "string", "relation"])
        except OdooError:
            continue
        defs = field_definitions(client, model)

        exportable: list[str] = []
        custom: list[dict[str, Any]] = []
        skipped: dict[str, str] = {}

        for name, meta in sorted(fields_all.items()):
            reason = is_exportable(name, meta, include_heavy=include_heavy)
            if reason:
                skipped[name] = reason
                continue
            exportable.append(name)
            klass, module = classify(name, meta, defs)
            if klass == "custom":
                custom.append({"name": name, "type": meta.get("type"),
                               "label": meta.get("string"), "module": module})

        plan["models"][model] = {
            "total_fields": len(fields_all),
            "exportable": exportable,
            "custom_fields": custom,
            "custom_count": len(custom),
            "skipped": skipped,
        }

    plan["total_custom_fields"] = sum(
        v.get("custom_count", 0) for v in plan["models"].values())
    return plan


def save_plan(plan: dict[str, Any], path: Path | str = PLAN_PATH) -> Path:
    p = Path(path)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, default=str)
    return p


def load_plan(path: Path | str = PLAN_PATH) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) and "models" in data else None


def ensure_plan(
    client: OdooClient,
    models: Iterable[str] = DEFAULT_MODELS,
    path: Path | str = PLAN_PATH,
    *,
    include_heavy: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Load the cached field plan, or build it from the live database.

    Caching matters: discovery costs one ``fields_get`` plus one
    ``ir.model.fields`` read per model, and the exporters call this once per run.
    """
    if not refresh:
        cached = load_plan(path)
        if cached and not include_heavy:
            return cached
    plan = build_plan(client, models, include_heavy=include_heavy)
    save_plan(plan, path)
    return plan


def fields_for(plan: dict[str, Any], model: str, fallback: Iterable[str] = ()) -> list[str]:
    """Exportable field list for ``model``, falling back when unplanned."""
    entry = (plan.get("models") or {}).get(model) or {}
    fields = list(entry.get("exportable") or [])
    if not fields:
        fields = [f for f in fallback if f != "id"]
    if "id" not in fields:
        fields.insert(0, "id")
    return fields


def custom_fields_for(plan: dict[str, Any], model: str) -> list[dict[str, Any]]:
    entry = (plan.get("models") or {}).get(model) or {}
    return list(entry.get("custom_fields") or [])


def custom_field_names(plan: dict[str, Any], model: str) -> set[str]:
    return {c["name"] for c in custom_fields_for(plan, model)}


def summary(plan: dict[str, Any]) -> str:
    lines = []
    for model, entry in (plan.get("models") or {}).items():
        lines.append(f"  {model:<26} {entry.get('total_fields', 0):>4} total  "
                     f"{len(entry.get('exportable') or []):>4} exportable  "
                     f"{entry.get('custom_count', 0):>4} custom")
    return "\n".join(lines)