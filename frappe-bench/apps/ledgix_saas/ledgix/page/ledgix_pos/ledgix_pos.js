frappe.pages["ledgix-pos"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "Ledgix Restaurant POS", single_column: true });
	new LedgixRestaurantPOS(page, wrapper);
};

class LedgixRestaurantPOS {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.state = {
			branch: "",
			channel: "Dine In",
			boot: null,
			catalog: { sections: [], items: [] },
			selectedSection: "",
			activeOrder: null,
			activeSession: null,
			loading: false,
			settlementIds: {},
		};
		this.realtimeTimer = null;
		this.renderShell();
		this.bindEvents();
		this.bindRealtime();
		this.boot();
	}

	async call(method, args = {}) {
		const response = await frappe.call({ method, args, freeze: false });
		return response.message || {};
	}

	escape(value) { return frappe.utils.escape_html(String(value == null ? "" : value)); }
	money(value) { return `Rs. ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`; }
	uuid(prefix) {
		const id = window.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
		return `${prefix}-${id}`;
	}
	settlementId(orderName) {
		if (!this.state.settlementIds[orderName]) this.state.settlementIds[orderName] = this.uuid("settle");
		return this.state.settlementIds[orderName];
	}

	renderShell() {
		$(this.page.body).html(`
			<div class="lx-rpos">
				<header class="lx-rpos-toolbar">
					<div class="lx-rpos-context">
						<label>Branch<select class="lx-branch-select"></select></label>
						<div class="lx-order-types" role="group" aria-label="Order type">
							<button data-channel="Dine In" class="active">Dine In</button>
							<button data-channel="Takeaway">Takeaway</button>
							<button data-channel="Delivery">Delivery</button>
						</div>
						<div class="lx-menu-fact"><span>Menu</span><strong class="lx-menu-name">—</strong></div>
					</div>
					<div class="lx-rpos-actions">
						<span class="lx-shift-badge">Shift —</span>
						<button class="btn btn-default btn-sm lx-open-checks">Open checks</button>
						<button class="btn btn-default btn-sm lx-refresh">Refresh</button>
						<button class="btn btn-primary btn-sm lx-new-check">New check</button>
					</div>
				</header>
				<div class="lx-rpos-workspace">
					<aside class="lx-floor-pane">
						<div class="lx-pane-title"><div><strong>Tables</strong><span class="lx-table-subtitle">Select a table</span></div></div>
						<div class="lx-floor-tabs"></div>
						<div class="lx-table-grid"></div>
					</aside>
					<main class="lx-menu-pane">
						<div class="lx-menu-search"><span>⌕</span><input class="lx-menu-search-input" placeholder="Search menu…" autocomplete="off"></div>
						<div class="lx-section-tabs"></div>
						<div class="lx-menu-grid"></div>
					</main>
					<aside class="lx-check-pane">
						<div class="lx-check-empty"><strong>No open check</strong><span>Select a table or start a takeaway/delivery check.</span></div>
						<div class="lx-check-live hidden">
							<div class="lx-check-head"></div>
							<div class="lx-check-lines"></div>
							<div class="lx-check-summary"></div>
							<div class="lx-held-courses"></div>
							<div class="lx-check-actions">
								<button class="btn btn-default lx-manage-check">Manage</button>
								<button class="btn btn-default lx-split-check">Split</button>
								<button class="btn btn-default lx-transfer-table">Move table</button>
								<button class="btn btn-default lx-fire-order">Send to kitchen</button>
								<button class="btn btn-primary lx-settle-check">Settle check</button>
							</div>
						</div>
					</aside>
				</div>
			</div>`);
		this.$root = $(this.page.body).find(".lx-rpos");
	}

	bindEvents() {
		this.$root.on("change", ".lx-branch-select", e => this.switchBranch($(e.currentTarget).val()));
		this.$root.on("click", ".lx-order-types button", e => this.switchChannel($(e.currentTarget).data("channel")));
		this.$root.on("click", ".lx-refresh", () => this.refreshAll());
		this.$root.on("click", ".lx-new-check", () => this.startNewCheck());
		this.$root.on("click", ".lx-open-checks", () => this.showOpenChecks());
		this.$root.on("click", ".lx-floor-tab", e => this.selectFloor($(e.currentTarget).data("floor")));
		this.$root.on("click", ".lx-table-card", e => this.selectTable($(e.currentTarget).data("table")));
		this.$root.on("click", ".lx-section-tab", e => this.selectSection($(e.currentTarget).data("section")));
		this.$root.on("input", ".lx-menu-search-input", () => this.renderMenu());
		this.$root.on("click", ".lx-menu-card:not(.unavailable)", e => this.addMenuItem($(e.currentTarget).data("menu-item")));
		this.$root.on("click", ".lx-line-plus", e => this.changeLineQuantity($(e.currentTarget).closest(".lx-check-line").data("item"), 1));
		this.$root.on("click", ".lx-line-minus", e => this.changeLineQuantity($(e.currentTarget).closest(".lx-check-line").data("item"), -1));
		this.$root.on("click", ".lx-line-edit", e => this.editLine($(e.currentTarget).closest(".lx-check-line").data("item")));
		this.$root.on("click", ".lx-line-void", e => this.voidLine($(e.currentTarget).closest(".lx-check-line").data("item")));
		this.$root.on("click", ".lx-fire-order", () => this.fireOrder());
		this.$root.on("click", ".lx-fire-course", e => this.fireCourse($(e.currentTarget).data("course")));
		this.$root.on("click", ".lx-manage-check", () => this.manageCheck());
		this.$root.on("click", ".lx-split-check", () => this.splitCheck());
		this.$root.on("click", ".lx-transfer-table", () => this.transferTable());
		this.$root.on("click", ".lx-settle-check", () => this.openSettlement());
	}

	bindRealtime() {
		const schedule = payload => {
			if (!payload || !this.state.branch || payload.branch !== this.state.branch) return;
			clearTimeout(this.realtimeTimer);
			this.realtimeTimer = setTimeout(() => this.refreshAll(), 240);
		};
		if (window.__ledgix_rpos_order_handler && frappe.realtime.off) frappe.realtime.off("ledgix_restaurant_order_update", window.__ledgix_rpos_order_handler);
		if (window.__ledgix_rpos_kds_handler && frappe.realtime.off) frappe.realtime.off("ledgix_kds_update", window.__ledgix_rpos_kds_handler);
		window.__ledgix_rpos_order_handler = schedule;
		window.__ledgix_rpos_kds_handler = schedule;
		frappe.realtime.on("ledgix_restaurant_order_update", schedule);
		frappe.realtime.on("ledgix_kds_update", schedule);
	}

	setLoading(value) {
		this.state.loading = !!value;
		this.$root.toggleClass("is-loading", this.state.loading);
	}

	async boot() {
		this.setLoading(true);
		try {
			const data = await this.call("ledgix_saas.api.restaurant_pos.boot", {
				branch: this.state.branch || null,
				channel: this.state.channel,
			});
			this.applyBoot(data);
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	applyBoot(data) {
		this.state.boot = data;
		this.state.branch = data.branch;
		this.state.channel = data.channel;
		this.state.catalog = data.catalog || { sections: [], items: [] };
		const sections = this.state.catalog.sections || [];
		if (!sections.some(row => row.section === this.state.selectedSection)) this.state.selectedSection = sections[0]?.section || "";
		this.renderToolbar();
		this.renderTables();
		this.renderSections();
		this.renderMenu();
		this.renderCheck();
	}

	renderToolbar() {
		const boot = this.state.boot || {};
		this.$root.find(".lx-branch-select").html((boot.branches || []).map(row => `<option value="${this.escape(row.name)}" ${row.name === this.state.branch ? "selected" : ""}>${this.escape(row.branch_name || row.name)}</option>`).join(""));
		this.$root.find(".lx-order-types button").removeClass("active").filter(`[data-channel="${this.state.channel}"]`).addClass("active");
		this.$root.find(".lx-menu-name").text(boot.menu_name || boot.menu || "—");
		this.$root.find(".lx-shift-badge").toggleClass("open", !!boot.active_shift).text(boot.active_shift ? `Shift ${boot.active_shift}` : "No open shift");
		this.$root.find(".lx-floor-pane").toggleClass("hidden", this.state.channel !== "Dine In");
		this.$root.find(".lx-rpos-workspace").toggleClass("without-floor", this.state.channel !== "Dine In");
		this.$root.find(".lx-transfer-table, .lx-manage-check").toggleClass("hidden", this.state.channel !== "Dine In" || !this.state.activeOrder);
	}

	async switchBranch(branch) {
		if (!branch || branch === this.state.branch) return;
		this.state.branch = branch;
		this.state.activeOrder = null;
		this.state.activeSession = null;
		await this.boot();
	}

	async switchChannel(channel) {
		if (!channel || channel === this.state.channel) return;
		this.state.channel = channel;
		this.state.activeOrder = null;
		this.state.activeSession = null;
		await this.boot();
	}

	async refreshAll({ keepOrder = true } = {}) {
		const orderName = keepOrder ? this.state.activeOrder?.name : null;
		await this.boot();
		if (orderName) {
			try {
				const order = await this.call("ledgix_saas.api.restaurant_orders.get_check", { restaurant_order: orderName });
				this.state.activeOrder = ["Closed", "Voided"].includes(order.status) ? null : order;
			} catch (_) { this.state.activeOrder = null; }
			this.renderCheck();
		}
	}

	selectFloor(floor) { this.state.boot.table_map.active_floor = floor; this.renderTables(); }

	renderTables() {
		if (this.state.channel !== "Dine In") return;
		const floors = this.state.boot?.table_map?.floors || [];
		let activeFloor = this.state.boot?.table_map?.active_floor;
		if (!floors.some(row => row.name === activeFloor)) activeFloor = floors[0]?.name || "";
		if (this.state.boot?.table_map) this.state.boot.table_map.active_floor = activeFloor;
		this.$root.find(".lx-floor-tabs").html(floors.map(row => `<button class="lx-floor-tab ${row.name === activeFloor ? "active" : ""}" data-floor="${this.escape(row.name)}">${this.escape(row.floor_name || row.name)}</button>`).join(""));
		const floor = floors.find(row => row.name === activeFloor);
		const tables = floor?.tables || [];
		this.$root.find(".lx-table-grid").html(tables.length ? tables.map(table => `
			<button class="lx-table-card state-${this.escape(String(table.state || "Available").toLowerCase().replaceAll(" ", "-"))}" data-table="${this.escape(table.name)}">
				<div class="lx-table-top"><strong>${this.escape(table.table_name || table.table_code)}</strong><span>${this.escape(table.state || "Available")}</span></div>
				<div class="lx-table-meta"><span>${table.covers ? `${table.covers} covers` : `${table.capacity || 0} seats`}</span><span>${table.open_checks ? `${table.open_checks} check${table.open_checks === 1 ? "" : "s"}` : "Open"}</span></div>
				${table.session_total ? `<div class="lx-table-total">${this.money(table.session_total)}</div>` : ""}
			</button>`).join("") : `<div class="lx-empty-state">No active tables on this floor.</div>`);
	}

	async selectTable(tableName) {
		const table = this.findTable(tableName);
		if (!table) return;
		if (table.table_session) {
			this.state.activeSession = table.table_session;
			if ((table.checks || []).length === 1) return this.loadOrder(table.checks[0].name);
			if ((table.checks || []).length > 1) return this.showChecksForTable(table);
			return this.openCheckForSession(table.table_session);
		}
		const values = await this.promptValues("Open table", [
			{ fieldname: "covers", fieldtype: "Int", label: "Covers", default: Math.min(Number(table.capacity || 2), 2), reqd: 1 },
			{ fieldname: "guest_name", fieldtype: "Data", label: "Guest name" },
		]);
		if (!values) return;
		this.setLoading(true);
		try {
			const session = await this.call("ledgix_saas.api.restaurant_orders.open_session", {
				restaurant_table: table.name,
				covers: values.covers,
				guest_name: values.guest_name,
				request_id: this.uuid("session"),
			});
			this.state.activeSession = session.name;
			await this.openCheckForSession(session.name, values.covers);
			await this.refreshAll();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	findTable(tableName) {
		for (const floor of this.state.boot?.table_map?.floors || []) {
			const table = (floor.tables || []).find(row => row.name === tableName);
			if (table) return table;
		}
		return null;
	}

	currentTable() {
		const session = this.state.activeOrder?.table_session;
		if (!session) return null;
		for (const floor of this.state.boot?.table_map?.floors || []) {
			const table = (floor.tables || []).find(row => row.table_session === session);
			if (table) return table;
		}
		return null;
	}

	async openCheckForSession(sessionName, covers = null) {
		const order = await this.call("ledgix_saas.api.restaurant_orders.open_check", {
			order_type: "Dine In",
			table_session: sessionName,
			covers: covers || 1,
			client_order_id: this.uuid("check"),
		});
		this.state.activeOrder = order;
		this.state.activeSession = order.table_session;
		this.renderCheck();
	}

	async startNewCheck() {
		if (this.state.channel === "Dine In") {
			frappe.show_alert({ message: "Select an available table to open a dine-in check.", indicator: "blue" });
			return;
		}
		const fields = this.state.channel === "Takeaway"
			? [{ fieldname: "pickup_name", fieldtype: "Data", label: "Pickup name" }, { fieldname: "contact_phone", fieldtype: "Data", label: "Phone" }]
			: [{ fieldname: "pickup_name", fieldtype: "Data", label: "Guest name" }, { fieldname: "contact_phone", fieldtype: "Data", label: "Phone" }, { fieldname: "delivery_address", fieldtype: "Small Text", label: "Delivery address", reqd: 1 }];
		const values = await this.promptValues(`New ${this.state.channel} check`, fields);
		if (!values) return;
		this.setLoading(true);
		try {
			this.state.activeOrder = await this.call("ledgix_saas.api.restaurant_orders.open_check", {
				order_type: this.state.channel,
				branch: this.state.branch,
				menu: this.state.boot.menu,
				pickup_name: values.pickup_name,
				contact_phone: values.contact_phone,
				delivery_address: values.delivery_address,
				client_order_id: this.uuid("check"),
			});
			this.renderCheck();
			await this.refreshAll();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async loadOrder(name) {
		this.setLoading(true);
		try {
			this.state.activeOrder = await this.call("ledgix_saas.api.restaurant_orders.get_check", { restaurant_order: name });
			this.state.activeSession = this.state.activeOrder.table_session;
			this.renderCheck();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	showChecksForTable(table) {
		const dialog = new frappe.ui.Dialog({ title: `${table.table_name || table.table_code} · Open checks`, fields: [{ fieldtype: "HTML", fieldname: "list" }] });
		dialog.fields_dict.list.$wrapper.html(`<div class="lx-dialog-list">${(table.checks || []).map(row => `<button class="lx-dialog-row" data-order="${this.escape(row.name)}"><span><strong>${this.escape(row.name)}</strong><small>${this.escape(row.status)} · ${row.covers || 0} covers</small></span><b>${this.money(row.grand_total)}</b></button>`).join("")}</div><button class="btn btn-default btn-sm lx-dialog-new-check">+ New sibling check</button>`);
		dialog.$wrapper.on("click", ".lx-dialog-row", e => { dialog.hide(); this.loadOrder($(e.currentTarget).data("order")); });
		dialog.$wrapper.on("click", ".lx-dialog-new-check", async () => { dialog.hide(); await this.openCheckForSession(table.table_session, table.covers || 1); await this.refreshAll(); });
		dialog.show();
	}

	showOpenChecks() {
		const rows = this.state.boot?.open_checks || [];
		const dialog = new frappe.ui.Dialog({ title: `${this.state.channel} · Open checks`, fields: [{ fieldtype: "HTML", fieldname: "list" }] });
		dialog.fields_dict.list.$wrapper.html(rows.length ? `<div class="lx-dialog-list">${rows.map(row => `<button class="lx-dialog-row" data-order="${this.escape(row.name)}"><span><strong>${this.escape(row.table_name_snapshot || row.pickup_name || row.name)}</strong><small>${this.escape(row.status)} · ${this.escape(row.server || "Unassigned")}</small></span><b>${this.money(row.grand_total)}</b></button>`).join("")}</div>` : `<div class="lx-empty-dialog">No open checks.</div>`);
		dialog.$wrapper.on("click", ".lx-dialog-row", e => { dialog.hide(); this.loadOrder($(e.currentTarget).data("order")); });
		dialog.show();
	}

	renderSections() {
		const sections = this.state.catalog?.sections || [];
		this.$root.find(".lx-section-tabs").html(sections.map(row => `<button class="lx-section-tab ${row.section === this.state.selectedSection ? "active" : ""}" data-section="${this.escape(row.section)}">${this.escape(row.name || row.code)}</button>`).join(""));
	}

	selectSection(section) { this.state.selectedSection = section; this.renderSections(); this.renderMenu(); }

	renderMenu() {
		const query = String(this.$root.find(".lx-menu-search-input").val() || "").trim().toLowerCase();
		const rows = (this.state.catalog?.items || []).filter(row => {
			const sectionMatch = !this.state.selectedSection || row.section === this.state.selectedSection;
			const haystack = `${row.display_name || ""} ${row.item_name || ""} ${row.item_code || ""}`.toLowerCase();
			return sectionMatch && (!query || haystack.includes(query));
		});
		this.$root.find(".lx-menu-grid").html(rows.length ? rows.map(row => `
			<button class="lx-menu-card ${row.available ? "" : "unavailable"}" data-menu-item="${this.escape(row.menu_item)}">
				<div class="lx-menu-card-top"><span>${this.escape(row.restaurant_item_type || "Menu Item")}</span>${!row.available ? `<b>86</b>` : ""}</div>
				<strong>${this.escape(row.display_name || row.item_name)}</strong>
				<small>${this.escape(row.description || (row.available ? "" : row.unavailable_reason || "Unavailable"))}</small>
				<div class="lx-menu-card-bottom"><b>${this.money(row.rate)}</b>${(row.modifier_groups || []).length ? `<span>Customizable</span>` : ""}</div>
			</button>`).join("") : `<div class="lx-empty-state">No menu items match this view.</div>`);
	}

	async addMenuItem(menuItemName) {
		if (!this.state.activeOrder) return frappe.show_alert({ message: "Open a check before adding menu items.", indicator: "orange" });
		const item = (this.state.catalog?.items || []).find(row => row.menu_item === menuItemName);
		if (!item || !item.available) return;
		let options = { quantity: 1, modifiers: [], seat_no: 0, course: "", is_course_held: 0, item_note: "" };
		if ((item.modifier_groups || []).length) {
			const selected = await this.modifierDialog(item);
			if (!selected) return;
			options = selected;
		}
		this.setLoading(true);
		try {
			this.state.activeOrder = await this.call("ledgix_saas.api.restaurant_orders.add_item", {
				restaurant_order: this.state.activeOrder.name,
				menu_item: item.menu_item,
				quantity: options.quantity,
				modifiers: options.modifiers,
				seat_no: options.seat_no,
				course: options.course,
				is_course_held: options.is_course_held,
				item_note: options.item_note,
				client_item_id: this.uuid("line"),
			});
			this.renderCheck();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	modifierDialog(item) {
		return new Promise(resolve => {
			let settled = false;
			const dialog = new frappe.ui.Dialog({
				title: item.display_name || item.item_name,
				fields: [
					{ fieldtype: "HTML", fieldname: "mods" },
					{ fieldtype: "Int", fieldname: "quantity", label: "Quantity", default: 1, reqd: 1 },
					{ fieldtype: "Column Break" },
					{ fieldtype: "Int", fieldname: "seat_no", label: "Seat", default: 0 },
					{ fieldtype: "Section Break" },
					{ fieldtype: "Data", fieldname: "course", label: "Course" },
					{ fieldtype: "Check", fieldname: "is_course_held", label: "Hold course" },
					{ fieldtype: "Small Text", fieldname: "item_note", label: "Kitchen note" },
				],
				primary_action_label: "Add to check",
				primary_action: values => {
					const modifiers = [];
					for (const group of item.modifier_groups || []) {
						const checked = dialog.fields_dict.mods.$wrapper.find(`[data-group="${CSS.escape(group.modifier_group)}"] input:checked`);
						if (checked.length < Number(group.min_selection || 0) || (Number(group.max_selection || 0) && checked.length > Number(group.max_selection))) {
							frappe.msgprint(`${this.escape(group.name)} requires ${group.min_selection || 0}${group.max_selection ? `–${group.max_selection}` : "+"} selection(s).`);
							return;
						}
						checked.each((_, input) => modifiers.push({ modifier_option: input.value, quantity: 1 }));
					}
					settled = true;
					dialog.hide();
					resolve({ ...values, modifiers });
				},
			});
			dialog.fields_dict.mods.$wrapper.html((item.modifier_groups || []).map(group => `
				<div class="lx-mod-group" data-group="${this.escape(group.modifier_group)}"><div class="lx-mod-head"><strong>${this.escape(group.name)}</strong><span>${group.required ? "Required" : "Optional"}</span></div>
					<div class="lx-mod-options">${(group.options || []).map(option => `<label><input type="${group.selection_type === "Single" ? "radio" : "checkbox"}" name="mod-${this.escape(group.modifier_group)}" value="${this.escape(option.name)}"><span>${this.escape(option.option_name)}</span><b>${Number(option.price_delta || 0) ? `+${this.money(option.price_delta)}` : "Included"}</b></label>`).join("")}</div>
				</div>`).join(""));
			dialog.onhide = () => { if (!settled) resolve(null); };
			dialog.show();
		});
	}

	renderCheck() {
		const order = this.state.activeOrder;
		this.$root.find(".lx-check-empty").toggleClass("hidden", !!order);
		this.$root.find(".lx-check-live").toggleClass("hidden", !order);
		if (!order) return;
		this.$root.find(".lx-check-head").html(`
			<div><span>${this.escape(order.order_type)}</span><h3>${this.escape(order.table_name || order.pickup_name || order.name)}</h3><small>${this.escape(order.status)} · ${order.covers || 0} covers${order.server ? ` · ${this.escape(order.server)}` : ""}</small></div>
			<button class="btn btn-default btn-xs lx-refresh">↻</button>`);
		const lines = order.items || [];
		this.$root.find(".lx-check-lines").html(lines.length ? lines.map(line => this.lineHtml(line)).join("") : `<div class="lx-empty-state compact">Add menu items to this check.</div>`);
		this.$root.find(".lx-check-summary").html(`
			<div><span>Items</span><strong>${this.money(Number(order.subtotal || 0) + Number(order.modifier_total || 0))}</strong></div>
			${Number(order.discount_amount || 0) ? `<div><span>Discount</span><strong>− ${this.money(order.discount_amount)}</strong></div>` : ""}
			${Number(order.service_charge || 0) ? `<div><span>Service charge</span><strong>${this.money(order.service_charge)}</strong></div>` : ""}
			${Number(order.tip_amount || 0) ? `<div><span>Tip / gratuity</span><strong>${this.money(order.tip_amount)}</strong></div>` : ""}
			<div><span>Tax</span><strong>${this.money(order.tax_amount)}</strong></div>
			<div class="total"><span>Check total</span><strong>${this.money(order.grand_total)}</strong></div>`);
		const activeLines = lines.filter(line => !line.is_voided && Number(line.billable_quantity || 0) > 0);
		const pending = activeLines.reduce((sum, line) => sum + Math.max(Number(line.billable_quantity || 0) - Number(line.fired_quantity || 0), 0), 0);
		this.$root.find(".lx-fire-order").prop("disabled", pending <= 0).text(pending > 0 ? `Send ${pending:g} to kitchen`.replace(":g", "") : "Kitchen sent");
		this.$root.find(".lx-settle-check").prop("disabled", !activeLines.length || pending > 0).attr("title", pending > 0 ? "Fire all billable items before settlement." : "Settle this check");
		this.renderHeldCourses();
		this.renderToolbar();
	}

	lineHtml(line) {
		const locked = Number(line.fired_quantity || 0) > 0;
		const modifiers = (line.modifiers || []).map(row => row.option_name).filter(Boolean).join(", ");
		return `<div class="lx-check-line ${line.is_voided ? "voided" : ""}" data-item="${this.escape(line.name)}">
			<div class="lx-line-main"><strong>${this.escape(line.display_name || line.item)}</strong><span>${this.escape([modifiers, line.course ? `Course: ${line.course}` : "", line.seat_no ? `Seat ${line.seat_no}` : ""].filter(Boolean).join(" · "))}</span>${line.item_note ? `<small>${this.escape(line.item_note)}</small>` : ""}</div>
			<div class="lx-line-state"><span>${this.escape(line.kitchen_status || "Not Sent")}</span><small>${Number(line.fired_quantity || 0) ? `${line.fired_quantity}/${line.quantity} fired` : "Not fired"}</small></div>
			<div class="lx-line-controls">${!locked && !line.is_voided ? `<button class="lx-line-minus">−</button><b>${line.quantity}</b><button class="lx-line-plus">+</button>` : `<b>${line.billable_quantity}</b>`}</div>
			<strong class="lx-line-amount">${this.money(line.net_amount || line.amount)}</strong>
			<div class="lx-line-more">${!locked && !line.is_voided ? `<button class="lx-line-edit" title="Edit">•••</button>` : ""}${!line.is_voided ? `<button class="lx-line-void" title="Void">×</button>` : ""}</div>
		</div>`;
	}

	async changeLineQuantity(itemName, delta) {
		const line = this.state.activeOrder?.items?.find(row => row.name === itemName);
		if (!line || Number(line.fired_quantity || 0) > 0) return;
		const quantity = Number(line.quantity || 0) + delta;
		if (quantity <= 0) return this.voidLine(itemName);
		this.setLoading(true);
		try {
			this.state.activeOrder = await this.call("ledgix_saas.api.restaurant_orders.edit_item", { order_item: itemName, quantity, request_id: this.uuid("edit") });
			this.renderCheck();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async editLine(itemName) {
		const line = this.state.activeOrder?.items?.find(row => row.name === itemName);
		if (!line || Number(line.fired_quantity || 0) > 0) return frappe.msgprint("Fired item context is locked. Void/re-add the item for a kitchen-visible change.");
		const values = await this.promptValues("Edit item", [
			{ fieldname: "seat_no", fieldtype: "Int", label: "Seat", default: line.seat_no || 0 },
			{ fieldname: "course", fieldtype: "Data", label: "Course", default: line.course || "" },
			{ fieldname: "is_course_held", fieldtype: "Check", label: "Hold course", default: line.is_course_held || 0 },
			{ fieldname: "item_note", fieldtype: "Small Text", label: "Kitchen note", default: line.item_note || "" },
		]);
		if (!values) return;
		this.setLoading(true);
		try {
			this.state.activeOrder = await this.call("ledgix_saas.api.restaurant_orders.edit_item", { order_item: itemName, ...values, request_id: this.uuid("edit") });
			this.renderCheck();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async voidLine(itemName) {
		const line = this.state.activeOrder?.items?.find(row => row.name === itemName);
		if (!line || line.is_voided) return;
		const values = await this.promptValues("Void item", [{ fieldname: "reason", fieldtype: "Small Text", label: "Reason", reqd: 1 }]);
		if (!values) return;
		this.setLoading(true);
		try {
			const fired = Number(line.fired_quantity || 0) > 0;
			const method = fired ? "ledgix_saas.api.kitchen.void_item" : "ledgix_saas.api.restaurant_orders.void_item";
			const args = fired
				? { order_item: itemName, reason: values.reason, client_fire_id: this.uuid("void") }
				: { order_item: itemName, reason: values.reason, request_id: this.uuid("void") };
			const result = await this.call(method, args);
			this.state.activeOrder = result.order || result;
			this.renderCheck();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async fireOrder() {
		if (!this.state.activeOrder) return;
		this.setLoading(true);
		try {
			const result = await this.call("ledgix_saas.api.kitchen.fire", { restaurant_order: this.state.activeOrder.name, client_fire_id: this.uuid("fire") });
			this.state.activeOrder = result.order;
			this.renderCheck();
			frappe.show_alert({ message: `Sent ${result.kot?.items?.length || 0} item(s) to kitchen.`, indicator: "green" });
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	renderHeldCourses() {
		const courses = [...new Set((this.state.activeOrder?.items || []).filter(row => row.is_course_held && !row.is_voided && Number(row.billable_quantity || 0) > Number(row.fired_quantity || 0)).map(row => row.course).filter(Boolean))];
		this.$root.find(".lx-held-courses").html(courses.length ? `<span>Held courses</span>${courses.map(course => `<button class="lx-fire-course" data-course="${this.escape(course)}">Fire ${this.escape(course)}</button>`).join("")}` : "");
	}

	async fireCourse(course) {
		this.setLoading(true);
		try {
			const result = await this.call("ledgix_saas.api.kitchen_courses.fire", { restaurant_order: this.state.activeOrder.name, course, client_fire_id: this.uuid("course") });
			this.state.activeOrder = result.order;
			this.renderCheck();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async manageCheck() {
		const order = this.state.activeOrder;
		if (!order?.table_session) return;
		const table = this.currentTable();
		const siblings = (table?.checks || []).filter(row => row.name !== order.name);
		const mergeOptions = ["", ...siblings.map(row => row.name)];
		const values = await this.promptValues("Manage table check", [
			{ fieldname: "covers", fieldtype: "Int", label: "Covers", default: order.covers || 1, reqd: 1 },
			{ fieldname: "server", fieldtype: "Link", options: "User", label: "Server / Waiter", default: order.server || "" },
			{ fieldname: "merge_into", fieldtype: "Select", label: "Merge this check into", options: mergeOptions, description: siblings.length ? "Optional. All lines move to the selected sibling check." : "No sibling check is open on this table." },
			{ fieldname: "reason", fieldtype: "Small Text", label: "Reason", reqd: 1 },
		]);
		if (!values) return;
		this.setLoading(true);
		try {
			if (Number(values.covers) !== Number(order.covers || 0)) {
				await this.call("ledgix_saas.api.restaurant_orders.set_covers", { table_session: order.table_session, covers: values.covers, reason: values.reason, request_id: this.uuid("covers") });
			}
			if ((values.server || "") !== (order.server || "")) {
				await this.call("ledgix_saas.api.restaurant_orders.set_server", { table_session: order.table_session, server: values.server, reason: values.reason, request_id: this.uuid("server") });
			}
			if (values.merge_into) {
				this.state.activeOrder = await this.call("ledgix_saas.api.restaurant_order_splits.merge", { source_order: order.name, destination_order: values.merge_into, reason: values.reason, request_id: this.uuid("merge") });
			}
			await this.refreshAll({ keepOrder: true });
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async splitCheck() {
		const lines = (this.state.activeOrder?.items || []).filter(row => !row.is_voided && Number(row.billable_quantity || 0) > 0);
		if (lines.length < 2) return frappe.show_alert({ message: "At least two active lines are needed to split a check.", indicator: "orange" });
		const dialog = new frappe.ui.Dialog({ title: "Split check", fields: [{ fieldtype: "HTML", fieldname: "lines" }, { fieldtype: "Small Text", fieldname: "reason", label: "Reason", reqd: 1 }], primary_action_label: "Create split check", primary_action: async values => {
			const selected = [];
			dialog.fields_dict.lines.$wrapper.find("input:checked").each((_, input) => selected.push({ order_item: input.value }));
			if (!selected.length || selected.length === lines.length) return frappe.msgprint("Select some, but not all, lines for the new check.");
			dialog.hide();
			this.setLoading(true);
			try {
				const result = await this.call("ledgix_saas.api.restaurant_order_splits.split_by_items", { restaurant_order: this.state.activeOrder.name, selections: selected, client_order_id: this.uuid("split"), reason: values.reason });
				this.state.activeOrder = result.source;
				this.renderCheck();
				await this.refreshAll();
				frappe.show_alert({ message: `Created ${result.split.name}`, indicator: "green" });
			} catch (error) { this.handleError(error); }
			finally { this.setLoading(false); }
		} });
		dialog.fields_dict.lines.$wrapper.html(`<div class="lx-split-lines">${lines.map(line => `<label><input type="checkbox" value="${this.escape(line.name)}"><span>${this.escape(line.display_name || line.item)}</span><b>${this.money(line.net_amount || line.amount)}</b></label>`).join("")}</div>`);
		dialog.show();
	}

	async transferTable() {
		if (!this.state.activeOrder?.table_session) return;
		const available = [];
		for (const floor of this.state.boot?.table_map?.floors || []) {
			for (const table of floor.tables || []) if (!table.table_session) available.push({ ...table, floor_name: floor.floor_name });
		}
		if (!available.length) return frappe.msgprint("No available table is configured in this branch.");
		const values = await this.promptValues("Move table", [
			{ fieldname: "destination_table", fieldtype: "Select", label: "Destination", options: available.map(row => ({ label: `${row.floor_name} · ${row.table_name}`, value: row.name })), reqd: 1 },
			{ fieldname: "reason", fieldtype: "Small Text", label: "Reason", reqd: 1 },
		]);
		if (!values) return;
		this.setLoading(true);
		try {
			await this.call("ledgix_saas.api.restaurant_orders.move_table", { table_session: this.state.activeOrder.table_session, destination_table: values.destination_table, reason: values.reason, request_id: this.uuid("move") });
			await this.refreshAll();
		} catch (error) { this.handleError(error); }
		finally { this.setLoading(false); }
	}

	async openSettlement() {
		const order = this.state.activeOrder;
		if (!order) return;
		let preview;
		try {
			preview = await this.call("ledgix_saas.api.restaurant_settlement.preview", { restaurant_order: order.name });
		} catch (error) { return this.handleError(error); }

		const methods = preview.payment_methods || [];
		const tenders = [];
		let previewTimer = null;
		let previewBusy = false;
		const dialog = new frappe.ui.Dialog({
			title: `Settle ${order.table_name || order.pickup_name || order.name}`,
			size: "large",
			fields: [
				{ fieldtype: "Section Break", label: "Adjustments" },
				{ fieldname: "discount_amount", fieldtype: "Currency", label: "Discount", default: preview.discount_amount || 0, read_only: preview.can_adjust_discount_or_service ? 0 : 1 },
				{ fieldname: "service_charge", fieldtype: "Currency", label: "Service Charge", default: preview.service_charge || 0, read_only: preview.can_adjust_discount_or_service ? 0 : 1 },
				{ fieldname: "tip_amount", fieldtype: "Currency", label: "Tip / Gratuity", default: preview.tip_amount || 0 },
				{ fieldtype: "Column Break" },
				{ fieldname: "adjustment_reason", fieldtype: "Small Text", label: "Adjustment Reason", description: "Required when Discount or Service Charge changes." },
				{ fieldtype: "Section Break", label: "Payment" },
				{ fieldname: "payment_method", fieldtype: "Select", label: "Payment Method", options: methods.map(row => ({ label: row.payment_method_name || row.name, value: row.name })), reqd: 0 },
				{ fieldname: "tender_amount", fieldtype: "Currency", label: "Amount" },
				{ fieldtype: "Column Break" },
				{ fieldname: "reference_no", fieldtype: "Data", label: "Reference" },
				{ fieldname: "tender_actions", fieldtype: "HTML" },
				{ fieldtype: "Section Break" },
				{ fieldname: "tender_list", fieldtype: "HTML" },
				{ fieldname: "settlement_summary", fieldtype: "HTML" },
			],
			primary_action_label: "Finalize Sale",
			primary_action: async () => {
				if (previewBusy) return;
				preview = await refreshPreview(true);
				if (!preview) return;
				if (!preview.active_shift) return frappe.msgprint("Open a POS Shift before restaurant settlement.");
				const total = Number(preview.grand_total || 0);
				const tendered = tenders.reduce((sum, row) => sum + Number(row.amount || 0), 0);
				if (tendered + 0.005 < total) return frappe.msgprint(`Payment is short by ${this.money(total - tendered)}.`);
				if (tendered > total + 0.005 && !tenders.some(row => row.allow_change)) return frappe.msgprint("Over-tender requires a payment method that allows change.");
				const discountChanged = Math.abs(Number(dialog.get_value("discount_amount") || 0) - Number(order.discount_amount || 0)) > 0.005;
				const serviceChanged = Math.abs(Number(dialog.get_value("service_charge") || 0) - Number(order.service_charge || 0)) > 0.005;
				if ((discountChanged || serviceChanged) && !String(dialog.get_value("adjustment_reason") || "").trim()) return frappe.msgprint("Enter a reason for Discount / Service Charge changes.");
				dialog.get_primary_btn().prop("disabled", true).text("Finalizing…");
				try {
					const clientSaleId = this.settlementId(order.name);
					const result = await this.call("ledgix_saas.api.restaurant_settlement.settle", {
						restaurant_order: order.name,
						tenders: tenders.map(({ allow_change, label, ...row }) => row),
						client_sale_id: clientSaleId,
						discount_amount: dialog.get_value("discount_amount") || 0,
						service_charge: dialog.get_value("service_charge") || 0,
						tip_amount: dialog.get_value("tip_amount") || 0,
						adjustment_reason: dialog.get_value("adjustment_reason") || "",
						request_id: `settlement:${clientSaleId}`,
					});
					dialog.hide();
					delete this.state.settlementIds[order.name];
					this.state.activeOrder = null;
					this.state.activeSession = null;
					await this.refreshAll({ keepOrder: false });
					this.showSettlementSuccess(result.sale);
				} catch (error) {
					this.handleError(error);
					dialog.get_primary_btn().prop("disabled", false).text("Finalize Sale");
				}
			},
		});

		const adjustmentInputs = ["discount_amount", "service_charge", "tip_amount"];
		const adjustmentValues = () => ({
			discount_amount: dialog.get_value("discount_amount") || 0,
			service_charge: dialog.get_value("service_charge") || 0,
			tip_amount: dialog.get_value("tip_amount") || 0,
		});
		const renderPayment = () => {
			const total = Number(preview?.grand_total || 0);
			const tendered = tenders.reduce((sum, row) => sum + Number(row.amount || 0), 0);
			const remaining = Math.max(total - tendered, 0);
			const change = Math.max(tendered - total, 0);
			dialog.fields_dict.tender_list.$wrapper.html(tenders.length ? `<div class="lx-tender-list">${tenders.map((row, index) => `<div class="lx-tender-row"><span><strong>${this.escape(row.label)}</strong>${row.reference_no ? `<small>${this.escape(row.reference_no)}</small>` : ""}</span><b>${this.money(row.amount)}</b><button type="button" data-index="${index}">×</button></div>`).join("")}</div>` : `<div class="lx-empty-tenders">No payment added yet.</div>`);
			dialog.fields_dict.settlement_summary.$wrapper.html(`
				<div class="lx-settle-summary">
					<div><span>Subtotal</span><b>${this.money(preview?.subtotal_before_discount || 0)}</b></div>
					${Number(preview?.discount_amount || 0) ? `<div><span>Discount</span><b>− ${this.money(preview.discount_amount)}</b></div>` : ""}
					${Number(preview?.service_charge || 0) ? `<div><span>Service Charge</span><b>${this.money(preview.service_charge)}</b></div>` : ""}
					${Number(preview?.tip_amount || 0) ? `<div><span>Tip / Gratuity</span><b>${this.money(preview.tip_amount)}</b></div>` : ""}
					<div><span>Tax</span><b>${this.money(preview?.tax_amount || 0)}</b></div>
					<div class="grand"><span>Payable</span><b>${this.money(total)}</b></div>
					<div><span>Tendered</span><b>${this.money(tendered)}</b></div>
					<div class="${remaining > 0.005 ? "remaining" : "change"}"><span>${remaining > 0.005 ? "Remaining" : "Change"}</span><b>${this.money(remaining > 0.005 ? remaining : change)}</b></div>
				</div>`);
			if (!tenders.length || !Number(dialog.get_value("tender_amount") || 0)) dialog.set_value("tender_amount", remaining || total);
		};
		const refreshPreview = async immediate => {
			clearTimeout(previewTimer);
			const run = async () => {
				previewBusy = true;
				try {
					preview = await this.call("ledgix_saas.api.restaurant_settlement.preview", { restaurant_order: order.name, ...adjustmentValues() });
					renderPayment();
					return preview;
				} catch (error) {
					this.handleError(error);
					return null;
				} finally { previewBusy = false; }
			};
			if (immediate) return run();
			previewTimer = setTimeout(run, 260);
			return preview;
		};

		dialog.show();
		dialog.fields_dict.tender_actions.$wrapper.html(`<button type="button" class="btn btn-default btn-sm lx-add-tender">Add payment</button><button type="button" class="btn btn-default btn-sm lx-pay-remaining">Use remaining</button>`);
		adjustmentInputs.forEach(fieldname => dialog.fields_dict[fieldname].$input?.on("input change", () => refreshPreview(false)));
		dialog.$wrapper.on("click", ".lx-pay-remaining", () => {
			const total = Number(preview?.grand_total || 0);
			const tendered = tenders.reduce((sum, row) => sum + Number(row.amount || 0), 0);
			dialog.set_value("tender_amount", Math.max(total - tendered, 0));
		});
		dialog.$wrapper.on("click", ".lx-add-tender", () => {
			const paymentMethod = dialog.get_value("payment_method");
			const amount = Number(dialog.get_value("tender_amount") || 0);
			if (!paymentMethod) return frappe.msgprint("Select a Payment Method.");
			if (amount <= 0) return frappe.msgprint("Payment amount must be greater than zero.");
			const meta = methods.find(row => row.name === paymentMethod);
			const reference = String(dialog.get_value("reference_no") || "").trim();
			if (meta?.requires_reference && !reference) return frappe.msgprint(`${meta.payment_method_name || meta.name} requires a reference.`);
			const total = Number(preview?.grand_total || 0);
			const tendered = tenders.reduce((sum, row) => sum + Number(row.amount || 0), 0);
			const remaining = Math.max(total - tendered, 0);
			if (amount > remaining + 0.005 && !meta?.allow_change) return frappe.msgprint(`${meta?.payment_method_name || paymentMethod} cannot exceed the remaining amount.`);
			tenders.push({ payment_method: paymentMethod, amount, reference_no: reference, allow_change: !!meta?.allow_change, label: meta?.payment_method_name || paymentMethod });
			dialog.set_value("reference_no", "");
			dialog.set_value("tender_amount", 0);
			renderPayment();
		});
		dialog.$wrapper.on("click", ".lx-tender-row button", e => { tenders.splice(Number($(e.currentTarget).data("index")), 1); renderPayment(); });
		renderPayment();
	}

	showSettlementSuccess(sale) {
		const dialog = new frappe.ui.Dialog({ title: "Sale finalized", fields: [{ fieldtype: "HTML", fieldname: "result" }] });
		dialog.fields_dict.result.$wrapper.html(`
			<div class="lx-sale-success"><div class="lx-success-mark">✓</div><strong>${this.escape(sale.invoice_number || sale.name)}</strong><span>${this.money(sale.grand_total)} · ${this.escape(sale.payment_status || "Paid")}</span>${Number(sale.change_amount || 0) ? `<b>Change ${this.money(sale.change_amount)}</b>` : ""}<div><button type="button" class="btn btn-default lx-view-sale">Open Sale</button><button type="button" class="btn btn-primary lx-close-success">Done</button></div></div>`);
		dialog.$wrapper.on("click", ".lx-view-sale", () => { dialog.hide(); frappe.set_route("Form", "Ledgix Sale", sale.name); });
		dialog.$wrapper.on("click", ".lx-close-success", () => dialog.hide());
		dialog.show();
	}

	promptValues(title, fields) {
		return new Promise(resolve => {
			let settled = false;
			const dialog = new frappe.ui.Dialog({ title, fields, primary_action_label: "Continue", primary_action: values => { settled = true; dialog.hide(); resolve(values); } });
			dialog.onhide = () => { if (!settled) resolve(null); };
			dialog.show();
		});
	}

	handleError(error) {
		console.error(error);
		let message = error?.message || "Restaurant POS operation failed.";
		if (error?._server_messages) {
			try {
				const rows = JSON.parse(error._server_messages);
				const parsed = rows.map(row => { try { return JSON.parse(row).message; } catch (_) { return row; } }).filter(Boolean);
				if (parsed.length) message = parsed.join("<br>");
			} catch (_) { message = error._server_messages; }
		}
		frappe.msgprint({ title: "Ledgix Restaurant", message, indicator: "red" });
	}
}
