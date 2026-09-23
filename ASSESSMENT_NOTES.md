# Assessment notes

This is a local, staff-operated educational application with fictional customers
and money. It does not connect to banks or payment systems.

## Assumptions and business decisions

- All accounts use KES. Savings and current accounts follow the same demo rules.
- Amounts are exact decimals: KES 0.01–10,000,000.00 per movement, at most two
  decimal places. The account balance ceiling is KES 999,999,999,999.99.
- Opening and closure are zero-value ledger events. Financial movements must be
  positive and contain before/after snapshots.
- An existing customer can open another account. Normalized email, Kenyan mobile
  number and national ID must be unique across customers.
- A manager can manually mark a zero-balance, loan-free account dormant. Closure
  requires dormancy, zero funds and no outstanding loan. Closure retains records.
- The loan is exactly KES 10,000.00, once per account, at 0% demo interest. There
  is no repayment workflow; an outstanding loan therefore blocks closure.
- Banking records are read-only in admin so normal operations cannot bypass the
  service layer. Superusers can manage staff and group membership there.

## Manual acceptance check

Use `demo_manager` after setting its password as described in the README.

1. Open savings account A with fictional identity details; confirm zero balance.
2. Deposit 25,000, then withdraw 5,000; confirm KES 20,000.00.
3. Create account B and transfer 2,500 from A. The receipt must show both ledger
   entries with the same transfer reference. A = 17,500; B = 2,500.
4. On A, confirm **Create & Disburse KES 10,000 Loan**. A = 27,500 and the linked
   loan is disbursed with 10,000 outstanding. Repeating the POST must not credit
   another loan (covered by the integration test).
5. Create zero-balance account C, mark dormant and close it. Find it with the
   Closed filter and inspect its retained opening and closure entries.
6. As `demo_teller`, confirm manager actions are hidden and direct access is 403.
7. Try an overdraft, a zero amount and more than two decimal places. Check that
   balances and completed ledger records do not change.

## Trade-offs and production boundary

SQLite uses IMMEDIATE transactions to serialize writers; `select_for_update()`
is effective with PostgreSQL but is a no-op on SQLite. A busy writer can be
rejected safely and retried by the operator. Tests cover conflicting withdrawals;
they do not establish production throughput or cover every possible schedule.

The application guards ledger modification through its ORM and admin. A database
administrator or raw SQL can bypass those controls. This is an account movement
audit ledger, not a complete double-entry general ledger.

Ordinary deposits, withdrawals and transfers require operators to check receipts
before retrying an uncertain request; they do not have durable idempotency keys.
Loans have both one-to-one uniqueness and service checks. Dormancy is a manual
demo action; a real system needs an approved inactivity policy and scheduled job.

Before real financial use, redesign and independently review accounting controls,
durable request idempotency, actor audit trails, PostgreSQL concurrency, privacy,
identity verification, access segregation, reconciliation, backups and recovery,
monitoring, deployment hardening and applicable regulatory requirements. This
assessment is not a production banking platform.
