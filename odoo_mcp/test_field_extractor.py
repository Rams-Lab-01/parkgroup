"""Unit test for the inaccessible-field extractor used by tolerant fetching."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from pgre_client import extract_inaccessible_fields as extract  # noqa: E402

CASES: list[tuple[str, list[str]]] = [
    ('You do not have enough rights to access the fields "birthday,gender,'
     'passport_id" on model res.users',
     ["birthday", "gender", "passport_id"]),
    ("Invalid field 'amount_credit' on model 'account.move'", ["amount_credit"]),
    ("Invalid field 'amount_credit' on model 'account.move'\n"
     "Invalid field 'amount_debit' on model 'account.move'",
     ["amount_credit", "amount_debit"]),
    ("Invalid field account.move.line.state in leaf ('state', '=', 'posted')",
     ["account.move.line.state"]),
    ('access the fields "a,b, c ,d" ', ["a", "b", "c", "d"]),
    ('access the fields "id,secret"', ["secret"]),          # 'id' never dropped
    ("some unrelated failure", []),
    ("", []),
]


def main() -> int:
    failures = 0
    for message, expected in CASES:
        got = extract(message)
        ok = got == expected
        print(f"  {'PASS' if ok else 'FAIL'}  {message[:64]!r}")
        if not ok:
            print(f"        expected {expected}")
            print(f"        got      {got}")
            failures += 1
    print()
    if failures:
        print(f"RESULT: FAIL - {failures}/{len(CASES)} cases failed")
        return 1
    print(f"RESULT: PASS - all {len(CASES)} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())