// Copyright (c) 2026, HisaabDari contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("hisaabdari.accounts");

const BANK_REC = "hisaabdari.accounts.doctype.bank_reconciliation.bank_reconciliation.";

frappe.ui.form.on("Bank Reconciliation", {
	setup(frm) {
		frm.set_query("bank_account", () => ({
			filters: { account_type: ["in", ["Bank", "Cash"]], is_group: 0, company: frm.doc.company },
		}));
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}
		if (frm.is_new() && !frm.doc.from_date) {
			const last_month = frappe.datetime.add_months(frappe.datetime.get_today(), -1);
			frm.set_value("from_date", moment(last_month).startOf("month").format("YYYY-MM-DD"));
			frm.set_value("to_date", moment(last_month).endOf("month").format("YYYY-MM-DD"));
		}
	},

	refresh(frm) {
		if (frm.is_new()) return;
		if (!frm.bank_reconciliation_view) {
			frm.bank_reconciliation_view = new hisaabdari.accounts.BankReconciliationView(frm);
		}
		frm.bank_reconciliation_view.load();
	},

	statement_closing_balance(frm) {
		if (!frm.is_new()) frm.save();
	},
});

hisaabdari.accounts.BankReconciliationView = class BankReconciliationView {
	constructor(frm) {
		this.frm = frm;
		this.tab = "to_check";
		this.selected_lines = new Set();
		this.selected_entries = new Set();
		this.wrapper = $(frm.fields_dict.reconciliation_html.wrapper).empty();
		this.wrapper.html(`<style>${BANK_REC_CSS}</style><div class="bank-rec"></div>`);
		this.body = this.wrapper.find(".bank-rec");
		this.bind();
	}

	get name() {
		return this.frm.doc.name;
	}

	get is_open() {
		return this.data && this.data.status === "Open";
	}

	money(value) {
		return format_currency(value, this.data.currency);
	}

	esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	date(value) {
		return value ? frappe.datetime.str_to_user(value) : "";
	}

	call(method, args, freeze_message) {
		return frappe
			.call({
				method: BANK_REC + method,
				args: Object.assign({ name: this.name }, args),
				freeze: true,
				freeze_message: freeze_message || __("Working..."),
			})
			.then((r) => r.message);
	}

	load() {
		return frappe.call({ method: BANK_REC + "get_reconciliation_data", args: { name: this.name } }).then((r) => {
			this.data = r.message;
			const names = new Set(this.data.to_check.map((d) => d.name));
			this.selected_lines = new Set([...this.selected_lines].filter((d) => names.has(d)));
			this.selected_entries.clear();
			if (!this.data.has_statement && this.tab === "to_check" && !this.tab_chosen) {
				this.tab = "not_on_statement";
			}
			this.render();
		});
	}

	// ----------------------------------------------------------------------------------------
	// Rendering
	// ----------------------------------------------------------------------------------------

	render() {
		const d = this.data;
		const s = d.summary;
		const tabs = [
			["to_check", __("To check"), d.to_check.length],
			["done", __("Done"), d.matches.length],
			["not_on_statement", __("Not on statement"), d.not_on_statement.length],
			["summary", __("Summary"), null],
		];
		const difference_class = s.difference ? "bad" : "good";

		this.body.html(`
			<div class="br-stats">
				<div class="br-stat"><small>${__("Closing balance on statement")}</small><b>${this.money(s.statement_closing_balance)}</b></div>
				<div class="br-stat"><small>${__("Balance in our books")}</small><b>${this.money(s.book_balance)}</b></div>
				<div class="br-stat"><small>${__("Lines left to check")}</small><b>${s.lines_to_check} ${__("of")} ${s.lines_total}</b></div>
				<div class="br-stat ${difference_class}"><small>${__("Difference still to explain")}</small><b>${this.money(s.difference)}</b></div>
			</div>
			<div class="br-actions">
				${
					this.is_open
						? `<button class="btn btn-primary btn-sm" data-action="upload">${__("Upload Statement")}</button>
					<button class="btn btn-default btn-sm" data-action="add_line">${__("Add a Line by Hand")}</button>
					<button class="btn btn-default btn-sm" data-action="mark_all">${__("Starting Out? Mark Old Entries as Agreed")}</button>
					<button class="btn btn-default btn-sm" data-action="close">${__("Finish and Close")}</button>`
						: `<span class="br-closed">${__("This reconciliation is closed.")}</span>
					<button class="btn btn-default btn-sm" data-action="reopen">${__("Reopen")}</button>`
				}
				<button class="btn btn-default btn-sm" data-action="rules">${__("Rules")}</button>
			</div>
			<div class="br-tabs">
				${tabs
					.map(
						([key, label, count]) =>
							`<a class="br-tab ${this.tab === key ? "on" : ""}" data-tab="${key}">${label}${
								count === null ? "" : ` (${count})`
							}</a>`
					)
					.join("")}
			</div>
			<div class="br-content"></div>
		`);

		const content = this.body.find(".br-content");
		if (this.tab === "to_check") content.html(this.render_to_check());
		else if (this.tab === "done") content.html(this.render_done());
		else if (this.tab === "not_on_statement") content.html(this.render_not_on_statement());
		else content.html(this.render_summary());
		this.update_selection_bar();
	}

	line_card(line, with_checkbox) {
		const amount = flt(line.deposit) - flt(line.withdrawal);
		return `
			<div class="br-card">
				<div class="br-top">
					<span>${
						with_checkbox && this.is_open
							? `<input type="checkbox" class="br-line-check" data-line="${line.name}" ${
									this.selected_lines.has(line.name) ? "checked" : ""
							  }> `
							: ""
					}<b>${this.date(line.date)}</b> · ${this.esc(line.description) || __("No description")}</span>
					<span class="br-amount ${amount > 0 ? "in" : "out"}">${amount > 0 ? "+" : "−"} ${this.money(
			Math.abs(amount)
		)}</span>
				</div>
				${line.reference_no ? `<div class="br-meta">${__("Ref")} ${this.esc(line.reference_no)}</div>` : ""}
			</div>`;
	}

	entry_card(entry, note) {
		return `
			<div class="br-top">
				<span><b>${this.esc(entry.title) || this.esc(entry.voucher_type)}</b></span>
				<span class="br-amount">${this.money(Math.abs(entry.amount))}</span>
			</div>
			<div class="br-meta">
				<a href="${frappe.utils.get_form_link(entry.voucher_type, entry.voucher_no)}" target="_blank">${this.esc(
			entry.voucher_no
		)}</a>
				· ${this.date(entry.posting_date)}${entry.reference_no ? ` · ${__("Ref")} ${this.esc(entry.reference_no)}` : ""}
				${note ? ` · ${note}` : ""}
			</div>`;
	}

	render_to_check() {
		const lines = this.data.to_check;
		if (!lines.length) {
			return `<div class="br-empty">${
				this.data.has_statement
					? __("Every line of the statement is checked.")
					: __(
							"No statement lines yet. Upload the bank's file, add lines by hand, or go to \"Not on statement\" and tick entries against a printed statement."
					  )
			}</div>`;
		}

		const rows = [];
		const grouped = new Set();
		for (const line of lines) {
			const suggestion = line.suggestion;
			if (suggestion && suggestion.type === "group") {
				if (grouped.has(suggestion.group)) continue;
				grouped.add(suggestion.group);
				const members = lines.filter((d) => d.suggestion && d.suggestion.group === suggestion.group);
				rows.push(this.render_group_row(members, suggestion));
			} else {
				rows.push(this.render_line_row(line, suggestion));
			}
		}
		return `
			<div class="br-selection" style="display:none"></div>
			<div class="br-heading"><span>${__("From the bank statement")}</span><span></span><span>${__(
			"In our books"
		)}</span></div>
			${rows.join("")}`;
	}

	render_line_row(line, suggestion) {
		let right;
		let ok = "";
		const find_buttons = `
			<button class="btn btn-xs btn-default" data-action="find" data-line="${line.name}">${__("Find a Match")}</button>
			<button class="btn btn-xs btn-default" data-action="new_entry" data-line="${line.name}">${__("New Entry")}</button>
			<button class="btn btn-xs btn-default" data-action="transfer" data-line="${line.name}">${__("Transfer")}</button>
			<button class="btn btn-xs btn-default br-quiet" data-action="delete_line" data-line="${line.name}">${__(
			"Remove Line"
		)}</button>`;

		if (suggestion && suggestion.type === "match") {
			const entry = suggestion.vouchers[0];
			const days = suggestion.days_apart;
			const note = days === 0 ? __("same date") : days === 1 ? __("one day apart") : __("{0} days apart", [days]);
			right = `<div class="br-card match">
				<div class="br-pill-row"><span class="br-pill on">${__("Match found")}</span>${
				suggestion.others ? `<span class="br-pill">${__("{0} more with this amount", [suggestion.others])}</span>` : ""
			}</div>
				${this.entry_card(entry, note)}
				${
					this.is_open
						? `<div class="br-buttons"><button class="btn btn-xs btn-default br-quiet" data-action="find" data-line="${line.name}">${__(
								"Not This One? Find Another"
						  )}</button></div>`
						: ""
				}
			</div>`;
			ok = `<button class="btn btn-success btn-sm" data-action="accept" data-line="${line.name}">${__("OK")}</button>`;
		} else if (suggestion && suggestion.type === "rule") {
			const against = suggestion.party_or_ledger === "Ledger Account" ? suggestion.ledger_account : suggestion.party;
			right = `<div class="br-card rule">
				<div class="br-pill-row"><span class="br-pill on">${__("New entry from your rule")}</span></div>
				<div class="br-top"><span><b>${this.esc(against)}</b></span></div>
				<div class="br-meta">${__("Rule")}: ${this.esc(suggestion.rule)}</div>
				${this.is_open ? `<div class="br-buttons">${find_buttons}</div>` : ""}
			</div>`;
			ok = `<button class="btn btn-success btn-sm" data-action="accept_rule" data-line="${line.name}">${__("OK")}</button>`;
		} else {
			right = `<div class="br-card">
				<div class="br-meta">${__("Nothing in the books with this amount yet.")}</div>
				${this.is_open ? `<div class="br-buttons">${find_buttons}</div>` : ""}
			</div>`;
		}

		return `<div class="br-row">${this.line_card(line, true)}<div class="br-mid">${this.is_open ? ok : ""}</div>${right}</div>`;
	}

	render_group_row(members, suggestion) {
		const entry = suggestion.vouchers[0];
		const names = members.map((d) => d.name).join(",");
		const preview = members
			.slice(0, 4)
			.map((d) => `${this.date(d.date)} ${this.money(Math.abs(flt(d.deposit) - flt(d.withdrawal)))}`)
			.join(" · ");
		const left = `
			<div class="br-card">
				<div class="br-top">
					<span><b>${__("{0} lines", [members.length])}</b> · ${this.esc(members[0].description)}</span>
					<span class="br-amount ${suggestion.total > 0 ? "in" : "out"}">${suggestion.total > 0 ? "+" : "−"} ${this.money(
			Math.abs(suggestion.total)
		)}</span>
				</div>
				<div class="br-meta">${preview}${members.length > 4 ? ` · ${__("and {0} more", [members.length - 4])}` : ""}</div>
				${
					this.is_open
						? `<div class="br-buttons"><button class="btn btn-xs btn-default" data-action="ungroup" data-lines="${names}">${__(
								"Handle These Lines One by One"
						  )}</button></div>`
						: ""
				}
			</div>`;
		const right = `<div class="br-card match">
			<div class="br-pill-row"><span class="br-pill on">${__("Match found")}</span></div>
			${this.entry_card(entry, __("the {0} lines add up to this entry", [members.length]))}
		</div>`;
		const ok = this.is_open
			? `<button class="btn btn-success btn-sm" data-action="accept_group" data-lines="${names}">${__("OK")}</button>`
			: "";
		return `<div class="br-row">${left}<div class="br-mid">${ok}</div>${right}</div>`;
	}

	render_done() {
		if (!this.data.matches.length) return `<div class="br-empty">${__("Nothing matched yet.")}</div>`;
		const labels = {
			Match: __("Matched"),
			"New Entry": __("New entry"),
			Transfer: __("Transfer"),
			"Without Statement": __("Ticked without a statement line"),
		};
		return this.data.matches
			.map((match) => {
				const left = match.lines.length
					? match.lines.map((d) => this.line_card(d, false)).join("")
					: `<div class="br-card"><div class="br-meta">${__("On the statement dated {0}", [
							this.date(match.clearance_date),
					  ])}</div></div>`;
				const right = `<div class="br-card match">
					<div class="br-pill-row"><span class="br-pill on">${labels[match.match_type] || match.match_type}</span></div>
					${match.entries.map((d) => this.entry_card(d)).join('<hr class="br-hr">')}
				</div>`;
				const undo = this.is_open
					? `<button class="btn btn-default btn-xs" data-action="undo" data-match="${match.name}" data-created="${
							match.entries.some((d) => d.created_by_match) ? 1 : 0
					  }">${__("Undo")}</button>`
					: "";
				return `<div class="br-row"><div>${left}</div><div class="br-mid">${undo}</div>${right}</div>`;
			})
			.join("");
	}

	render_not_on_statement() {
		const entries = this.data.not_on_statement;
		if (!entries.length) {
			return `<div class="br-empty">${__("Every entry in the books up to {0} is agreed with the bank.", [
				this.date(this.frm.doc.to_date),
			])}</div>`;
		}
		return `
			<p class="br-help">${__(
				"These entries are in the books but not yet agreed with the bank. If you are working from a printed statement, tick the ones that appear on it and press the button. Entries left here are cheques not yet presented and deposits not yet credited."
			)}</p>
			${
				this.is_open
					? `<div class="br-actions"><button class="btn btn-primary btn-sm" data-action="tick_selected">${__(
							"Selected Entries Are on the Statement"
					  )}</button></div>`
					: ""
			}
			<table class="table br-table">
				<thead><tr><th style="width:30px">${
					this.is_open ? '<input type="checkbox" class="br-entry-all">' : ""
				}</th><th>${__("Date")}</th><th>${__("Entry")}</th><th>${__("Reference")}</th>
				<th class="text-right">${__("Money In")}</th><th class="text-right">${__("Money Out")}</th></tr></thead>
				<tbody>
				${entries
					.map(
						(d) => `<tr>
						<td>${
							this.is_open
								? `<input type="checkbox" class="br-entry-check" data-type="${this.esc(d.voucher_type)}" data-no="${this.esc(
										d.voucher_no
								  )}">`
								: ""
						}</td>
						<td>${this.date(d.posting_date)}</td>
						<td><b>${this.esc(d.title)}</b><br><a class="br-meta" href="${frappe.utils.get_form_link(
							d.voucher_type,
							d.voucher_no
						)}" target="_blank">${this.esc(d.voucher_no)}</a></td>
						<td>${this.esc(d.reference_no)}</td>
						<td class="text-right">${d.amount > 0 ? this.money(d.amount) : ""}</td>
						<td class="text-right">${d.amount < 0 ? this.money(-d.amount) : ""}</td>
					</tr>`
					)
					.join("")}
				</tbody>
			</table>`;
	}

	summary_rows() {
		const s = this.data.summary;
		const rows = [
			[__("Balance in our books on {0}", [this.date(this.frm.doc.to_date)]), s.book_balance, true],
			[__("Add: payments we made that are not on the statement yet"), s.payments_not_presented],
			[__("Less: money we received that is not on the statement yet"), -s.receipts_not_credited],
			[__("Balance the bank should show"), s.expected_bank_balance, true],
		];
		if (s.unbooked_in || s.unbooked_out) {
			rows.push([__("Add: money in on the statement, not in our books yet"), s.unbooked_in]);
			rows.push([__("Less: money out on the statement, not in our books yet"), -s.unbooked_out]);
		}
		rows.push([__("Closing balance on the statement"), s.statement_closing_balance, true]);
		rows.push([__("Difference"), s.difference, true]);
		return rows;
	}

	render_summary() {
		const s = this.data.summary;
		const verdict = s.difference
			? `<div class="br-verdict bad">${__(
					"The statement and the books do not agree yet. Check the closing balance you typed, and the lines still to check."
			  )}</div>`
			: s.lines_to_check
			? `<div class="br-verdict warn">${__("The balances agree, but some statement lines are still to check.")}</div>`
			: `<div class="br-verdict good">${__("The statement and the books agree.")}</div>`;
		return `
			${verdict}
			<table class="table br-table br-summary">
				${this.summary_rows()
					.map(
						([label, value, strong]) =>
							`<tr class="${strong ? "strong" : ""}"><td>${label}</td><td class="text-right">${this.money(value)}</td></tr>`
					)
					.join("")}
			</table>
			<div class="br-actions"><button class="btn btn-default btn-sm" data-action="print">${__(
				"Print Reconciliation Statement"
			)}</button></div>`;
	}

	// ----------------------------------------------------------------------------------------
	// Events
	// ----------------------------------------------------------------------------------------

	bind() {
		this.wrapper.on("click", "[data-tab]", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.tab_chosen = true;
			this.render();
		});
		this.wrapper.on("change", ".br-line-check", (e) => {
			const name = $(e.currentTarget).data("line");
			if (e.currentTarget.checked) this.selected_lines.add(name);
			else this.selected_lines.delete(name);
			this.update_selection_bar();
		});
		this.wrapper.on("change", ".br-entry-all", (e) => {
			this.wrapper.find(".br-entry-check").prop("checked", e.currentTarget.checked);
		});
		this.wrapper.on("click", "[data-action]", (e) => {
			const el = $(e.currentTarget);
			const action = el.data("action");
			const line = el.data("line");
			const lines = line ? [line] : String(el.data("lines") || "").split(",").filter(Boolean);
			const handlers = {
				upload: () => this.upload(),
				add_line: () => this.add_line(),
				mark_all: () => this.mark_all(),
				close: () => this.close(),
				reopen: () => this.call("reopen_reconciliation").then(() => this.frm.reload_doc()),
				rules: () => frappe.set_route("List", "Bank Statement Rule"),
				accept: () => this.accept(lines),
				accept_group: () => this.accept(lines),
				accept_rule: () => this.accept_rule(lines[0]),
				ungroup: () => {
					lines.forEach((d) => this.selected_lines.add(d));
					this.find(lines);
				},
				find: () => this.find(lines),
				new_entry: () => this.new_entry(lines),
				transfer: () => this.transfer(lines),
				delete_line: () => this.delete_lines(lines),
				selection_find: () => this.find([...this.selected_lines]),
				selection_new_entry: () => this.new_entry([...this.selected_lines]),
				selection_transfer: () => this.transfer([...this.selected_lines]),
				selection_clear: () => {
					this.selected_lines.clear();
					this.render();
				},
				undo: () => this.undo(el.data("match"), el.data("created")),
				tick_selected: () => this.tick_selected(),
				print: () => this.print(),
			};
			if (handlers[action]) handlers[action]();
		});
	}

	get_lines(names) {
		return this.data.to_check.filter((d) => names.includes(d.name));
	}

	lines_total(names) {
		return this.get_lines(names).reduce((total, d) => total + flt(d.deposit) - flt(d.withdrawal), 0);
	}

	update_selection_bar() {
		const bar = this.wrapper.find(".br-selection");
		if (!bar.length) return;
		const names = [...this.selected_lines];
		if (names.length < 2) {
			bar.hide();
			return;
		}
		const total = this.lines_total(names);
		bar.show().html(`
			<span><b>${__("{0} lines selected", [names.length])}</b> · ${__("total")} ${total > 0 ? "+" : "−"} ${this.money(
			Math.abs(total)
		)}</span>
			<span>
				<button class="btn btn-xs btn-primary" data-action="selection_find">${__("Find a Match for All")}</button>
				<button class="btn btn-xs btn-default" data-action="selection_new_entry">${__("New Entry for All")}</button>
				<button class="btn btn-xs btn-default" data-action="selection_transfer">${__("Transfer")}</button>
				<button class="btn btn-xs btn-default" data-action="selection_clear">${__("Clear")}</button>
			</span>`);
	}

	done(message) {
		if (message) frappe.show_alert({ message, indicator: "green" });
		this.selected_lines.clear();
		return this.load();
	}

	// ----------------------------------------------------------------------------------------
	// Actions
	// ----------------------------------------------------------------------------------------

	accept(names) {
		const line = this.get_lines(names)[0];
		const vouchers = line.suggestion.vouchers.map((d) => ({ voucher_type: d.voucher_type, voucher_no: d.voucher_no }));
		return this.call("create_match", { lines: names, vouchers }).then(() => this.done(__("Matched")));
	}

	accept_rule(name) {
		const suggestion = this.get_lines([name])[0].suggestion;
		const entry = {
			party_or_ledger: suggestion.party_or_ledger,
			ledger_account: suggestion.ledger_account,
			party: suggestion.party,
		};
		return this.call("create_entry_and_match", { lines: [name], entry }).then(() => this.done(__("Entered and matched")));
	}

	find(names) {
		const total = this.lines_total(names);
		const candidates = this.data.candidates.filter((d) => (total > 0 ? d.amount > 0 : d.amount < 0));
		const picked = new Set();
		const dialog = new frappe.ui.Dialog({
			title: __("Find a Match"),
			size: "large",
			fields: [
				{ fieldtype: "HTML", fieldname: "target" },
				{ fieldtype: "Data", fieldname: "search", label: __("Search by name, number or amount") },
				{ fieldtype: "HTML", fieldname: "list" },
			],
			primary_action_label: __("Match"),
			primary_action: () => {
				const vouchers = [...picked].map((key) => {
					const [voucher_type, voucher_no] = key.split("||");
					return { voucher_type, voucher_no };
				});
				const picked_total = candidates
					.filter((d) => picked.has(`${d.voucher_type}||${d.voucher_no}`))
					.reduce((sum, d) => sum + d.amount, 0);
				const left = flt(total - picked_total, 2);
				if (!vouchers.length) {
					frappe.msgprint(__("Tick at least one entry."));
					return;
				}
				if (left) {
					dialog.hide();
					this.new_entry(names, vouchers, left);
					return;
				}
				this.call("create_match", { lines: names, vouchers }).then(() => {
					dialog.hide();
					this.done(__("Matched"));
				});
			},
		});

		const draw = () => {
			const text = (dialog.get_value("search") || "").toLowerCase();
			const shown = candidates.filter(
				(d) =>
					!text ||
					[d.title, d.voucher_no, d.reference_no, String(Math.abs(d.amount))].join(" ").toLowerCase().includes(text)
			);
			const picked_total = candidates
				.filter((d) => picked.has(`${d.voucher_type}||${d.voucher_no}`))
				.reduce((sum, d) => sum + d.amount, 0);
			const left = flt(total - picked_total, 2);
			dialog.fields_dict.target.$wrapper.html(`
				<div class="bank-rec"><div class="br-stats">
					<div class="br-stat"><small>${__("Statement lines ({0})", [names.length])}</small><b>${this.money(Math.abs(total))}</b></div>
					<div class="br-stat"><small>${__("Entries ticked")}</small><b>${this.money(Math.abs(picked_total))}</b></div>
					<div class="br-stat ${left ? "bad" : "good"}"><small>${__("Left over")}</small><b>${this.money(Math.abs(left))}</b></div>
				</div>
				${
					left && picked.size
						? `<p class="br-help">${__("The totals are not equal. Pressing Match will ask how to enter the amount left over.")}</p>`
						: ""
				}</div>`);
			dialog.fields_dict.list.$wrapper.html(
				shown.length
					? `<div class="bank-rec"><table class="table br-table"><tbody>${shown
							.map((d) => {
								const key = `${d.voucher_type}||${d.voucher_no}`;
								return `<tr>
								<td style="width:30px"><input type="checkbox" class="br-pick" data-key="${this.esc(key)}" ${
									picked.has(key) ? "checked" : ""
								}></td>
								<td>${this.date(d.posting_date)}</td>
								<td><b>${this.esc(d.title)}</b><br><span class="br-meta">${this.esc(d.voucher_no)}${
									d.reference_no ? ` · ${__("Ref")} ${this.esc(d.reference_no)}` : ""
								}</span></td>
								<td class="text-right">${this.money(Math.abs(d.amount))}</td></tr>`;
							})
							.join("")}</tbody></table></div>`
					: `<div class="bank-rec"><div class="br-empty">${__(
							"No entry in the books that is not yet matched. Use New Entry to record this line."
					  )}</div></div>`
			);
		};

		dialog.fields_dict.list.$wrapper.on("change", ".br-pick", (e) => {
			const key = $(e.currentTarget).data("key");
			if (e.currentTarget.checked) picked.add(key);
			else picked.delete(key);
			draw();
		});
		dialog.fields_dict.search.$input.on("input", () => draw());
		dialog.show();
		draw();
	}

	new_entry(names, vouchers, amount) {
		const lines = this.get_lines(names);
		const total = amount === undefined ? this.lines_total(names) : amount;
		const first = lines[0];
		const dialog = new frappe.ui.Dialog({
			title: total > 0 ? __("Enter Money Received") : __("Enter Money Paid"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${
						vouchers && vouchers.length
							? __("This enters the amount left over, {0}, and matches everything together.", [
									this.money(Math.abs(total)),
							  ])
							: __("{0} of {1}", [this.money(Math.abs(total)), this.date(first.date)])
					} · ${this.esc(first.description)}</p>`,
				},
				{
					fieldtype: "Select",
					fieldname: "party_or_ledger",
					label: total > 0 ? __("Received From") : __("Paid To"),
					options: ["Ledger Account", "Customer", "Supplier"],
					default: "Ledger Account",
					reqd: 1,
				},
				{
					fieldtype: "Link",
					fieldname: "ledger_account",
					label: __("Account"),
					options: "Account",
					depends_on: 'eval:doc.party_or_ledger=="Ledger Account"',
					mandatory_depends_on: 'eval:doc.party_or_ledger=="Ledger Account"',
					get_query: () => ({
						filters: {
							account_type: ["not in", ["Receivable", "Payable", "Stock"]],
							is_group: 0,
							disabled: 0,
							company: this.frm.doc.company,
							name: ["!=", this.frm.doc.bank_account],
						},
					}),
				},
				{
					fieldtype: "Link",
					fieldname: "customer",
					label: __("Customer"),
					options: "Customer",
					depends_on: 'eval:doc.party_or_ledger=="Customer"',
					mandatory_depends_on: 'eval:doc.party_or_ledger=="Customer"',
				},
				{
					fieldtype: "Link",
					fieldname: "supplier",
					label: __("Supplier"),
					options: "Supplier",
					depends_on: 'eval:doc.party_or_ledger=="Supplier"',
					mandatory_depends_on: 'eval:doc.party_or_ledger=="Supplier"',
				},
				{ fieldtype: "Small Text", fieldname: "remarks", label: __("Note"), default: first.description },
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Check",
					fieldname: "save_rule",
					label: __("Do the same next time for lines like this"),
				},
				{
					fieldtype: "Data",
					fieldname: "rule_text",
					label: __("When the description contains"),
					depends_on: "save_rule",
					mandatory_depends_on: "save_rule",
					default: (first.description || "").replace(/[0-9]+/g, " ").replace(/\s+/g, " ").trim(),
				},
			],
			primary_action_label: __("Enter and Match"),
			primary_action: (values) => {
				const entry = {
					party_or_ledger: values.party_or_ledger,
					ledger_account: values.ledger_account,
					party: values.party_or_ledger === "Customer" ? values.customer : values.supplier,
					remarks: values.remarks,
					save_rule: values.save_rule,
					rule_text: values.rule_text,
				};
				this.call("create_entry_and_match", { lines: names, entry, vouchers: vouchers || [] }).then(() => {
					dialog.hide();
					this.done(__("Entered and matched"));
				});
			},
		});
		dialog.show();
	}

	transfer(names) {
		const total = this.lines_total(names);
		frappe.prompt(
			[
				{
					fieldtype: "Link",
					fieldname: "other_account",
					label: total > 0 ? __("Money Came From Our Account") : __("Money Went to Our Account"),
					options: "Account",
					reqd: 1,
					get_query: () => ({
						filters: {
							account_type: ["in", ["Bank", "Cash"]],
							is_group: 0,
							company: this.frm.doc.company,
							name: ["!=", this.frm.doc.bank_account],
						},
					}),
				},
			],
			(values) =>
				this.call("create_transfer_and_match", { lines: names, other_account: values.other_account }).then(() =>
					this.done(__("Transfer entered and matched"))
				),
			__("Transfer Between Our Own Accounts"),
			__("Enter and Match")
		);
	}

	delete_lines(names) {
		frappe.confirm(__("Remove this line from the statement?"), () =>
			this.call("delete_statement_lines", { lines: names }).then(() => this.done())
		);
	}

	undo(bank_match, created) {
		const run = (cancel_created_entries) =>
			this.call("undo_match", { bank_match, cancel_created_entries }).then(() => this.done(__("Match undone")));
		if (!cint(created)) {
			run(0);
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Undo Match"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${__(
						"This match made a new entry in the books. Cancel that entry too, or keep it and only undo the match?"
					)}</p>`,
				},
			],
			primary_action_label: __("Undo and Cancel the Entry"),
			primary_action: () => {
				dialog.hide();
				run(1);
			},
			secondary_action_label: __("Undo, Keep the Entry"),
			secondary_action: () => {
				dialog.hide();
				run(0);
			},
		});
		dialog.show();
	}

	tick_selected() {
		const vouchers = this.wrapper
			.find(".br-entry-check:checked")
			.map((i, el) => ({ voucher_type: $(el).data("type"), voucher_no: String($(el).data("no")) }))
			.get();
		if (!vouchers.length) {
			frappe.msgprint(__("Tick the entries that appear on the statement first."));
			return;
		}
		frappe.prompt(
			[
				{
					fieldtype: "Select",
					fieldname: "how",
					label: __("Date on the Statement"),
					options: [__("Same as each entry's own date"), __("One date for all")],
					default: __("Same as each entry's own date"),
				},
				{
					fieldtype: "Date",
					fieldname: "clearance_date",
					label: __("Date"),
					depends_on: `eval:doc.how=="${__("One date for all")}"`,
					mandatory_depends_on: `eval:doc.how=="${__("One date for all")}"`,
				},
			],
			(values) =>
				this.call("mark_cleared", {
					vouchers,
					clearance_date: values.how === __("One date for all") ? values.clearance_date : null,
				}).then(() => this.done(__("{0} entries agreed", [vouchers.length]))),
			__("{0} Entries Are on the Statement", [vouchers.length]),
			__("Confirm")
		);
	}

	add_line() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add a Statement Line"),
			fields: [
				{ fieldtype: "Date", fieldname: "date", label: __("Date"), reqd: 1, default: this.frm.doc.to_date },
				{ fieldtype: "Data", fieldname: "description", label: __("Description") },
				{ fieldtype: "Data", fieldname: "reference_no", label: __("Cheque or Reference No") },
				{ fieldtype: "Column Break" },
				{ fieldtype: "Currency", fieldname: "deposit", label: __("Money In") },
				{ fieldtype: "Currency", fieldname: "withdrawal", label: __("Money Out") },
			],
			primary_action_label: __("Add"),
			primary_action: (values) =>
				this.call("add_statement_line", values).then(() => {
					dialog.hide();
					this.tab = "to_check";
					this.done(__("Line added"));
				}),
		});
		dialog.show();
	}

	mark_all() {
		frappe.prompt(
			[
				{
					fieldtype: "HTML",
					options: `<p>${__(
						"Use this once, when you start reconciling an account that already has history. Every entry in the books up to the date below is treated as already agreed with the bank, so only newer entries are left to check."
					)}</p>`,
				},
				{
					fieldtype: "Date",
					fieldname: "up_to_date",
					label: __("Up To and Including"),
					reqd: 1,
					default: frappe.datetime.add_days(this.frm.doc.from_date, -1),
				},
			],
			(values) =>
				this.call("mark_all_cleared", values).then((count) => this.done(__("{0} entries marked as agreed", [count]))),
			__("Mark Old Entries as Agreed"),
			__("Mark")
		);
	}

	close() {
		this.call("close_reconciliation").then(() => {
			frappe.show_alert({ message: __("Reconciliation closed"), indicator: "green" });
			this.frm.reload_doc();
		});
	}

	// ----------------------------------------------------------------------------------------
	// Statement upload
	// ----------------------------------------------------------------------------------------

	upload() {
		new frappe.ui.FileUploader({
			doctype: this.frm.doctype,
			docname: this.frm.docname,
			frm: this.frm,
			allow_multiple: false,
			restrictions: { allowed_file_types: [".csv", ".xlsx", ".xls", ".pdf"] },
			on_success: (file) => this.preview_statement(file.file_url),
		});
	}

	preview_statement(file_url, layout) {
		this.call("read_statement_file", { file_url, layout: layout || null }, __("Reading the statement...")).then((result) =>
			this.show_preview(file_url, result)
		);
	}

	show_preview(file_url, result) {
		const header = result.header || {};
		const facts = [
			[__("Bank"), header.bank_name],
			[__("Account title"), header.account_title],
			[__("Account number"), header.iban || header.account_number],
			[
				__("Period"),
				header.period_from || header.period_to ? `${this.date(header.period_from)} – ${this.date(header.period_to)}` : null,
			],
			[__("Opening balance"), header.opening_balance == null ? null : this.money(header.opening_balance)],
			[__("Closing balance"), header.closing_balance == null ? null : this.money(header.closing_balance)],
		].filter((d) => d[1]);

		const check = result.account_check || {};
		const check_class = { ok: "good", mismatch: "bad", unknown: "warn" }[check.status] || "warn";
		const columns = result.columns || [];
		const layout = result.layout || {};
		const column_options = [{ value: "", label: __("(none)") }].concat(
			columns.map((label, index) => ({ value: String(index), label: `${index + 1}. ${label || __("(no heading)")}` }))
		);
		const roles = [
			["date", __("Date")],
			["description", __("Description")],
			["reference", __("Cheque or Reference No")],
			["withdrawal", __("Money Out")],
			["deposit", __("Money In")],
			["amount", __("Single Amount Column")],
			["dr_cr", __("Dr / Cr Marker Column")],
			["balance", __("Balance")],
		];
		const current = (role) => {
			const value = layout[role];
			if (Array.isArray(value)) return value.length ? String(value[0]) : "";
			return value == null ? "" : String(value);
		};

		const dialog = new frappe.ui.Dialog({
			title: __("Check the Statement Before Adding It"),
			size: "extra-large",
			fields: [
				{ fieldtype: "HTML", fieldname: "found" },
				{ fieldtype: "Section Break", label: __("Columns Read Wrongly? Correct Them Here"), collapsible: 1 },
				...roles.map(([role, label]) => ({
					fieldtype: "Select",
					fieldname: `column_${role}`,
					label,
					options: column_options,
					default: current(role),
				})),
				{ fieldtype: "Button", fieldname: "reread", label: __("Read Again With These Columns") },
			],
			primary_action_label: __("Add {0} Lines", [result.line_count]),
			primary_action: () => {
				this.call(
					"import_statement_file",
					{ file_url, layout: result.layout || null },
					__("Adding the statement lines...")
				).then((r) => {
					dialog.hide();
					let message = __("{0} lines added.", [r.added]);
					if (r.skipped) message += " " + __("{0} lines were already on a statement of this account and were left out.", [r.skipped]);
					frappe.msgprint({ title: __("Statement Added"), message, indicator: "green" });
					this.tab = "to_check";
					this.frm.reload_doc();
				});
			},
		});

		dialog.fields_dict.found.$wrapper.html(`
			<div class="bank-rec">
				${
					facts.length
						? `<div class="br-facts">${facts
								.map(([label, value]) => `<div><small>${label}</small><b>${this.esc(value)}</b></div>`)
								.join("")}</div>`
						: ""
				}
				${check.message ? `<div class="br-verdict ${check_class}">${this.esc(check.message)}</div>` : ""}
				${(result.warnings || []).map((d) => `<div class="br-verdict warn">${this.esc(d)}</div>`).join("")}
				<p class="br-help">${__("{0} lines were read. The first ones are shown below; check that the dates and the money in and out look right.", [
					result.line_count,
				])}</p>
				<table class="table br-table">
					<thead><tr><th>${__("Date")}</th><th>${__("Description")}</th><th>${__("Reference")}</th>
					<th class="text-right">${__("Money In")}</th><th class="text-right">${__("Money Out")}</th><th class="text-right">${__(
			"Balance"
		)}</th></tr></thead>
					<tbody>${(result.lines || [])
						.slice(0, 12)
						.map(
							(d) => `<tr><td>${this.date(d.date)}</td><td>${this.esc(d.description)}</td><td>${this.esc(d.reference_no)}</td>
							<td class="text-right">${flt(d.deposit) ? this.money(d.deposit) : ""}</td>
							<td class="text-right">${flt(d.withdrawal) ? this.money(d.withdrawal) : ""}</td>
							<td class="text-right">${d.balance == null ? "" : this.money(d.balance)}</td></tr>`
						)
						.join("")}</tbody>
				</table>
			</div>`);

		dialog.fields_dict.reread.$input.on("click", () => {
			const new_layout = Object.assign({}, layout);
			for (const [role] of roles) {
				const value = dialog.get_value(`column_${role}`);
				const index = value === "" || value == null ? null : cint(value);
				new_layout[role] = role === "description" ? (index === null ? [] : [index]) : index;
			}
			dialog.hide();
			this.preview_statement(file_url, new_layout);
		});
		if (!columns.length) dialog.fields_dict.reread.$wrapper.closest(".form-section").hide();
		dialog.show();
	}

	// ----------------------------------------------------------------------------------------
	// Printing
	// ----------------------------------------------------------------------------------------

	print() {
		const doc = this.frm.doc;
		const outstanding = this.data.not_on_statement;
		const table = (rows) =>
			rows.length
				? `<table><thead><tr><th>${__("Date")}</th><th>${__("Entry")}</th><th>${__("Reference")}</th><th class="r">${__(
						"Amount"
				  )}</th></tr></thead><tbody>${rows
						.map(
							(d) =>
								`<tr><td>${this.date(d.posting_date)}</td><td>${this.esc(d.title)} (${this.esc(d.voucher_no)})</td><td>${this.esc(
									d.reference_no
								)}</td><td class="r">${this.money(Math.abs(d.amount))}</td></tr>`
						)
						.join("")}</tbody></table>`
				: `<p>${__("None")}</p>`;
		const html = `
			<html><head><title>${__("Bank Reconciliation Statement")}</title><style>
				body { font: 13px/1.5 -apple-system, "Segoe UI", sans-serif; color: #111; margin: 32px; }
				h1 { font-size: 18px; margin: 0; } h2 { font-size: 14px; margin: 22px 0 6px; }
				table { width: 100%; border-collapse: collapse; } td, th { padding: 5px 8px; border-bottom: 1px solid #ddd; text-align: left; }
				.r { text-align: right; } .strong td { font-weight: 700; } .muted { color: #555; }
			</style></head><body>
				<h1>${__("Bank Reconciliation Statement")}</h1>
				<div class="muted">${this.esc(doc.company)} · ${this.esc(doc.bank_account)} · ${this.date(doc.from_date)} – ${this.date(
			doc.to_date
		)}</div>
				<h2>${__("Summary")}</h2>
				<table>${this.summary_rows()
					.map(
						([label, value, strong]) =>
							`<tr class="${strong ? "strong" : ""}"><td>${label}</td><td class="r">${this.money(value)}</td></tr>`
					)
					.join("")}</table>
				<h2>${__("Payments we made that are not on the statement yet")}</h2>
				${table(outstanding.filter((d) => d.amount < 0))}
				<h2>${__("Money we received that is not on the statement yet")}</h2>
				${table(outstanding.filter((d) => d.amount > 0))}
			</body></html>`;
		const win = window.open("", "_blank");
		win.document.write(html);
		win.document.close();
		win.focus();
		win.print();
	}
};

const BANK_REC_CSS = `
.bank-rec { --br-line: var(--border-color, #dfe3e9); --br-muted: var(--text-muted, #6b7686); }
.bank-rec .br-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.bank-rec .br-stat { border: 1px solid var(--br-line); border-radius: 10px; padding: 10px 12px; background: var(--card-bg, #fff); }
.bank-rec .br-stat small { display: block; color: var(--br-muted); }
.bank-rec .br-stat b { font-size: 17px; font-variant-numeric: tabular-nums; }
.bank-rec .br-stat.bad b { color: var(--red-600, #b3261e); }
.bank-rec .br-stat.good b { color: var(--green-600, #1e7d46); }
.bank-rec .br-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; align-items: center; }
.bank-rec .br-closed { color: var(--br-muted); margin-right: 6px; }
.bank-rec .br-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.bank-rec .br-tab { padding: 5px 12px; border-radius: 999px; border: 1px solid var(--br-line); color: var(--br-muted); cursor: pointer; text-decoration: none; }
.bank-rec .br-tab.on { background: var(--primary, #0b6e6e); border-color: var(--primary, #0b6e6e); color: #fff; }
.bank-rec .br-heading, .bank-rec .br-row { display: grid; grid-template-columns: minmax(0, 1fr) 64px minmax(0, 1fr); gap: 0; }
.bank-rec .br-heading { color: var(--br-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; }
.bank-rec .br-row { margin-bottom: 10px; align-items: stretch; }
.bank-rec .br-card { border: 1px solid var(--br-line); border-radius: 10px; padding: 9px 12px; background: var(--card-bg, #fff); height: 100%; }
.bank-rec .br-row > div > .br-card + .br-card { margin-top: 6px; }
.bank-rec .br-card.match { border-color: var(--green-500, #1e7d46); background: var(--green-50, #e6f4ec); }
.bank-rec .br-card.rule { border-color: var(--blue-400, #4a90d9); background: var(--blue-50, #eaf3fc); }
.bank-rec .br-mid { display: flex; align-items: center; justify-content: center; }
.bank-rec .br-top { display: flex; justify-content: space-between; gap: 10px; }
.bank-rec .br-amount { font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.bank-rec .br-amount.in { color: var(--green-600, #1e7d46); }
.bank-rec .br-meta { color: var(--br-muted); font-size: 12.5px; }
.bank-rec .br-pill-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.bank-rec .br-pill { font-size: 12px; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--br-line); color: var(--br-muted); }
.bank-rec .br-pill.on { color: var(--green-700, #17623a); border-color: var(--green-500, #1e7d46); font-weight: 600; }
.bank-rec .br-card.rule .br-pill.on { color: var(--blue-700, #1f5a99); border-color: var(--blue-400, #4a90d9); }
.bank-rec .br-buttons { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.bank-rec .br-quiet { opacity: .7; }
.bank-rec .br-hr { margin: 6px 0; border-color: var(--br-line); }
.bank-rec .br-empty { border: 1px dashed var(--br-line); border-radius: 10px; padding: 26px; text-align: center; color: var(--br-muted); }
.bank-rec .br-help { color: var(--br-muted); }
.bank-rec .br-selection { position: sticky; top: 60px; z-index: 5; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
	background: var(--fg-color, #fff); border: 1px solid var(--primary, #0b6e6e); border-radius: 10px; padding: 8px 12px; margin-bottom: 10px; }
.bank-rec .br-table td, .bank-rec .br-table th { vertical-align: middle; font-variant-numeric: tabular-nums; }
.bank-rec .br-summary { max-width: 640px; }
.bank-rec .br-summary tr.strong td { font-weight: 700; }
.bank-rec .br-verdict { border-radius: 8px; padding: 8px 12px; margin-bottom: 10px; }
.bank-rec .br-verdict.good { background: var(--green-50, #e6f4ec); color: var(--green-700, #17623a); }
.bank-rec .br-verdict.bad { background: var(--red-50, #fdecea); color: var(--red-700, #8f1d17); }
.bank-rec .br-verdict.warn { background: var(--yellow-50, #fdf1dc); color: var(--yellow-800, #7a4700); }
.bank-rec .br-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 16px; margin-bottom: 10px; }
.bank-rec .br-facts small { display: block; color: var(--br-muted); }
.bank-rec .br-facts > div { min-width: 0; overflow-wrap: anywhere; }
@media (max-width: 760px) {
	.bank-rec .br-heading { display: none; }
	.bank-rec .br-row { grid-template-columns: 1fr; }
	.bank-rec .br-mid { padding: 6px 0; }
}
`;
