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
    if "." in xmlid:
        # Qualified reference to ANOTHER module's model (Odoo resolves it
        # against that module); existence there cannot be checked locally.
        continue
    # Odoo builds model xmlids by replacing dots with underscores, so invert it.
    model_name = xmlid[len("model_"):].replace("_", ".")
    if model_name not in defined_models:
        fail(f"security references {xmlid} but the module does not define "
             f"model {model_name}")

# -- 8. Group references in XML resolve to groups declared in this module ---
declared_groups = set(re.findall(
    r'<record id="(group_escrow_\w+)"',
    (ROOT / "security" / "escrow_groups.xml").read_text(encoding="utf-8")))
referenced_groups = set()
for path in xml_files + list(ROOT.rglob("*.py")):
    referenced_groups |= set(re.findall(
        r'sgc_escrow\.(group_escrow_\w+)', path.read_text(encoding="utf-8")))
for group in sorted(referenced_groups - declared_groups):
    fail(f"XML/Python references undeclared group: sgc_escrow.{group}")

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
                if "compute" in kwargs and kwargs.get("store") is True:
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
            key = " ".join(str(definition).upper().split())
            if key in norm:
                fail(f"{path.relative_to(ROOT)}:{lineno} duplicates a UNIQUE "
                     f"constraint in {node.name} (already at line {norm[key]})")
            norm[key] = lineno

# -- 16. No dotted <field name="a.b"> tags (rejected by Odoo 19 validation) ---
# Odoo 19's _validate_tag_field looks the name up in model._fields and then in
# field_info; dotted names match neither, so the view fails install with
# 'Field "a.b" does not exist in model "m"'. Dotted paths remain valid inside
# invisible/domains expressions -- only the <field> tag is affected. Use an
# explicit related field on the model instead.
for path in xml_files:
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.search(r'<field\s+name="([a-z_]+\.[a-z_]+)"', line)
        if match:
            fail(f"{path.relative_to(ROOT)}:{lineno} uses dotted field name "
                 f"'{match.group(1)}' in a <field> tag; Odoo 19 view validation "
                 f"rejects it -- declare an explicit related field instead")

# -- 17. No QWeb directives in form/list view arch (Odoo 19 Owl rejects them) --
# View arch compiles to Owl templates where t-out/t-esc/t-foreach/... are
# forbidden ('Forbidden owl directive used in arch'); only kanban/report QWeb
# may use them. Display values with <field> nodes instead.
QWEB_DIRECTIVE = re.compile(r'\s(t-out|t-esc|t-raw|t-foreach|t-if|t-else|t-set|t-call)=')
for path in xml_files:
    if "report" in path.parts:
        continue  # QWeb report templates legitimately use directives
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        match = QWEB_DIRECTIVE.search(line)
        if match:
            fail(f"{path.relative_to(ROOT)}:{lineno} uses QWeb directive "
                 f"{match.group(1)}= in view arch; Odoo 19 forbids it in "
                 f"form/list views -- use a <field> node")

# -- 18. Filter domains/group-bys may only use stored (or search=) fields -----
# A non-stored compute field is not server-side searchable: Odoo rejects the
# view with 'Unsearchable field "x" in path "x" in domain of <filter ...>'.
# Stored computes and fields with an explicit search= method are fine.
FIELD_SEARCHABLE = {}  # (class-node, field-name) -> dict(compute=..., store=..., search=...)
for path in ROOT.rglob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)):
                continue
            kwargs = {}
            for kw in stmt.value.keywords:
                if kw.arg:
                    try:
                        kwargs[kw.arg] = ast.literal_eval(kw.value)
                    except (ValueError, SyntaxError):
                        kwargs[kw.arg] = "<expr>"
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    FIELD_SEARCHABLE[target.id] = kwargs

DOMAIN_FIELD = re.compile(r"""\(\s*['"]([a-z_]+)['"]\s*,""")
GROUPBY_FIELD = re.compile(r"""['"]group_by['"]\s*:\s*['"]([a-z_]+)['"]""")
for path in xml_files:
    text = path.read_text(encoding="utf-8")
    used = set(DOMAIN_FIELD.findall(text)) | set(GROUPBY_FIELD.findall(text))
    for fname in sorted(used):
        kwargs = FIELD_SEARCHABLE.get(fname)
        if kwargs is None:
            continue  # field defined elsewhere (property.*, account.*) -- not ours to judge
        if "compute" in kwargs and kwargs.get("store") is not True and "search" not in kwargs:
            fail(f"{path.relative_to(ROOT)} uses non-stored compute field '{fname}' "
                 f"in a filter domain / group-by; Odoo rejects it as unsearchable "
                 f"-- store the field, add search=, or drop the filter")

# -- 19. No legacy <group expand=...> wrappers in search arch ----------------
# Odoo 19's search RNG forbids expand/string on <group> and expects field
# children; the platform migrated to bare group-by filters. The wrapper fails
# install with a generic 'Invalid view ... definition'.
for path in xml_files:
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if re.search(r"<group[^>]*\sexpand=", line):
            fail(f"{path.relative_to(ROOT)}:{lineno} uses a legacy "
                 f"<group expand=...> wrapper; Odoo 19 search RNG rejects it "
                 f"-- use bare group-by <filter context=.../> entries instead")

# -- 20. Settings view fields must exist in our settings model ---------------
# A view <field name="x"/> on res.config.settings with no matching model field
# aborts install with ParseError "Field ... does not exist".
settings_model = ROOT / "models" / "res_config_settings.py"
settings_views = [p for p in xml_files
                  if 'res_config_setting' in p.name or 'res_config' in p.name]
if settings_model.exists() and settings_views:
    defined = set(re.findall(
        r"^    (\w+) = fields\.", settings_model.read_text(encoding="utf-8"),
        re.M))
    for path in settings_views:
        for rec in ET.parse(path).getroot().iter("record"):
            model_field = rec.find("field[@name='model']")
            if model_field is None or (
                    model_field.text or "").strip() != "res.config.settings":
                continue
            arch = rec.find("field[@name='arch']")
            if arch is None:
                continue
            used = {f.get("name") for f in arch.iter("field")
                    if f is not arch and f.get("name")}
            missing = sorted(used - defined)
            if missing:
                fail(f"{path.relative_to(ROOT)} view {rec.get('id')} references "
                     f"{missing} not defined in models/res_config_settings.py")

# -- 21. Manifest order: local xmlid refs must be defined earlier -------------
# Odoo resolves ref/action/parent xmlids at load time; a menu referencing an
# action defined in a later manifest entry aborts install with
# "External ID not found in the system".
_local_defs = {}   # id -> (file_index, line)
_refs = []         # (file_index, line, value)
for _idx, _entry in enumerate(manifest["data"]):
    _p = ROOT / _entry
    if _p.suffix.lower() != ".xml" or not _p.exists():
        continue
    _text = _p.read_text(encoding="utf-8")
    for _m in re.finditer(r'[\s<]id="([\w]+)"', _text):
        _line = _text[:_m.start()].count("\n")
        _local_defs.setdefault(_m.group(1), (_idx, _line))
    for _m in re.finditer(r'\b(?:ref|action|parent)="([^"]+)"', _text):
        _line = _text[:_m.start()].count("\n")
        _refs.append((_idx, _line, _m.group(1)))
for _idx, _line, _val in _refs:
    if any(_c in _val for _c in " (){}'[,"):
        continue                          # expression junk, not an xmlid
    if _val.startswith("sgc_escrow."):
        _val = _val.split(".", 1)[1]
    elif "." in _val:
        continue                          # external module xmlid
    if _val not in _local_defs:
        continue                          # not defined by us (see check 5)
    _didx, _dline = _local_defs[_val]
    if _didx > _idx or (_didx == _idx and _dline > _line):
        fail(f"manifest entry {manifest['data'][_idx]} line {_line + 1} "
             f"references '{_val}' but it is only defined at line "
             f"{_dline + 1} of {manifest['data'][_didx]} -- move the "
             f"defining entry earlier in the manifest data list")

# -- 22. Whole-file data schema (odoo/import_xml.rng) ------------------------
# A data file whose root is a bare <template> (or any structure outside
# odoo/openerp/data + record/menuitem/template/...) aborts install with
# "Document does not comply with schema". The rng is vendored from
# odoo/import_xml.rng so this runs without an Odoo checkout.
try:
    from lxml import etree as _LET
except ImportError:
    fail("lxml is not installed -- cannot run whole-file schema check 22")
else:
    _rngf = ROOT / "tools" / "import_xml.rng"
    if not _rngf.exists():
        fail("tools/import_xml.rng is missing (vendor it from odoo/import_xml.rng)")
    else:
        _rng = _LET.RelaxNG(file=str(_rngf))
        for _entry in manifest["data"]:
            _p = ROOT / _entry
            if _p.suffix.lower() != ".xml" or not _p.exists():
                continue
            try:
                _doc = _LET.parse(str(_p))
            except _LET.XMLSyntaxError as _exc:
                fail(f"{_entry} is not well-formed XML: {_exc}")
                continue
            if not _rng.validate(_doc):
                _msgs = [f"@{_e.line}: {_e.message}" for _e in _rng.error_log]
                fail(f"{_entry} violates odoo/import_xml.rng -- "
                     + ("; ".join(_msgs[:4]) if _msgs else
                        "root must be <odoo>/<openerp>/<data> and only "
                        "record/menuitem/template/asset/delete/function "
                        "structures are allowed at file level"))

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