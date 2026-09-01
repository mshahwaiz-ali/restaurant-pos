app_name = "ledgix_saas"
app_title = "Ledgix Restaurant"
app_publisher = "Ali"
app_description = "Restaurant management, POS, inventory and fiscal compliance platform"
app_email = "alishahwaiz96@gmail.com"
app_license = "mit"

# Keep the global Desk layer deliberately small. Workflow-specific styling belongs
# to its Page so native Frappe Lists, Forms, Workspaces and dialogs retain normal behavior.
app_include_css = [
	"/assets/ledgix_saas/css/ledgix_brand.css",
	"/assets/ledgix_saas/css/ledgix_v2_tokens.css",
]

app_include_js = [
	"/assets/ledgix_saas/js/ledgix_brand.js",
]

web_include_css = [
	"/assets/ledgix_saas/css/ledgix_brand.css",
]
web_include_js = [
	"/assets/ledgix_saas/js/ledgix_brand.js",
]

# Homepage routing is only a UX default. Authorization remains enforced by
# Page, DocType, Report and server-side permissions.
role_home_page = {
	"Ledgix Cashier": "ledgix-pos",
	"Ledgix Manager": "Ledgix",
	"Ledgix Admin": "Ledgix",
}

jinja = {
	"methods": [
		"ledgix_saas.api.brand.get_splash_logo_url",
		"ledgix_saas.api.brand.get_print_logo_url",
		"ledgix_saas.api.printing.get_fbr_qr_data_uri",
	],
}

after_migrate = [
	"ledgix_saas.setup.fast_permissions.after_migrate",
]

extend_bootinfo = [
	"ledgix_saas.api.brand.extend_bootinfo",
]

update_website_context = [
	"ledgix_saas.api.brand.update_website_context",
]

# Fiscal attributes captured on an open restaurant line are part of the
# transaction snapshot. Financial adjustments on an open check are service-owned.
doc_events = {
	"Ledgix Restaurant Order Item": {
		"before_insert": "ledgix_saas.services.restaurant_tax_snapshots.before_insert_order_item",
		"validate": "ledgix_saas.services.restaurant_tax_snapshots.validate_order_item_tax_snapshot",
	},
	"Ledgix Restaurant Order": {
		"validate": "ledgix_saas.services.restaurant_settlement.validate_order_adjustment_mutation",
	},
}

# Ledgix Sale remains the single finalized fiscal/payment document. The override
# changes only restaurant-source policy: locked tax snapshots and no second stock
# posting after KOT consumption. Ordinary Retail/B2B Sale behavior delegates to
# the original controller unchanged.
override_doctype_class = {
	"Ledgix Sale": "ledgix_saas.overrides.restaurant_sale.RestaurantAwareLedgixSale",
}

# Keep legacy HTTP contracts stable while routing them through the current
# environment-aware / branch-aware authoritative services.
override_whitelisted_methods = {
	"ledgix_saas.api.tax_center.get_fbr_readiness": "ledgix_saas.api.fbr_preflight.get_fbr_readiness",
	"ledgix_saas.api.business_intelligence.get_business_intelligence_data": "ledgix_saas.api.inventory_intelligence.get_inventory_intelligence_data",
}

# Production FBR recovery is intentionally fail-closed. An ambiguous POST/HTTP
# failure can mean FBR received the invoice even when Ledgix did not receive the
# response, so automatic retransmission is disabled until reconciliation-safe
# status checking is implemented and proven against the client Sandbox/PRAL flow.
scheduler_events = {}

# Export customizations, business roles, Workspace, and property metadata.
fixtures = [
	{
		"doctype": "Role",
		"filters": [
			[
				"name",
				"in",
				[
					"Ledgix Admin",
					"Ledgix Manager",
					"Ledgix Cashier",
				],
			]
		],
	},
	{
		"doctype": "Workspace",
		"filters": [["name", "=", "Ledgix"]],
	},
	{
		"doctype": "Custom Field",
		"filters": [["module", "=", "Ledgix"]],
	},
	{
		"doctype": "Property Setter",
		"filters": [["module", "=", "Ledgix"]],
	},
]
