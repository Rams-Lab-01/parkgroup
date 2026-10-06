"""Static consistency checks for the sgc_escrow scaffold.

Catches the class of mistake that only shows up as an opaque Odoo install
failure: XML that is not well-formed, manifest entries pointing at files that
do not exist, view inheritance targets that are not declared, and security CSV
columns that do not match the model.
"""
import ast
import csv
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
problems = []


def fail(msg):
    problems.append(msg)


# -- 1. No HTML named entities in XML (they are not valid XML entities) ---
# &mdash; / &times; / &ldquo; are HTML named entities. XML has no such entity,
# so the parser behind view loading rejects the file. This scan runs BEFORE the
# well-formedness pass so the failure is reported as a clear message rather than
# as a bare ParseError traceback.
NAMED_ENTITY = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#)[a-zA-Z]+;")
for path in sorted(ROOT.rglob("*.xml")):
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        found = NAMED_ENTITY.search(line)
        if found:
            fail(f"{path.relative_to(ROOT)}:{lineno} uses the HTML named entity "
                 f"{found.group(0)}; XML has no such entity -- use the numeric "
                 f"character reference instead")

# -- 2. Every XML file is well-formed ---
# Parsed once and cached: the checks below need the trees, and re-parsing a file
# that section 1 already rejected would abort the whole run on a ParseError
# instead of reporting every problem found.
xml_files = sorted(ROOT.rglob("*.xml"))
XML_TREES = {}
for path in xml_files:
    try:
        XML_TREES[path] = ET.parse(path)
    except ET.ParseError as exc:
        fail(f"XML not well-formed: {path.relative_to(ROOT)}: {exc}")

# -- 3. Manifest parses and every listed file exists ---
manifest_path = ROOT / "__manifest__.py"
manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))

for key in ("name", "version", "license", "depends", "data"):
    if key not in manifest:
        fail(f"manifest missing required key: {key}")

if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+\.\d+", manifest["version"]):
    fail(f"manifest version is not an Odoo 5-part version: {manifest['version']}")

for entry in manifest["data"]:
    if not (ROOT / entry).is_file():
        fail(f"manifest data entry does not exist: {entry}")

# Every data file that exists should also be listed (catches forgotten wiring).
listed = set(manifest["data"])
for path in xml_files:
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("static/"):
        continue
    if rel not in listed and rel != manifest_path.name:
        # security/paperformat/report files must be declared; local override
        # files under a *_local/ dir are not expected in this scaffold.
        fail(f"XML file present but NOT in manifest data: {rel}")

# -- 4. No duplicate manifest entries ---
duplicates = {e for e in listed if list(manifest["data"]).count(e) > 1}
if duplicates:
    fail(f"duplicate manifest data entries: {sorted(duplicates)}")

def read_odoo_csv(path):
    """Parse an Odoo security CSV, honouring '#' comment lines like the loader does."""
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return list(csv.DictReader(lines))


# -- 5. ir.model.access.csv shape ---
acl_path = ROOT / "security" / "ir.model.access.csv"
acl_rows = read_odoo_csv(acl_path)
expected_acl = [
    "id", "name", "model_id:id", "group_id:id",
    "perm_read", "perm_write", "perm_create", "perm_unlink",
]
if list(acl_rows[0].keys()) != expected_acl:
    fail(f"ir.model.access.csv columns wrong: {list(acl_rows[0].keys())}")

# -- 6. ir.rule.csv shape ---
rule_path = ROOT / "security" / "ir.rule.csv"
rule_rows = read_odoo_csv(rule_path)
expected_rule = [
    "id", "name", "model_id:id", "domain_force",
    "perm_read", "perm_write", "perm_create", "perm_unlink",
]
if list(rule_rows[0].keys()) != expected_rule:
    fail(f"ir.rule.csv columns wrong: {list(rule_rows[0].keys())}")

# -- 7. Every model referenced by an ACL row is defined in this module ---
defined_models = set()
for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if (isinstance(target, ast.Name)
                                and target.id in ("_name", "_inherit")):
                            try:
                                value = ast.literal_eval(stmt.value)
                            except (ValueError, SyntaxError):
                                continue
                            for item in (value if isinstance(value, list) else [value]):
                                if isinstance(item, str) and "." in item:
                                    defined_models.add(item)

acl_xmlids = {row["model_id:id"] for row in acl_rows}
rule_xmlids = {row["model_id:id"] for row in rule_rows}

for xmlid in sorted(acl_xmlids | rule_xmlids):
    # Odoo builds model xmlids by replacing dots with underscores, so invert it.
    model_name = xmlid[len("model_"):].replace("_", ".")
    if model_name not in defined_models:
        fail(f"security references {xmlid} but the module does not define "
             f"model {model_name}")

# -- 8. Group references in XML resolve to groups declared in this module ---
declared_groups = set(re.findall(
    r'<record id="(group_escrow_\w+)"',
    (ROOT / "security" / "escrow_groups.xml").read_text(encoding="utf-8")))
referenced_groups = {}
# Security CSVs count too: an ACL row is the most likely place to name a group
# that was never declared, and omitting them let a phantom group through.
group_scan_files = (
    xml_files
    + list(ROOT.rglob("*.py"))
    + sorted((ROOT / "security").glob("*.csv"))
)
for path in group_scan_files:
    # Any sgc_escrow.group_* reference must resolve. Matching the bare `group_`
    # prefix (rather than the declared names) is deliberate: a typo'd group name
    # must be caught, and it would not match a name-specific pattern.
    for group in re.findall(
            r'sgc_escrow\.(group_\w+)', path.read_text(encoding="utf-8")):
        referenced_groups.setdefault(group, set()).add(path.relative_to(ROOT))
for group in sorted(set(referenced_groups) - declared_groups):
    where = ", ".join(sorted(str(p) for p in referenced_groups[group]))
    fail(f"references undeclared group sgc_escrow.{group} (in {where})")

# -- 9. env.ref() ids inside Python resolve to a declared record ---
declared_records = set()
for path in xml_files:
    text = path.read_text(encoding="utf-8")
    declared_records |= set(re.findall(r'<record id="([\w.]+)"', text))
    declared_records |= set(re.findall(r'<template id="([\w.]+)"', text))
    declared_records |= set(re.findall(r'<menuitem id="([\w.]+)"', text))
    declared_records |= set(re.findall(r'<act_window id="([\w.]+)"', text))

referenced_refs = set()
for path in ROOT.rglob("*.py"):
    for match in re.findall(
            r"(?:env\.ref|self\.env\.ref)\(\s*[\"']([\w.]+)[\"']",
            path.read_text(encoding="utf-8")):
        if match.startswith("sgc_escrow."):
            referenced_refs.add(match.removeprefix("sgc_escrow."))
for ref in sorted(referenced_refs - declared_records):
    fail(f"env.ref('sgc_escrow.{ref}') has no matching declared record")

# -- 10. Every <field name="x"> in a view for a model this module owns ---
# escrow.allocation, escrow.release, escrow.allocation.import and
# escrow.allocation.import.line are fully defined here, so every field their
# views reference must exist. This catches typos that otherwise only surface
# as an opaque install error.
OWNED_MODELS = {
    "escrow.allocation",
    "escrow.release",
    "escrow.allocation.import",
    "escrow.allocation.import.line",
}

owned_fields = {model: set() for model in OWNED_MODELS}
# Fields Odoo / base modules contribute to every model.
INHERITED = {
    "id", "display_name", "create_uid", "create_date", "write_uid", "write_date",
    "active", "company_id", "currency_id", "message_ids", "message_follower_ids",
    "message_main_attachment_id", "access_token", "__last_update",
}

for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Fields may be declared on the class that defines the model (_name) or
        # on a class that only extends it (_inherit) -- both are legal ways to
        # add a field, and Odoo resolves them identically.
        model_names = []
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id in ("_name", "_inherit"):
                    try:
                        value = ast.literal_eval(stmt.value)
                    except (ValueError, SyntaxError):
                        continue
                    for item in (value if isinstance(value, list) else [value]):
                        if isinstance(item, str) and "." in item:
                            model_names.append(item)
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id not in (
                            "_name", "_inherit", "_order", "_description",
                            "_rec_name", "_sql_constraints", "_description",
                            "_CONTROLLED_FIELDS",
                            "_audit_watched_fields", "_audit_excluded_fields",
                            "_audit_unlink_requires_reason",
                            "_audit_capture_points", "_audit_t1_commission_models",
                            "_audit_t1_commission_fields", "_audit_t1_webhook_model"):
                        for model in model_names:
                            if model in owned_fields:
                                owned_fields[model].add(target.id)

for path in xml_files:
    tree = XML_TREES.get(path)
    if tree is None:
        continue  # already reported as not well-formed
    for record in tree.iter("record"):
        if (record.get("model") or "") != "ir.ui.view":
            continue
        model_field = record.find("field[@name='model']")
        if model_field is None or (model_field.text or "").strip() not in owned_fields:
            continue
        model = model_field.text.strip()

        # Only the <field name="arch" type="xml"> subtree describes fields of the
        # model; the record's own metadata <field> children are not model fields.
        arch = None
        for child in record.findall("field"):
            if child.get("name") == "arch" and child.get("type") == "xml":
                arch = child
        if arch is None:
            continue

        def check(element, inside_relation):
            for child in element:
                if child.tag != "field":
                    check(child, inside_relation)
                    continue
                name = child.get("name")
                if not name:
                    continue
                # Descending into a relational field means the inner list/search
                # belongs to the comodel, not to this model.
                nested = inside_relation or child.get("type") in (
                    "one2many", "many2many")
                if nested:
                    check(child, True)
                    continue
                if "." in name or name in INHERITED or name.startswith("x_"):
                    continue
                if (name not in owned_fields[model]
                        and name not in defined_models):
                    fail(f"view for {model} references unknown field "
                         f"'{name}' ({path.relative_to(ROOT)})")

        check(arch, False)

# -- 11. No leftover Odoo<17 'states=' field attribute ---
for path in ROOT.rglob("*.py"):
    if path.name == pathlib.Path(__file__).name:
        continue  # this checker names the attribute in its own messages
    source = path.read_text(encoding="utf-8")
    code_lines = [
        line for line in source.splitlines()
        if not line.lstrip().startswith("#")
    ]
    for lineno, line in enumerate(code_lines, start=1):
        if re.search(r"\bstates\s*=", line):
            fail(f"{path.relative_to(ROOT)}:{lineno} uses the removed Odoo 17+ "
                 f"`states=` field attribute: {line.strip()}")

# -- 11. Compute overrides must not narrow the base dependency list ---
# Overriding a compute method in Odoo REPLACES its @api.depends rather than
# extending it. Narrowing it silently makes the recompute trigger go stale.
# These are the base triggers of the methods this module overrides.
BASE_COMPUTE_DEPENDS = {
    "_compute_journal_id": {"available_journal_ids"},
    "_compute_available_journal_ids": {"payment_type", "company_id", "can_edit_wizard"},
}
for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.FunctionDef)
                    and stmt.name in BASE_COMPUTE_DEPENDS):
                continue
            declared = set()
            for dec in stmt.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and getattr(dec.func, "attr", "") == "depends"):
                    continue
                # @api.depends may be given several positional string lists.
                for arg in dec.args:
                    try:
                        value = ast.literal_eval(arg)
                    except (ValueError, SyntaxError):
                        continue
                    if isinstance(value, str):
                        declared.add(value)
                    elif isinstance(value, (list, tuple, set)):
                        declared |= set(value)
            if not declared:
                fail(f"{path.relative_to(ROOT)} overrides {stmt.name} with no "
                     f"@api.depends -- the base triggers will be lost")
                continue
            missing = BASE_COMPUTE_DEPENDS[stmt.name] - declared
            if missing:
                fail(f"{path.relative_to(ROOT)}:{stmt.lineno} {stmt.name} drops "
                     f"base compute trigger(s) {sorted(missing)}; overriding a "
                     f"compute replaces @api.depends so the field goes stale")

# -- 12. Manifest assets/images must exist ---
for image in manifest.get("images", []):
    if not (ROOT / image).is_file():
        fail(f"manifest images entry does not exist: {image}")
# -- 12. Compute overrides must not narrow the base dependency list ---
# Overriding a compute method in Odoo REPLACES its @api.depends rather than
# extending it. Narrowing it silently makes the recompute trigger go stale.
# These are the base triggers of the methods this module overrides.
BASE_COMPUTE_DEPENDS = {
    "_compute_journal_id": {"available_journal_ids"},
    "_compute_available_journal_ids": {"payment_type", "company_id", "can_edit_wizard"},
}
for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.FunctionDef)
                    and stmt.name in BASE_COMPUTE_DEPENDS):
                continue
            declared = set()
            for dec in stmt.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and getattr(dec.func, "attr", "") == "depends"):
                    continue
                # @api.depends may be given several positional string lists.
                for arg in dec.args:
                    try:
                        value = ast.literal_eval(arg)
                    except (ValueError, SyntaxError):
                        continue
                    if isinstance(value, str):
                        declared.add(value)
                    elif isinstance(value, (list, tuple, set)):
                        declared |= set(value)
            if not declared:
                fail(f"{path.relative_to(ROOT)} overrides {stmt.name} with no "
                     f"@api.depends -- the base triggers will be lost")
                continue
            missing = BASE_COMPUTE_DEPENDS[stmt.name] - declared
            if missing:
                fail(f"{path.relative_to(ROOT)}:{stmt.lineno} {stmt.name} drops "
                     f"base compute trigger(s) {sorted(missing)}; overriding a "
                     f"compute replaces @api.depends so the field goes stale")

# -- 13. A stored compute may not depend on a non-stored field ---
# Odoo builds its recompute graph from stored fields. A stored computed field
# listing a non-stored field in @api.depends never triggers, so it silently
# serves a stale value.
STORAGE = {}
for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                kwargs = {}
                if isinstance(stmt.value, ast.Call):
                    for kw in stmt.value.keywords:
                        if kw.arg:
                            try:
                                kwargs[kw.arg] = ast.literal_eval(kw.value)
                            except (ValueError, SyntaxError):
                                kwargs[kw.arg] = "<expr>"
                STORAGE.setdefault((path, target.id), kwargs)

FIELD_INDEX = {}
for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        models = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id in ("_name", "_inherit"):
                        try:
                            value = ast.literal_eval(stmt.value)
                        except (ValueError, SyntaxError):
                            continue
                        models += ([value] if isinstance(value, str) else list(value))
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                kwargs = STORAGE.get((path, target.id), {})
                # Index EVERY computed field, stored or not. Indexing only the
                # stored ones -- an earlier bug in this rule -- made a non-stored
                # computed dependency invisible, so the rule could never fire.
                if "compute" in kwargs:
                    for model in models:
                        FIELD_INDEX.setdefault(model, {})[target.id] = kwargs

for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        models = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id in ("_name", "_inherit"):
                        try:
                            value = ast.literal_eval(stmt.value)
                        except (ValueError, SyntaxError):
                            continue
                        models += ([value] if isinstance(value, str) else list(value))
        for stmt in node.body:
            if not (isinstance(stmt, ast.FunctionDef) and stmt.name.startswith("_compute_")):
                continue
            # Only a compute that backs a STORED field has a recompute graph to
            # keep alive. A compute backing only non-stored fields is fine.
            backs_stored_field = any(
                FIELD_INDEX.get(model, {}).get(fname, {}).get("store") is True
                and FIELD_INDEX.get(model, {}).get(fname, {}).get("compute") == stmt.name
                for model in models
                for fname in FIELD_INDEX.get(model, {})
            )
            if not backs_stored_field:
                continue
            declared = []
            for dec in stmt.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and getattr(dec.func, "attr", "") == "depends"):
                    continue
                for arg in dec.args:
                    try:
                        value = ast.literal_eval(arg)
                    except (ValueError, SyntaxError):
                        continue
                    declared += [value] if isinstance(value, str) else list(value)
            for model in models:
                for dep in declared:
                    if "." in dep:
                        continue
                    dep_kwargs = FIELD_INDEX.get(model, {}).get(dep)
                    if dep_kwargs is not None and dep_kwargs.get("store") is not True:
                        fail(f"{path.relative_to(ROOT)}:{stmt.lineno} stored compute "
                             f"{stmt.name} depends on non-stored '{dep}'; it would "
                             f"never recompute")

# -- 14. Manifest assets/images must exist ---
for image in manifest.get("images", []):
    if not (ROOT / image).is_file():
        fail(f"manifest images entry does not exist: {image}")

# -- 15. Security CSVs must not contain '#' comment rows ---
# Odoo 19's convert_csv_import passes every non-blank row to the ORM loader
# (only fully-empty rows are filtered). A '#' comment row is a 1-cell row, so
# the loader applies the header column indexes to it and the install dies with
# IndexError: list index out of range -- inside ir.model.access.csv.
for path in sorted((ROOT / "security").glob("*.csv")):
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.lstrip().startswith("#"):
            fail(f"{path.relative_to(ROOT)}:{lineno} is a '#' comment row; "
                 f"Odoo 19 does not skip these in data CSVs and the install "
                 f"will fail with IndexError (move comments to README)")

# -- 16. No legacy _sql_constraints (silently ignored by Odoo 19) ---
# Odoo 19 removed _sql_constraints: the attribute generates only a WARNING
# ("please define models.Constraint on the model") and the DB constraint is
# never created -- the module then ships without its uniqueness guarantees.
for path in ROOT.rglob("*.py"):
    if path.name == pathlib.Path(__file__).name:
        continue  # this checker names the attribute in its own messages
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if re.search(r"\b_sql_constraints\s*=", line):
            fail(f"{path.relative_to(ROOT)}:{lineno} uses legacy _sql_constraints; "
                 f"Odoo 19 silently ignores it -- declare models.Constraint "
                 f"('<sql>', '<message>') as a class attribute instead")

# -- 17. tracking=True on a model without mail.thread is a dead parameter ---
# On models that do not (transitively) inherit mail.thread, Odoo logs
# "Field ...: unknown parameter 'tracking'" at install and the tracking never
# fires -- a silent no-op, not a failure.
for path in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        inherits = None  # only new models (with _name) are judged statically
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "_name":
                        try:
                            ast.literal_eval(stmt.value)
                            inherits = "has_name"
                        except (ValueError, SyntaxError):
                            pass
        if inherits is None:
            continue
        lineage = set()
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "_inherit":
                        try:
                            value = ast.literal_eval(stmt.value)
                        except (ValueError, SyntaxError):
                            continue
                        lineage |= set(value if isinstance(value, list) else [value])
        if "mail.thread" in lineage:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not isinstance(stmt.value, ast.Call):
                continue
            if not any(kw.arg == "tracking" for kw in stmt.value.keywords):
                continue
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if not names or names[0] in ("_name", "_inherit"):
                continue
            fail(f"{path.relative_to(ROOT)}:{stmt.lineno} field "
                 f"'{names[0]}' has tracking=True on a model without "
                 f"mail.thread in _inherit -- unknown parameter, silently dead")

# -- 18. No duplicate models.Constraint attribute in one class ---
# Two Constraint declarations with the same attribute name, or two UNIQUE
# constraints on the same columns in one model, is either a hard error or a
# silently redundant second constraint on the table.
for path in ROOT.rglob("*.py"):
    if path.name == pathlib.Path(__file__).name:
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(f"{path.relative_to(ROOT)}: Python syntax error: {exc}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen_attrs = {}
        seen_defs = []
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not (isinstance(stmt.value, ast.Call)
                    and getattr(stmt.value.func, "attr", "") == "Constraint"):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    seen_attrs.setdefault(target.id, []).append(stmt.lineno)
                    try:
                        seen_defs.append(
                            (ast.literal_eval(stmt.value.args[0]), stmt.lineno))
                    except (ValueError, SyntaxError, IndexError):
                        pass
        for attr, linenos in seen_attrs.items():
            if len(linenos) > 1:
                fail(f"{path.relative_to(ROOT)} declares models.Constraint "
                     f"'{attr}' more than once in {node.name} (lines {linenos})")
        norm = {}
        for definition, lineno in seen_defs:
            # Compare with ALL whitespace removed, so "UNIQUE (name)" and
            # "UNIQUE(name)" are recognised as the same constraint.
            key = re.sub(r"\s+", "", str(definition).upper())
            if key in norm:
                fail(f"{path.relative_to(ROOT)}:{lineno} duplicates a UNIQUE "
                     f"constraint in {node.name} (already at line {norm[key]})")
            norm[key] = lineno

# -- 19. XML comments must not contain '--' ---------------------------------
# A comment may not contain the string "--" anywhere in its body. An ASCII rule
# inside a comment (or a stray "----" separator) breaks the file outright with
# "not well-formed (invalid token)"; Odoo's view loader does not tolerate it.
for path in xml_files:
    for match in re.finditer(r"<!--(.*?)-->", path.read_text(encoding="utf-8"),
                             flags=re.S):
        if "--" in match.group(1):
            snippet = match.group(0).splitlines()[0][:60]
            fail(f"{path.relative_to(ROOT)} has an XML comment containing '--', "
                 f"which is illegal inside a comment: {snippet!r}")
            break

# -- Report ---
print(f"XML files parsed : {len(xml_files)}")
print(f"Manifest data    : {len(manifest['data'])} entries")
print(f"Models defined   : {len(defined_models)}")
print(f"ACL rows         : {len(acl_rows)}")
print(f"Rule rows        : {len(rule_rows)}")
print(f"Groups declared  : {len(declared_groups)}")
print(f"Owned-model fields checked: "
      f"{sum(len(v) for v in owned_fields.values())}")
print()
if problems:
    print(f"FAILED with {len(problems)} problem(s):")
    for problem in problems:
        print(f"  - {problem}")
    sys.exit(1)
print("All static consistency checks passed.")
