import frappe


def execute():
	"""Fill the Party Type selector on Payment Entries made before the Ledger Account option existed."""
	pe = frappe.qb.DocType("Payment Entry")
	(
		frappe.qb.update(pe)
		.set(pe.party_or_ledger, pe.party_type)
		.where(pe.party_type.isin(["Customer", "Supplier"]))
		.where((pe.party_or_ledger.isnull()) | (pe.party_or_ledger == ""))
	).run()
