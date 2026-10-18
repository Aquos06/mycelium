# Spec: expenses

**Observed need:** Hansen mentions spending in chat ("dinner 350", "grab 120 to office") several
times a week and later asks how much he spent.

**What to build:** a module that

- listens to `sense.chat`, and when a message looks like an expense (an amount plus a short
  description, e.g. "dinner 350", "350 dinner", "coffee 85.5"), stores it with the date
- emits `expense.logged` with `{amount, description, day}`
- answers `summary` with totals for a date range (`{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`,
  default: current week) and the top 5 descriptions by spend
- currency is TWD unless the message says otherwise; store the currency string as given
- observes (`severity="notice"`) when a single expense is over 3000
- ignores messages that are not expenses (no amount, or the amount is part of a time like "at 7")

No network, no actuation.
