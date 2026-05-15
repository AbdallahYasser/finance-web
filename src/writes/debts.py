"""Debt lifecycle: lend / borrow / repay / forgive.

Every state change is mirrored as a `transactions` row so the wallet ledger
stays in sync. `debt_id` (already part of the bot's transactions schema)
links the transaction back to its debt.

Transaction-type mapping:
  - lend            → 'lend'      (money leaves your wallet to person)
  - borrow          → 'borrow'    (money enters your wallet from person)
  - repay (lent)    → 'repay_in'  (you get money back — receivable shrinks)
  - repay (borrowed)→ 'repay_out' (you pay money back — payable shrinks)
  - forgive         → 'forgive'   (debt written off; convert to expense)
"""
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from src.db import write_db_uri


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _debt_status(db, debt_id: int) -> str:
    async with db.execute(
        "SELECT status FROM debts WHERE id = ?", (debt_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else "open"


async def _debt_summary(db, debt_id: int) -> dict | None:
    """Compute the debt's remaining + total-repaid based on linked transactions."""
    async with db.execute(
        """
        SELECT id, person_id, direction, original_amount_cents, status, note
        FROM debts WHERE id = ?
        """,
        (debt_id,),
    ) as cur:
        row = await cur.fetchone()
        if not row:
            return None
        debt_id, person_id, direction, original, status, note = row

    repay_type = "repay_in" if direction == "lent" else "repay_out"
    async with db.execute(
        """
        SELECT COALESCE(SUM(amount_cents), 0) FROM transactions
        WHERE debt_id = ? AND type = ? AND deleted_at IS NULL
        """,
        (debt_id, repay_type),
    ) as cur:
        (repaid,) = await cur.fetchone()

    remaining = max(0, original - repaid)
    return {
        "id": debt_id,
        "person_id": person_id,
        "direction": direction,
        "original_amount_cents": original,
        "repaid_cents": repaid,
        "remaining_cents": remaining,
        "status": status,
        "note": note,
    }


async def insert_debt(
    *,
    person_id: int,
    direction: str,
    amount_cents: int,
    wallet_id: int,
    opened_at: Optional[str] = None,
    due_at: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    if direction not in ("lent", "borrowed"):
        raise ValueError("direction must be 'lent' or 'borrowed'")
    if amount_cents <= 0:
        raise ValueError("amount must be > 0")
    if not person_id:
        raise ValueError("person_id required")
    if not wallet_id:
        raise ValueError("wallet_id required")

    opened_at = opened_at or _now_utc_iso()
    note_clean = (note or "").strip() or None

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        cur = await db.execute(
            """
            INSERT INTO debts
              (person_id, direction, original_amount_cents, opened_at, due_at, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (person_id, direction, amount_cents, opened_at, due_at, note_clean),
        )
        debt_id = cur.lastrowid

        # Mirror as a transaction: lend → money out of wallet, borrow → money in
        tx_type = "lend" if direction == "lent" else "borrow"
        if direction == "lent":
            src_w, dst_w = wallet_id, None
        else:
            src_w, dst_w = None, wallet_id
        await db.execute(
            """
            INSERT INTO transactions
              (type, amount_cents, source_wallet_id, dest_wallet_id,
               person_id, debt_id, occurred_at, note, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')
            """,
            (tx_type, amount_cents, src_w, dst_w,
             person_id, debt_id, opened_at, note_clean),
        )

        await db.commit()
        return debt_id


async def repay(
    *,
    debt_id: int,
    amount_cents: int,
    wallet_id: int,
    occurred_at: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    """Record a repayment toward an open debt. Updates status to
    'partial' / 'closed' as appropriate."""
    if amount_cents <= 0:
        raise ValueError("amount must be > 0")
    if not wallet_id:
        raise ValueError("wallet_id required")

    occurred_at = occurred_at or _now_utc_iso()
    note_clean = (note or "").strip() or None

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        summary = await _debt_summary(db, debt_id)
        if not summary:
            raise ValueError("debt not found")
        if summary["status"] in ("closed", "forgiven"):
            raise ValueError(f"cannot repay a {summary['status']} debt")
        if amount_cents > summary["remaining_cents"]:
            raise ValueError(
                f"repayment exceeds remaining "
                f"({summary['remaining_cents']} cents)"
            )

        direction = summary["direction"]
        tx_type = "repay_in" if direction == "lent" else "repay_out"
        # repay_in: money comes back into a wallet (dst)
        # repay_out: money leaves a wallet (src)
        if direction == "lent":
            src_w, dst_w = None, wallet_id
        else:
            src_w, dst_w = wallet_id, None

        cur = await db.execute(
            """
            INSERT INTO transactions
              (type, amount_cents, source_wallet_id, dest_wallet_id,
               person_id, debt_id, occurred_at, note, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')
            """,
            (tx_type, amount_cents, src_w, dst_w,
             summary["person_id"], debt_id, occurred_at, note_clean),
        )
        tx_id = cur.lastrowid

        new_repaid = summary["repaid_cents"] + amount_cents
        new_status = "closed" if new_repaid >= summary["original_amount_cents"] else "partial"
        await db.execute(
            "UPDATE debts SET status = ? WHERE id = ?",
            (new_status, debt_id),
        )

        await db.commit()
        return tx_id


async def forgive(
    *,
    debt_id: int,
    note: Optional[str] = None,
    forgive_category_id: Optional[int] = None,
) -> int:
    """Forgive an open/partial debt. Marks the debt forgiven and inserts
    a `forgive` transaction whose amount equals the remaining balance.

    The forgive transaction acts like an expense (for `lent` debts — your
    money is gone) or like a windfall (for `borrowed` debts — they let you
    off). For accounting clarity we model both as the linked `forgive`
    type, and net-worth math treats forgiven debts as no longer
    receivable/payable.
    """
    occurred_at = _now_utc_iso()
    note_clean = (note or "").strip() or None

    async with aiosqlite.connect(write_db_uri(), uri=True) as db:
        summary = await _debt_summary(db, debt_id)
        if not summary:
            raise ValueError("debt not found")
        if summary["status"] in ("closed", "forgiven"):
            raise ValueError(f"cannot forgive a {summary['status']} debt")
        if summary["remaining_cents"] == 0:
            raise ValueError("debt has no remaining balance to forgive")

        cur = await db.execute(
            """
            INSERT INTO transactions
              (type, amount_cents, person_id, debt_id, category_id,
               occurred_at, note, source)
            VALUES ('forgive', ?, ?, ?, ?, ?, ?, 'manual')
            """,
            (summary["remaining_cents"], summary["person_id"], debt_id,
             forgive_category_id, occurred_at, note_clean),
        )
        tx_id = cur.lastrowid

        await db.execute(
            "UPDATE debts SET status = 'forgiven' WHERE id = ?",
            (debt_id,),
        )
        await db.commit()
        return tx_id
