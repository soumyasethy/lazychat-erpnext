"""Audit which canonical-business-doctype pairs are covered by find_join_path.

Walks every ordered pair (a, b) of doctypes in CANONICAL_BUSINESS_DOCTYPES,
calls _find_join_path(a, b), and bins the result:

  curated  — at least one curated/curated_reverse hop in the chain
  meta     — only Frappe Link/Table edges, no curated input
  uncovered — no path within max_hops

Output is a markdown report you can scan to decide what to add to
_RELATIONSHIP_HINTS next. Pairs in the "uncovered" bucket are the highest-
value candidates for new hints.

Run via the same pattern as _smoke.py (file gets wiped on every deploy):

    cp lazychat-erpnext/scripts/audit-relationship-coverage.py \\
       <bench>/apps/lazychat_erpnext/lazychat_erpnext/_audit_relationships.py
    cd <bench>
    bench --site <site> execute lazychat_erpnext._audit_relationships.run

Optional kwargs (all positional in bench execute):
    max_hops=3              BFS depth limit
    show_paths=False        also print the hop chain for covered pairs
    only_uncovered=False    skip the covered tables, just print gaps
"""

# Master list of "canonical business doctypes" — the set the LLM most often
# needs to join across when answering report questions. Add to this list as
# new domain areas come into scope (manufacturing, HR, projects, …).
CANONICAL_BUSINESS_DOCTYPES = [
	# Sales pipeline
	"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
	"Quotation Item", "Sales Order Item", "Delivery Note Item", "Sales Invoice Item",
	# Purchase pipeline
	"Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice",
	"Material Request Item", "Purchase Order Item", "Purchase Receipt Item", "Purchase Invoice Item",
	# Accounting + payments
	"Journal Entry", "Payment Entry", "GL Entry", "Payment Entry Reference",
	"Journal Entry Account",
	# Stock
	"Stock Entry", "Stock Ledger Entry", "Stock Entry Detail",
	# Masters (frequent join targets)
	"Customer", "Supplier", "Item",
	# System tracking doctypes — Dynamic-Link references that touch any business doc
	"Communication", "File", "ToDo", "Comment", "Tag Link", "Version",
]


def run(max_hops=3, show_paths=False, only_uncovered=False):
	import frappe  # noqa: F401  (must import for Frappe context)
	from lazychat_erpnext.desk_assistant.tools import _find_join_path

	pairs = [(a, b) for a in CANONICAL_BUSINESS_DOCTYPES
	         for b in CANONICAL_BUSINESS_DOCTYPES if a != b]

	curated, meta, uncovered = [], [], []
	for a, b in pairs:
		hops = _find_join_path(a, b, max_hops=max_hops)
		if hops is None:
			uncovered.append((a, b))
			continue
		if any(h.get("via_kind") in ("curated", "curated_reverse") for h in hops):
			curated.append((a, b, hops))
		else:
			meta.append((a, b, hops))

	total = len(pairs)
	print(f"\n=== Relationship Coverage Audit (max_hops={max_hops}) ===")
	print(f"Total ordered pairs: {total}")
	print(f"  Curated     : {len(curated):4d}  ({100*len(curated)//total}%)  — canonical hint or reverse-curated")
	print(f"  Meta-only   : {len(meta):4d}  ({100*len(meta)//total}%)  — BFS via Frappe Link/Table fields")
	print(f"  UNCOVERED   : {len(uncovered):4d}  ({100*len(uncovered)//total}%)  — no path within {max_hops} hops")
	print()

	if not only_uncovered and curated:
		print("=== Curated coverage (sample 20) ===")
		for a, b, hops in curated[:20]:
			tag = "·".join(h.get("via_kind", "?") for h in hops)
			print(f"  {a:<35} → {b:<35}  [{len(hops)}h: {tag}]")
		if len(curated) > 20:
			print(f"  … and {len(curated)-20} more")
		print()

	print(f"=== UNCOVERED ({len(uncovered)}) — candidates for new _RELATIONSHIP_HINTS entries ===")
	if not uncovered:
		print("  (none — every business-doctype pair has a path)")
	for a, b in uncovered:
		print(f"  {a:<35} → {b}")
	print()

	if show_paths and meta:
		print("=== Meta-discovered routes (sample 10, may not be canonical — review) ===")
		for a, b, hops in meta[:10]:
			print(f"  {a} → {b}  ({len(hops)} hops)")
			for h in hops:
				on = h.get("on_template", "")[:70]
				print(f"    via {h.get('via_field')!r:25} ({h.get('via_kind')}): {on}")
		if len(meta) > 10:
			print(f"  … and {len(meta)-10} more")
