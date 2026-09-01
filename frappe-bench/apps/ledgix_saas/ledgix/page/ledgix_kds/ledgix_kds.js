frappe.pages["ledgix-kds"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "Kitchen Display", single_column: true });
	new LedgixKDS(page, wrapper);
};

class LedgixKDS {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.state = {
			branch: "",
			branches: [],
			stations: [],
			station: "",
			view: "Station",
			include_ready: true,
			queue: [],
			expo: [],
			server_time: null,
			loaded_at: Date.now(),
			loading: false,
		};
		this.refresh_timer = null;
		this.clock_timer = null;
		this.render_shell();
		this.bind_events();
		this.bind_realtime();
		this.boot();
	}

	async call(method, args = {}) {
		const response = await frappe.call({ method, args, freeze: false });
		return response.message || {};
	}

	escape(value) {
		return frappe.utils.escape_html(String(value == null ? "" : value));
	}

	render_shell() {
		$(this.page.body).html(`
			<div class="lx-kds">
				<div class="lx-kds-toolbar">
					<div class="lx-kds-context">
						<label class="lx-kds-branch-wrap"><span>Branch</span><select class="lx-kds-branch"></select></label>
						<div class="lx-kds-mode" role="group" aria-label="KDS view">
							<button type="button" data-view="Station" class="active">Stations</button>
							<button type="button" data-view="Expo">Expo</button>
						</div>
					</div>
					<div class="lx-kds-toolbar-actions">
						<label class="lx-kds-ready-toggle"><input type="checkbox" checked> Show ready</label>
						<span class="lx-kds-live"><i></i> Live</span>
						<button type="button" class="btn btn-default btn-sm lx-kds-refresh">Refresh</button>
					</div>
				</div>
				<div class="lx-kds-stations"></div>
				<div class="lx-kds-summary"></div>
				<div class="lx-kds-board"></div>
			</div>
		`);
		this.$root = $(this.page.body).find(".lx-kds");
	}

	bind_events() {
		this.$root.on("change", ".lx-kds-branch", e => {
			this.state.branch = $(e.currentTarget).val();
			this.state.station = "";
			this.load();
		});
		this.$root.on("click", ".lx-kds-mode button", e => {
			const view = $(e.currentTarget).data("view");
			if (view === this.state.view) return;
			this.state.view = view;
			this.load();
		});
		this.$root.on("click", ".lx-kds-station", e => {
			const station = $(e.currentTarget).data("station");
			if (!station || station === this.state.station) return;
			this.state.station = station;
			this.state.view = "Station";
			this.load();
		});
		this.$root.on("change", ".lx-kds-ready-toggle input", e => {
			this.state.include_ready = !!$(e.currentTarget).prop("checked");
			this.load();
		});
		this.$root.on("click", ".lx-kds-refresh", () => this.load());
		this.$root.on("click", ".lx-kds-transition", e => {
			const $button = $(e.currentTarget);
			this.transition_item($button.data("item"), $button.data("status"), $button);
		});
	}

	bind_realtime() {
		if (window.__ledgix_kds_realtime_handler && frappe.realtime.off) {
			frappe.realtime.off("ledgix_kds_update", window.__ledgix_kds_realtime_handler);
		}
		this.realtime_handler = payload => {
			if (!payload || !this.state.branch || payload.branch !== this.state.branch) return;
			if (this.state.view === "Station" && payload.station && payload.station !== this.state.station) return;
			clearTimeout(this.refresh_timer);
			this.refresh_timer = setTimeout(() => this.load({ quiet: true }), 220);
		};
		window.__ledgix_kds_realtime_handler = this.realtime_handler;
		frappe.realtime.on("ledgix_kds_update", this.realtime_handler);

		clearInterval(this.clock_timer);
		this.clock_timer = setInterval(() => this.refresh_elapsed_labels(), 15000);
	}

	async boot() {
		await this.load();
	}

	async load(options = {}) {
		if (this.state.loading) return;
		this.state.loading = true;
		if (!options.quiet) this.$root.addClass("is-loading");
		try {
			const payload = await this.call("ledgix_saas.api.kds.get_kds_boot", {
				branch: this.state.branch || null,
				station: this.state.station || null,
				view: this.state.view,
				include_ready: this.state.include_ready ? 1 : 0,
			});
			Object.assign(this.state, payload, { loaded_at: Date.now() });
			this.render();
		} catch (error) {
			this.handle_error(error);
		} finally {
			this.state.loading = false;
			this.$root.removeClass("is-loading");
		}
	}

	render() {
		this.render_branch_options();
		this.render_modes();
		this.render_stations();
		if (this.state.view === "Expo") this.render_expo();
		else this.render_station_queue();
		this.refresh_elapsed_labels();
	}

	render_branch_options() {
		const rows = this.state.branches || [];
		const html = rows.map(row => `<option value="${this.escape(row.name)}" ${row.name === this.state.branch ? "selected" : ""}>${this.escape(row.branch_name || row.branch_code || row.name)}</option>`).join("");
		this.$root.find(".lx-kds-branch").html(html);
		this.$root.find(".lx-kds-branch-wrap").toggleClass("hidden", rows.length <= 1);
	}

	render_modes() {
		this.$root.find(".lx-kds-mode button").removeClass("active");
		this.$root.find(`.lx-kds-mode button[data-view="${this.state.view}"]`).addClass("active");
		this.$root.find(".lx-kds-ready-toggle input").prop("checked", !!this.state.include_ready);
	}

	render_stations() {
		const rows = (this.state.stations || []).filter(row => row.station_type !== "Expo");
		this.$root.find(".lx-kds-stations").toggleClass("hidden", this.state.view === "Expo").html(
			rows.map(row => `
				<button type="button" class="lx-kds-station ${row.name === this.state.station ? "active" : ""}" data-station="${this.escape(row.name)}">
					<span>${this.escape(row.station_name || row.station_code || row.name)}</span>
					<small>${this.escape(row.station_type || "Kitchen")}</small>
				</button>
			`).join("")
		);
	}

	group_tickets(rows) {
		const tickets = new Map();
		(rows || []).forEach(row => {
			if (!tickets.has(row.kot)) {
				tickets.set(row.kot, {
					kot: row.kot,
					order: row.restaurant_order,
					order_type: row.order_type,
					table_name: row.table_name,
					server: row.server,
					fired_at: row.fired_at,
					queued_at: row.queued_at,
					items: [],
				});
			}
			const ticket = tickets.get(row.kot);
			ticket.items.push(row);
			if (row.queued_at && (!ticket.queued_at || row.queued_at < ticket.queued_at)) ticket.queued_at = row.queued_at;
		});
		return Array.from(tickets.values());
	}

	render_station_queue() {
		const tickets = this.group_tickets(this.state.queue || []);
		const counts = this.count_statuses(this.state.queue || []);
		this.render_summary(counts, tickets.length, "tickets");
		const $board = this.$root.find(".lx-kds-board").removeClass("expo");
		if (!tickets.length) {
			$board.html(this.empty_state("Station clear", "New kitchen tickets will appear here automatically."));
			return;
		}
		$board.html(tickets.map(ticket => this.station_ticket(ticket)).join(""));
	}

	station_ticket(ticket) {
		const target = this.current_station()?.target_prep_minutes || 15;
		return `
			<article class="lx-kds-ticket" data-queued-at="${this.escape(ticket.queued_at || ticket.fired_at || "")}" data-target-minutes="${Number(target || 15)}">
				<header>
					<div><strong>${this.escape(ticket.table_name || ticket.order_type || "Order")}</strong><span>${this.escape(ticket.order)} · ${this.escape(ticket.kot)}</span></div>
					<div class="lx-kds-age" data-time="${this.escape(ticket.queued_at || ticket.fired_at || "")}" data-target-minutes="${Number(target || 15)}">0m</div>
				</header>
				<div class="lx-kds-ticket-meta"><span>${this.escape(ticket.order_type || "Order")}</span>${ticket.server ? `<span>${this.escape(ticket.server)}</span>` : ""}</div>
				<div class="lx-kds-lines">${ticket.items.map(item => this.item_line(item)).join("")}</div>
			</article>
		`;
	}

	item_line(item, expo = false) {
		const next = this.next_action(item.status);
		const station = this.station_by_name(item.kitchen_station);
		const showSeat = expo || !station || Number(station.show_seat || 0);
		const showCourse = expo || !station || Number(station.show_course || 0);
		const details = [];
		if (showSeat && Number(item.seat_no || 0)) details.push(`Seat ${Number(item.seat_no)}`);
		if (showCourse && item.course) details.push(item.course);
		if (expo && station) details.push(station.station_name || station.station_code);
		return `
			<div class="lx-kds-line status-${this.slug(item.status)}">
				<div class="lx-kds-line-copy">
					<div class="lx-kds-line-title"><b>${Number(item.quantity || 0).toLocaleString()}×</b><strong>${this.escape(item.item_name || item.item)}</strong><span class="lx-kds-status">${this.escape(item.status)}</span></div>
					${details.length ? `<div class="lx-kds-line-context">${details.map(value => `<span>${this.escape(value)}</span>`).join("")}</div>` : ""}
					${item.modifier_summary ? `<div class="lx-kds-modifiers">${this.escape(item.modifier_summary)}</div>` : ""}
					${item.kitchen_note ? `<div class="lx-kds-note">${this.escape(item.kitchen_note)}</div>` : ""}
				</div>
				${next ? `<button type="button" class="lx-kds-transition action-${this.slug(next.status)}" data-item="${this.escape(item.name)}" data-status="${this.escape(next.status)}">${this.escape(next.label)}</button>` : ""}
			</div>
		`;
	}

	render_expo() {
		const orders = this.state.expo || [];
		const items = orders.flatMap(order => order.items || []);
		const counts = this.count_statuses(items);
		this.render_summary(counts, orders.length, "orders");
		const $board = this.$root.find(".lx-kds-board").addClass("expo");
		if (!orders.length) {
			$board.html(this.empty_state("Expo clear", "Active kitchen orders will appear here across all stations."));
			return;
		}
		$board.html(orders.map(order => {
			const ready = Number(order.ready_count || 0);
			const total = Number(order.active_count || (order.items || []).length);
			return `
				<article class="lx-kds-ticket lx-kds-expo-card" data-queued-at="${this.escape(order.oldest_queued_at || "")}">
					<header>
						<div><strong>${this.escape(order.table_name || order.order_type || "Order")}</strong><span>${this.escape(order.restaurant_order)}</span></div>
						<div class="lx-kds-age" data-time="${this.escape(order.oldest_queued_at || "")}">0m</div>
					</header>
					<div class="lx-kds-expo-progress"><span>${ready}/${total} ready</span><div><i style="width:${total ? Math.round(ready / total * 100) : 0}%"></i></div></div>
					<div class="lx-kds-lines">${(order.items || []).map(item => this.item_line(item, true)).join("")}</div>
				</article>
			`;
		}).join(""));
	}

	render_summary(counts, total, noun) {
		this.$root.find(".lx-kds-summary").html(`
			<div><strong>${total}</strong><span>${noun}</span></div>
			<div class="new"><strong>${counts.New || 0}</strong><span>New</span></div>
			<div class="preparing"><strong>${counts.Preparing || 0}</strong><span>Preparing</span></div>
			<div class="ready"><strong>${counts.Ready || 0}</strong><span>Ready</span></div>
		`);
	}

	count_statuses(rows) {
		return (rows || []).reduce((acc, row) => {
			acc[row.status] = (acc[row.status] || 0) + 1;
			return acc;
		}, {});
	}

	current_station() {
		return this.station_by_name(this.state.station);
	}

	station_by_name(name) {
		return (this.state.stations || []).find(row => row.name === name) || null;
	}

	next_action(status) {
		if (status === "New") return { status: "Preparing", label: "Start" };
		if (status === "Preparing") return { status: "Ready", label: "Ready" };
		if (status === "Ready") return { status: "Bumped", label: "Bump" };
		return null;
	}

	async transition_item(item, status, $button) {
		if (!item || !status || $button.prop("disabled")) return;
		$button.prop("disabled", true).addClass("is-busy");
		try {
			await this.call("ledgix_saas.api.kds.transition_item", { kot_item: item, status });
			await this.load({ quiet: true });
		} catch (error) {
			this.handle_error(error);
		} finally {
			$button.prop("disabled", false).removeClass("is-busy");
		}
	}

	parse_time(value) {
		if (!value) return null;
		try {
			if (frappe.datetime && frappe.datetime.str_to_obj) return frappe.datetime.str_to_obj(value);
			return new Date(String(value).replace(" ", "T"));
		} catch (_error) {
			return null;
		}
	}

	elapsed_seconds(value) {
		const queued = this.parse_time(value);
		if (!queued) return 0;
		const server = this.parse_time(this.state.server_time) || new Date();
		const base = Math.max((server.getTime() - queued.getTime()) / 1000, 0);
		return Math.max(Math.round(base + (Date.now() - this.state.loaded_at) / 1000), 0);
	}

	refresh_elapsed_labels() {
		this.$root.find(".lx-kds-age").each((_index, element) => {
			const $element = $(element);
			const seconds = this.elapsed_seconds($element.data("time"));
			const minutes = Math.floor(seconds / 60);
			const target = Number($element.data("target-minutes") || 0);
			$element.text(minutes < 1 ? "<1m" : `${minutes}m`);
			$element.toggleClass("overdue", !!target && minutes >= target);
		});
	}

	empty_state(title, detail) {
		return `<div class="lx-kds-empty"><div>✓</div><strong>${this.escape(title)}</strong><span>${this.escape(detail)}</span></div>`;
	}

	slug(value) {
		return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
	}

	handle_error(error) {
		const message = error?.message || error?.exc || "Kitchen Display request failed.";
		frappe.msgprint({ title: "Kitchen Display", message, indicator: "red" });
	}
}
