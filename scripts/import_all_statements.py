"""Import all Futu-*-statement.pdf files under /app/uploads into Postgres."""

from __future__ import annotations

from pathlib import Path

from src.db import (
    delete_transactions_for_statement,
    file_sha256,
    insert_statement,
    insert_transactions,
)
from src.statement_parser import parse_statement_pdf


def main() -> None:
    uploads = Path("/app/uploads")
    files = sorted(
        {
            *uploads.glob("Futu-*-statement.pdf"),
            *[
                p
                for p in uploads.glob("*_Futu-*-statement.pdf")
            ],
        },
        key=lambda p: p.name,
    )
    # Prefer canonical names without sha prefix when both exist
    by_month: dict[str, Path] = {}
    for p in files:
        name = p.name
        if name.startswith("Futu-"):
            by_month[name] = p
        else:
            # sha_Futu-Aug-statement.pdf
            idx = name.find("Futu-")
            if idx >= 0:
                key = name[idx:]
                by_month.setdefault(key, p)

    for name, path in sorted(by_month.items()):
        data = path.read_bytes()
        parsed = parse_statement_pdf(path)
        sha = file_sha256(data)
        sid = insert_statement(
            filename=name,
            file_sha256_hex=sha,
            statement_month=parsed.statement_month,
            account_id=parsed.account_id,
            page_count=parsed.page_count,
            raw_text_preview=parsed.raw_text[:3000],
            parse_status="ok" if parsed.transactions else "partial",
            parse_message="; ".join(parsed.warnings) if parsed.warnings else None,
        )
        delete_transactions_for_statement(sid)
        n = insert_transactions(sid, [t.to_db_row() for t in parsed.transactions])
        print(f"{name}: statement_id={sid} inserted={n}")


if __name__ == "__main__":
    main()
