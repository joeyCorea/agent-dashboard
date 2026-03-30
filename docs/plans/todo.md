Proposed list:
1. Default to conversations where last message was sent in the last 7 days
1. Allow the user to toggle between flat list vs grouped by project
1. Allow the user to toggle enter how many days they want to filter

Revised list (least risky first):
1. Default to conversations where last message was sent in the last 7 days (plan 002) — simple datetime filter, no UI changes
2. Allow the user to toggle enter how many days they want to filter (plan 004) — extends plan 002 with Input widget, medium focus-management risk
3. Allow the user to toggle between flat list vs grouped by project (plan 003) — changes core display logic, index tracking with mixed item types

For above items,
1. use /ce:plan to write a plan to @docs/plans/
1. once you have all of the plans, order the items in terms of riskiest fix (least riskiest first). Write the new order under "revised list" (even if it's the same order as proposed)

Then each item on the revised list:
1. use /code skill to implement the plan
1. use /internal-review to review change
1. loop between using /code to fix anything (but also push back if scope creep) and /internal-review
1. use /ce:compound to add to knowledge base in docs/solutions/
1. commit the change (don't push)

