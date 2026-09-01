# Ledgix Restaurant — Product Architecture & Implementation Blueprint

**Status:** Architecture baseline for implementation  
**Version:** 2.0  
**Product:** Restaurant Management System + Point of Sale  
**Technical foundation:** Frappe Framework v15 + existing `ledgix_saas` application  
**Deployment target:** Single restaurant → multi-branch → multi-brand / multi-chain  

---

## 1. Product Vision

Ledgix Restaurant will be a serious restaurant operating platform whose front-of-house experience feels simple even when the engine behind it is powerful.

The product must not feel like an ERP screen with restaurant labels added on top. Each role should see the workflow that matters to that role:

- Cashier: fast order and payment surface.
- Waiter/server: tables, open checks, ordering and course control.
- Kitchen: KDS/KOT only.
- Expo: order coordination and final hand-off.
- Store/purchase staff: stock, receiving, transfers, waste and reorder work.
- Branch manager: live branch operations, exceptions and approvals.
- Owner/admin: cross-branch control and analytics.
- Accountant/back office: financial reports and optional future accounting integration.

The design target is a clean, calm, touch-first product: strong hierarchy, minimum visual noise, generous spacing, predictable actions, fast keyboard/touch interaction and very little unnecessary navigation.

This is not a plan to recreate Toast, Square, Lightspeed or Simphony feature-for-feature. Those products define the market bar. Ledgix should adopt the operational patterns that matter and avoid enterprise complexity that does not improve day-to-day restaurant work.

---

# 2. Architecture Decision — Locked

## 2.1 Current Ledgix is the transaction engine

The current application already owns a substantial commerce domain:

- `Ledgix Item`
- `Ledgix Category`
- `Ledgix Customer`
- `Ledgix Supplier`
- `Ledgix Price List`
- `Ledgix Item Price`
- `Ledgix Sale`
- `Ledgix Sale Item`
- `Ledgix Sale Payment`
- `Ledgix Payment`
- `Ledgix Payment Allocation`
- `Ledgix Payment Method`
- `Ledgix Sales Return`
- `Ledgix Purchase`
- `Ledgix Stock Movement`
- `Ledgix Stock Lot`
- `Ledgix Stock Serial`
- `Ledgix POS Shift`
- tax profiles/rates/categories
- FBR settings, validation, submission and audit logs
- sales, stock, payment, receivable, pricing and tax services

The app also already has working transactional rules for pricing, payment, stock decrement/increment, COGS, gross profit, returns, shifts and FBR submission.

**Therefore the restaurant product will extend this engine instead of duplicating it with ERPNext Sales Invoice, Payment Entry, Supplier, Purchase Receipt or Stock Ledger as a second source of truth.**

## 2.2 Frappe is the platform layer

Use Frappe aggressively where it is already strong:

- Users, roles and permissions
- User Permissions / branch scoping
- standard forms and lists
- workflow and approval primitives
- document versioning and audit history
- print formats
- reports and dashboards
- background jobs
- realtime events / Socket.IO
- notifications
- files and attachments
- import/export
- standard Desk navigation and workspace

Do not build custom UI merely because custom UI is possible.

## 2.3 ERPNext is not a hard dependency for Restaurant V1

The current `ledgix_saas` package depends on Frappe, not ERPNext. Installing ERPNext now and using its parallel sales, purchase, payment and stock documents would create duplicated business truth.

ERPNext may be added later through a deliberate integration boundary when full general-ledger accounting is required.

If that happens:

1. Ledgix operational transactions remain authoritative for restaurant operations.
2. Finalized immutable Ledgix transactions produce accounting sync events.
3. ERPNext accounting documents are generated through mappings/adapters.
4. ERPNext stock must not independently post the same stock movements unless the architecture is intentionally migrated.
5. Sync must be idempotent and reconciliable.

No half-Ledgix / half-ERPNext transaction model is permitted.

## 2.4 Keep technical package names stable

Do **not** rename `ledgix_saas`, the Python module `ledgix`, existing DocTypes or API dotted paths during the restaurant conversion.

Product-facing branding can become **Ledgix Restaurant** immediately. Technical renaming is a separate migration project and has no customer value during V1.

---

# 3. Current Codebase Assessment

## 3.1 What is already strong and should be kept

### Commerce / financial transaction boundary

`Ledgix Sale` is already a strong finalized-sale document with:

- retail/B2B channel awareness
- customer and salesperson snapshots
- item pricing snapshots
- tax snapshots
- discounts
- split tender rows
- paid / credit / outstanding amounts
- COGS and gross profit
- shift linkage
- returns metadata
- FBR state and invoice metadata

Its submit/cancel flow already coordinates stock, payment and FBR behavior. **Restaurant Order must not replace this finalized financial boundary.**

### Pricing

Keep and extend:

- `Ledgix Price List`
- `Ledgix Item Price`
- effective-date pricing
- customer/B2B pricing
- authorized price override with reason

Restaurant menu pricing should reuse this pricing engine rather than create a second `menu_price` truth.

### Payments / receivables

Keep:

- `Ledgix Payment`
- `Ledgix Payment Allocation`
- `Ledgix Payment Method`
- `Ledgix Sale Payment`

Restaurant settlement adds split-check and gratuity/service-charge behavior around this existing engine.

### Tax and FBR

Keep the existing Tax Center and FBR stack. This is a major product asset and should be adapted for branch-level fiscal configuration instead of rebuilt.

### Shifts

Keep `Ledgix POS Shift` as the cashier/session cash-control foundation and extend it with branch/terminal context.

### Returns

Keep the existing return engine for finalized restaurant sales. Restaurant-specific voids before settlement belong to the operational order workflow; refunds after settlement belong to `Ledgix Sales Return`.

### Inventory intelligence and reports

Keep the current inventory intelligence work and existing sales/purchase/stock reports. Add branch/location dimensions rather than throwing them away.

### Frappe-native shell

The current app has already reduced the old custom-chrome problem. Keep standard Frappe navigation/back behavior and only use immersive custom pages where the workflow needs them.

## 3.2 What must be modified

The biggest architectural limitation is that current stock is effectively global per item. `Ledgix Item.current_stock` is not sufficient for a multi-branch restaurant.

The following existing domains must become branch/location aware:

- Item stock balance
- Stock Movement
- Purchase
- Sale
- Sales Return
- POS Shift
- lots/serials where used
- inventory intelligence
- reports
- reorder logic
- pricing context where branch pricing is enabled
- tax/FBR context where fiscal identity differs by branch
- User Profile access

## 3.3 What should remain available but not dominate Restaurant UX

The following are valid platform capabilities but not primary restaurant surfaces:

- B2B sales
- receivables
- stock serial numbers
- classic retail POS Hold
- B2B invoice format

Do not delete stable capabilities simply because restaurants do not use them every day. Hide irrelevant shortcuts for restaurant roles and keep compatibility unless a feature actively conflicts with the restaurant architecture.

---

# 4. Source-of-Truth Matrix

There must be exactly one authoritative owner for each business concept.

| Concept | Authoritative model | Decision |
|---|---|---|
| Product / ingredient identity | `Ledgix Item` | Keep and extend |
| Product category | `Ledgix Category` | Keep |
| Menu presentation | New Restaurant Menu models | Add; never duplicate item master |
| Price | `Ledgix Price List` + `Ledgix Item Price` | Keep and extend |
| Customer | `Ledgix Customer` | Keep |
| Supplier | `Ledgix Supplier` | Keep |
| Cashier shift | `Ledgix POS Shift` | Keep and branch-enable |
| Open restaurant check/order | New `Ledgix Restaurant Order` | Add |
| Final fiscal sale | `Ledgix Sale` | Keep |
| Payment | Ledgix payment domain | Keep |
| Refund after finalized sale | `Ledgix Sales Return` | Keep |
| Stock movement ledger | `Ledgix Stock Movement` | Keep and location-enable |
| Per-location stock balance | New `Ledgix Stock Balance` | Add as maintained balance/cache |
| Purchasing receipt | `Ledgix Purchase` | Keep and evolve |
| Purchase order | New `Ledgix Purchase Order` | Add when procurement phase lands |
| Recipe | New `Ledgix Recipe` | Add |
| Kitchen dispatch | New KOT/KDS models | Add |
| Tax/FBR | Existing Ledgix tax/FBR services | Keep and branch-enable |
| Users/authentication | Frappe User / Role / User Permission | Keep native |
| General ledger accounting | Optional ERPNext integration later | Not V1 core |

---

# 5. Organization, Branch and Location Foundation

This phase comes **before** restaurant ordering because every serious restaurant workflow depends on correct location context.

## 5.1 New organization models

### `Ledgix Restaurant Brand`

Business/concept identity, separate from the technical single `Ledgix Brand Settings` doctype.

Suggested fields:

- brand name
- code
- active
- display logo / optional theme override
- default currency
- default timezone
- notes

`Ledgix Brand Settings` remains product/visual/legal fallback configuration. Do not overload it into a multi-record restaurant hierarchy.

### `Ledgix Branch`

Required fields:

- restaurant brand
- branch code
- branch name
- address
- phone
- timezone
- currency
- active
- default price list
- default tax profile
- default stock location
- default kitchen / expo configuration
- receipt header/footer settings where needed
- legal/fiscal identity link

For a single restaurant, installation should bootstrap one brand + one branch so chain complexity stays invisible.

### `Ledgix Stock Location`

Location belongs to a branch.

Examples:

- Main Store
- Kitchen Store
- Prep
- Bar
- Packaging

Do not create a complex warehouse tree unless a restaurant actually needs it.

Fields:

- branch
- location code/name
- location type
- active
- is default receiving location
- is default consumption location

### `Ledgix Stock Balance`

Unique key:

`item + stock_location`

Stores fast current balance and optional valuation snapshot. It is a derived operational balance; the stock movement ledger remains authoritative.

`Ledgix Item.current_stock` becomes legacy/aggregate compatibility data and must no longer be trusted as the only stock truth once location-aware inventory is enabled.

## 5.2 Existing documents to extend

Add branch/location snapshots to:

- `Ledgix Sale`
- `Ledgix Sales Return`
- `Ledgix Purchase`
- `Ledgix POS Shift`
- `Ledgix Stock Movement`
- lot/serial allocation records where applicable

A finalized transaction must retain its branch snapshot even if branch configuration changes later.

## 5.3 User access

Extend `Ledgix User Profile` with:

- default branch
- allowed branches
- optional default terminal / stock location

Use Frappe Roles + User Permissions for security. UI filtering alone is never authorization.

---

# 6. Item, Menu and Modifier Architecture

## 6.1 Keep `Ledgix Item` universal

Do not create separate duplicate item masters for menu products and ingredients.

Extend item classification with a controlled restaurant type, for example:

- Menu Item
- Ingredient
- Packaging
- Consumable
- Prepared / Finished Stock Item
- Retail Item

An item can be sellable, stock-tracked, recipe-produced or ingredient-consumed according to explicit flags instead of assumptions based only on type.

## 6.2 UOM conversion is mandatory

Restaurant inventory cannot be reliable with free-text UOM only.

Introduce a canonical stock UOM plus item-specific conversion rows, e.g.:

- 1 kg = 1000 g
- 1 carton = 12 bottles
- 1 bottle = 750 ml

Purchasing, recipes, stock movement and costing must normalize to the stock UOM.

## 6.3 New `Ledgix Menu`

A menu is a presentation/availability layer, not a duplicate inventory master.

Fields should support:

- name
- brand
- optional branch scope
- active dates
- order channels: Dine In / Takeaway / Delivery
- daypart / schedule
- price list
- active

Examples:

- All Day
- Breakfast
- Lunch
- Delivery
- Ramadan / seasonal menu

## 6.4 New `Ledgix Menu Item`

Links to `Ledgix Item` and contains only menu-specific data:

- menu
- item
- menu category / display section
- display name override
- image override if needed
- sort order
- availability schedule
- allowed order channels
- kitchen station override
- modifier groups
- enabled

Do not store a second tax or authoritative selling price here.

## 6.5 Modifiers — Core, not optional

A professional restaurant POS needs modifier logic from day one.

New models:

### `Ledgix Modifier Group`

Examples:

- Size
- Crust
- Add-ons
- Spice Level
- Cooking Preference
- Remove Ingredients

Rules:

- minimum selection
- maximum selection
- required/optional
- multi-select
- display order
- branch/menu scope if required

### `Ledgix Modifier Option`

Fields:

- label
- price delta
- active
- optional linked Ledgix Item for stock/cost effect
- optional kitchen label
- optional stock effect

Initial stock effects should support:

- No stock effect
- Add linked item/recipe quantity
- Exclude a recipe ingredient

Complex substitutions can be added after the core model is stable.

## 6.6 Availability and 86 / sold-out

Menu availability must support:

- manual branch-level 86 switch
- schedule/daypart availability
- optional stock-driven warning/block
- KDS/POS realtime update

Do not silently hide an item without showing staff why it is unavailable.

---

# 7. Recipe and Food-Cost Engine

## 7.1 New `Ledgix Recipe`

One active recipe version per produced/sold item for a given effective context.

Fields:

- finished/menu item
- recipe version
- batch/yield quantity
- output UOM
- effective from
- active
- notes / preparation instructions
- optional prep station

## 7.2 `Ledgix Recipe Ingredient`

Fields:

- ingredient item
- quantity
- UOM
- normalized stock quantity
- waste factor
- optional/non-stock flag where justified

## 7.3 Costing

Recipe costing should derive from current Ledgix ingredient valuation, not a separately maintained manual food cost.

Expose:

- recipe ingredient cost
- total recipe cost
- cost per serving
- selling price
- food cost %
- contribution margin
- gross margin %

Historical orders/sales must snapshot the cost used at transaction time so later purchase-cost changes do not rewrite history.

## 7.4 Ingredient consumption timing

For restaurant accuracy, ingredient consumption should be linked to **kitchen fire**, not payment time.

Rule:

1. Item is added to an open Restaurant Order — no stock movement yet.
2. Item is fired to kitchen — create exactly-once recipe consumption movements.
3. Item voided before kitchen preparation — authorized reversal can restore stock.
4. Item voided after preparation — do not pretend stock returned; record waste/comp reason.
5. Order later settles into `Ledgix Sale` — do not consume the same recipe again.

This requires explicit consumption references/idempotency on order-item/KOT level.

Prepared finished goods can use a different stock policy where required; the default restaurant path is ingredient consumption by recipe.

---

# 8. Restaurant Operational Order Model

`Ledgix Sale` is finalized financial truth. A restaurant needs a separate mutable operational object before settlement.

## 8.1 New `Ledgix Table Session`

Used for dine-in only.

Fields:

- branch
- floor/table
- opened at/by
- waiter/server
- covers
- status Open / Closing / Closed
- optional guest/customer

A table session can contain one or more open Restaurant Orders. This makes split checks and multiple parties/checks on the same table possible without corrupting the final sale model.

## 8.2 New `Ledgix Restaurant Order`

Think of this as the live restaurant check.

Required context:

- branch
- order number
- order type: Dine In / Takeaway / Delivery
- table session where applicable
- table
- waiter/cashier
- customer optional
- covers
- opened time
- promised/pickup time where applicable
- status
- pricing context
- tax context
- notes
- source/device/request id
- linked final `Ledgix Sale` after settlement

Recommended operational states:

- Draft
- Open
- In Kitchen
- Partially Ready
- Ready
- Served
- Closed
- Voided

Payment state should not be overloaded into kitchen state.

## 8.3 `Ledgix Restaurant Order Item`

Must preserve:

- item
- quantity
- price snapshot
- tax snapshot/reference
- seat number optional
- course optional
- modifiers
- kitchen station
- item note
- kitchen status
- fired quantity
- prepared quantity
- void quantity
- recipe/consumption reference
- authorization metadata for protected changes

## 8.4 Split checks without a duplicate billing system

One Restaurant Order settles to one `Ledgix Sale`.

When staff splits a check:

- create sibling Restaurant Orders under the same Table Session
- move whole items, seat items or allowed fractional quantities between orders
- preserve original order/item lineage for audit
- each resulting order settles independently to one Ledgix Sale

Support:

- split by seat
- split by item
- equal split where mathematically safe
- merge/recombine before final settlement

Do not mutate a submitted Ledgix Sale to achieve a split.

---

# 9. Floors and Tables

## 9.1 New `Ledgix Floor`

Fields:

- branch
- name
- display order
- active

## 9.2 New `Ledgix Restaurant Table`

Fields:

- floor
- branch
- table number/name
- capacity
- shape/display metadata
- active
- optional position data for visual floor plan

Operational states are derived from active table sessions and service state rather than manually edited permanent status fields where possible.

Visible states:

- Available
- Occupied
- Bill Requested / Closing
- Needs Cleaning
- Disabled

`Reserved` remains available for the future reservation module but reservation management itself is HOLD.

## 9.3 Table actions

Core actions:

- open table
- transfer/move table
- merge table sessions with authorization
- split checks
- change server
- adjust covers
- mark cleaning complete

All material moves must be auditable.

---

# 10. KOT / KDS Architecture

The KDS is one of the few places where a fully custom page is justified.

## 10.1 New `Ledgix Kitchen Station`

Examples:

- Grill
- Fry
- Pizza
- Cold Kitchen
- Drinks / Bar
- Dessert
- Expo

Configuration:

- branch
- station name/code
- active
- routing rules
- ticket display priority
- printer fallback configuration later

## 10.2 KOT is immutable dispatch history

Do not keep rewriting one kitchen ticket.

Each fire action creates a new delta KOT containing only the kitchen-relevant change.

New models:

- `Ledgix KOT`
- `Ledgix KOT Item`

KOT data:

- restaurant order
- branch
- station
- sequence/revision
- fired at/by
- action type
- status
- source device/request id

KOT item data:

- source order item
- action: Add / Void / Recall
- quantity delta
- modifiers snapshot
- seat/course
- kitchen note
- production timestamps

This prevents the classic error of reprinting/resending an entire order when only one item was added.

## 10.3 KDS states

Recommended item/ticket flow:

- New
- Preparing
- Ready
- Bumped / Completed

Order-level status is derived from item/ticket state.

## 10.4 KDS capabilities — Core

- station-specific queues
- all-station / expo view
- ticket age timer
- priority / rush marker
- modifiers and notes highly visible
- allergen/special instruction highlight when configured
- bump / ready
- recall with permission
- course hold/fire
- audible new-ticket alert, configurable
- realtime POS/KDS updates
- prep-time timestamps for analytics

Frappe realtime events should be used; polling is fallback, not the primary design.

## 10.5 Printing fallback

KDS is primary for the modern workflow, but kitchen ticket printing can remain a configurable fallback for restaurants that require paper.

Printer routing is station-based. Avoid hard-coding browser printer names into core business documents.

---

# 11. Restaurant POS — Custom Surface

The current `ledgix_pos` page is the right architectural location but its retail interaction model should be evolved into a restaurant-native POS.

Reuse existing:

- Ledgix pricing services
- shift validation
- payment methods
- tax engine
- idempotent request IDs
- customer lookup
- final sale creation
- returns/refund services
- design tokens / brand system

Do not blindly retain the current retail cart layout if it harms restaurant speed.

## 11.1 Primary POS layout

Recommended desktop/tablet shell:

### Header

- branch
- terminal/shift
- cashier/server
- order type
- table/check context
- connection state
- quick search

### Main menu area

- category rail/chips
- search
- large touch targets
- sold-out state
- daypart/menu state
- item cards

### Order/check area

- item rows
- modifiers
- seat/course labels
- notes
- quantity actions
- fire/hold state
- discounts/comps with permissions
- subtotal/tax/service charge/tip/grand total
- primary actions

## 11.2 Essential restaurant actions

- Dine In / Takeaway / Delivery
- open/select table
- add item
- modifier selection
- item note
- seat assignment optional
- course assignment optional
- send/fire to kitchen
- hold/fire course
- repeat item
- transfer table
- split check
- merge/recombine check
- multi-tender payment
- discount with reason
- comp with manager permission
- void with reason and kitchen-aware stock consequence
- reprint receipt
- refund finalized sale through return workflow

## 11.3 Manager authorization

Sensitive actions must use server-side authorization and reason capture:

- price override
- large discount
- comp
- post-fire void
- reopen/recall kitchen item
- table/check merge if risky
- refund
- shift variance override

PIN-style manager approval can be introduced as a fast UX layer, but it must resolve to an authenticated/authorized server identity.

## 11.4 Service charge, gratuity and tips

Support configurable:

- fixed/percentage service charge
- automatic gratuity based on branch/party size if desired
- manual tip
- tax treatment determined by configuration, not hard-coded

All adjustments must be snapshotted on the final sale.

## 11.5 Network resilience

V1 does **not** promise full offline fiscal operation.

Provide graceful degraded behavior:

- cache recent menu/config needed for rendering
- preserve unsent local draft state during short interruptions
- show clear offline/reconnecting state
- use idempotency/request IDs on mutations
- never show an order as finally paid/fiscalized until the server confirms it
- do not duplicate sale, KOT, payment or FBR posting after retry

True multi-device offline synchronization is a separate later project.

---

# 12. Takeaway and Delivery

## 12.1 Takeaway

Core fields:

- customer/contact optional
- pickup name
- promised time
- order note
- packaging implications

## 12.2 Delivery

V1 supports internal/manual delivery operation, not a full delivery marketplace.

Fields:

- customer
- phone
- delivery address
- delivery instructions
- delivery zone optional
- delivery fee
- promised time
- rider optional
- status

Suggested delivery states:

- New
- Preparing
- Ready for Dispatch
- Out for Delivery
- Delivered
- Cancelled

Third-party aggregators and driver apps are later integrations.

---

# 13. Purchasing and Inventory Operations

## 13.1 Existing `Ledgix Purchase` becomes receiving truth

Extend it with:

- branch
- destination stock location
- optional purchase-order reference
- supplier invoice/reference
- receiving user/time

Submitting a Purchase creates location-aware stock IN movements exactly once.

## 13.2 Add `Ledgix Purchase Order`

Use standard Frappe form/list/workflow rather than a custom purchasing dashboard.

Core states:

- Draft
- Pending Approval where enabled
- Ordered
- Partially Received
- Received
- Cancelled

Purchase Order does not move stock. Receiving through `Ledgix Purchase` does.

## 13.3 Stock transfers

Provide an atomic transfer workflow:

- source location OUT
- destination location IN
- same transfer reference
- no valuation gain/loss introduced by transfer
- server transaction guarantees both sides or neither side

A small `Ledgix Stock Transfer` document is justified for auditability.

## 13.4 Waste

Waste is an explicit stock OUT reason, not an arbitrary adjustment.

Capture:

- branch/location
- item
- quantity/UOM
- reason
- linked order/KOT where relevant
- user
- manager approval threshold where configured

Common reasons:

- spoilage
- overproduction
- post-prep void
- staff meal
- damaged
- quality rejection

## 13.5 Stock count

Add a simple cycle/physical count workflow after location-aware stock is stable:

- count sheet by location
- expected quantity
- counted quantity
- variance
- authorized adjustment on submit

## 13.6 Reorder intelligence

Evolve existing low-stock/inventory intelligence to use:

- item + location balance
- location reorder level
- recent consumption
- open purchase order quantity
- configurable lead time later

Do not put AI forecasting in V1.

---

# 14. Fiscal, Tax and FBR Strategy

The existing FBR implementation is retained.

## 14.1 Current limitation

`Ledgix FBR Settings` is currently a Single doctype with one seller identity/token context. Multi-branch/multi-entity operation eventually needs scoped fiscal profiles.

## 14.2 Target

Introduce a branch-linked fiscal profile without breaking the existing Single settings contract.

Recommended migration direction:

- Existing FBR Settings remains global control/safety/default configuration during transition.
- New `Ledgix Fiscal Profile` carries branch/legal seller identity and branch-specific credentials/config where legally required.
- Branch links to one fiscal profile.
- Final `Ledgix Sale` freezes resolved seller/fiscal identity.
- Existing submission logs remain historical truth.

Never rewrite historical fiscal identity because a branch profile changed.

## 14.3 Restaurant order vs FBR

Open Restaurant Order/KOT activity is not fiscal posting.

FBR submission remains attached to finalized `Ledgix Sale` after settlement according to configured submission rules.

---

# 15. Workspace and UI Surface Map

The product should have very few custom pages.

## 15.1 Custom pages — justified

### 1. Restaurant POS

High-frequency touch workflow; custom page required.

### 2. KDS / Kitchen

Realtime operational board; custom page required.

### 3. Tax & FBR Center

Keep current custom center because it coordinates multiple compliance workflows.

### 4. Operations / Owner Dashboard

One focused management surface is justified if it combines live restaurant metrics and exceptions that would otherwise require many reports.

Do not create separate custom centers for every module.

## 15.2 Prefer native Frappe forms/lists for

- Restaurant Brand
- Branch
- Stock Location
- Items
- Categories
- Menus
- Modifier Groups
- Recipes
- Kitchen Stations
- Floors
- Tables
- Customers
- Suppliers
- Purchase Orders
- Purchases / Receipts
- Stock Transfers
- Waste entries
- Payment Methods
- Price Lists
- Item Prices
- User Profiles
- fiscal configuration

These forms can be carefully structured with sections, columns, sensible defaults and short field sets. Do not replace them with custom pages just for appearance.

## 15.3 Workspace target

Restaurant workspace sections:

### Service

- Restaurant POS
- Tables / Floor
- Open Orders
- KDS
- Shifts

### Menu

- Menus
- Items
- Categories
- Modifier Groups
- Recipes
- Kitchen Stations

### Inventory & Buying

- Current Stock
- Stock Locations
- Stock Transfers
- Waste
- Purchase Orders
- Purchases / Receiving
- Suppliers
- Inventory Intelligence

### Customers & Finance

- Customers
- Payments
- Returns
- Payment Methods
- Price Lists

### Reports

- Sales
- Product Mix
- Kitchen Performance
- Table/Cover Performance
- Food Cost / Margin
- Stock / Waste
- Purchases
- Shift/Cash

### Tax & Compliance

- Tax & FBR Center
- Tax Profiles
- FBR Logs
- Fiscal Profiles

### Administration

- Restaurant Brands
- Branches
- User Profiles
- Brand Settings

Role visibility should remove sections users do not need.

---

# 16. Visual / Interaction System — “Apple-style”, not imitation

“Apple-style” means discipline, not copying Apple UI.

## 16.1 Principles

- one clear primary action per state
- minimum chrome
- no decorative dashboards full of colored cards
- generous whitespace
- typography before borders
- subtle elevation only where it conveys hierarchy
- neutral surfaces with restrained Ledgix accent color
- consistent 8px spacing rhythm
- minimum ~44px touch targets on POS/KDS controls
- clear selected/focused states
- no tiny inline actions for high-frequency touch workflows
- destructive actions separated and confirmed appropriately
- motion only to explain state change, not decorate

## 16.2 Frappe integration

Back-office pages keep the recognizable Frappe shell.

POS and KDS may use immersive full-width content inside Frappe, but must retain predictable navigation/session behavior and must not build a second application shell/sidebar.

## 16.3 Responsive targets

Primary:

- 1920×1080 cashier/KDS displays
- 1366×768 common POS terminals
- 10–13 inch tablets

Secondary:

- manager laptop
- mobile manager read-only/quick actions later

Never make the primary POS depend on hover.

---

# 17. Roles and Permissions

Retain existing technical roles for compatibility and introduce restaurant-role profiles deliberately.

Recommended role set:

- Ledgix Admin / Restaurant Admin
- Restaurant Owner
- Branch Manager
- Cashier
- Waiter / Server
- Kitchen User
- Kitchen Manager / Expo
- Store / Inventory User
- Purchase User
- Back Office / Accountant

Do not create custom authentication.

Server permissions must enforce:

- allowed branch
- allowed actions
- submitted-document restrictions
- manager-only exceptions
- kitchen-station scope if enabled
- cost/margin visibility
- FBR credential/config visibility

Cashier and waiter users should not automatically see ingredient cost, business margin or sensitive tax credentials.

---

# 18. Reporting and Management Intelligence

The current inventory intelligence work is retained and branch-enabled.

## 18.1 Owner / manager core KPIs

- net sales
- order count
- covers
- average check
- sales by order channel
- sales by branch
- payment mix
- discount amount/rate
- comp amount/rate
- voids/refunds
- gross margin
- food cost %
- waste cost
- top/bottom menu items
- product mix
- table turn time
- average prep time
- KDS late-ticket rate
- shift variance

## 18.2 Reports

### Restaurant sales

- by branch
- order type
- menu/category/item
- waiter/cashier
- hour/day/daypart
- payment method

### Kitchen performance

- average fire-to-ready time
- station throughput
- late tickets
- recall/void rate
- peak periods

### Table performance

- covers
- average check per cover
- table turns
- average session duration

### Menu engineering

- quantity sold
- revenue
- contribution margin
- food cost %
- popularity vs margin matrix

### Inventory

- stock by branch/location
- consumption
- variance
- waste
- stock movement
- low stock
- reorder suggestions

Reports should use Frappe report infrastructure unless a visual combined dashboard provides substantially better decision-making.

---

# 19. Core Market-Level Feature Boundary

## 19.1 Must ship in the main restaurant product

- single and multi-branch foundation
- branch-scoped users
- dine-in / takeaway / delivery order types
- floor/table management
- open checks
- seat tracking
- courses + hold/fire
- menu/daypart/channel availability
- modifiers
- 86/sold-out
- KOT delta dispatch
- multi-station KDS
- expo view
- split checks
- table/check transfer/merge
- multi-tender payment
- discounts/comps/void reasons and permissions
- shifts/cash control
- thermal receipt
- tax/FBR integration
- ingredient recipes
- food costing
- branch/location inventory
- purchase receiving
- purchase orders
- stock transfer
- waste
- core restaurant reports
- owner/manager operating dashboard

## 19.2 Phase 1.1 / after stable core

- stock count/cycle count UI
- advanced promotions / combo rules
- automatic gratuity rules
- QR customer menu
- printer routing service
- richer delivery zones/rider workflow
- menu bulk editor
- central chain menu publishing with branch overrides
- advanced recipe substitutions
- advanced forecast/reorder formulas

## 19.3 HOLD — do not build now

- Reservations
- Waitlist
- Guest CRM suite
- Loyalty program
- Gift cards
- customer mobile app
- online ordering storefront
- third-party delivery aggregators
- payroll / payslips
- HR suite
- AI recommendations
- AI forecasting
- dynamic pricing
- full offline multi-device synchronization
- enterprise franchise royalties
- central kitchen manufacturing/MRP
- complex commissary replenishment
- ERPNext general-ledger integration

These are valid future modules but are not required to make V1 a professional restaurant operating system.

---

# 20. Migration / Compatibility Rules

The restaurant conversion must be additive first.

## 20.1 Do not delete working retail code during foundation phases

Before removal, prove that:

- no route imports it
- no fixture references it
- no patch references it
- no report/print format depends on it
- no existing tests require it
- replacement behavior is tested

The old plan contained delete lists for paths from previous Ledgix UI generations. Those lists are obsolete and must **not** be executed blindly against the current repository.

## 20.2 Preserve transaction history

Existing Ledgix Sale, Payment, Purchase, Return and Stock Movement records remain valid.

Branch/location migration requires explicit defaults:

- bootstrap one default Restaurant Brand
- bootstrap one default Branch
- bootstrap one default Stock Location
- backfill existing transactions to that branch/location only where semantics are safe
- log migration counts and ambiguous rows

Migration patches must be idempotent.

## 20.3 No direct data mutation from UI

All important mutations go through server services/controllers with:

- permission checks
- state validation
- idempotency where retryable
- audit metadata
- database transaction boundaries

---

# 21. Implementation Roadmap

Each phase must end with migration + automated tests + smoke test before the next phase starts.

## Phase 0 — Baseline Lock

Current baseline:

- Frappe v15
- `ledgix_saas` installed
- clean site migration
- existing Ledgix transaction engine intact

Tasks:

- snapshot current tests
- document current routes/pages/DocTypes
- fix packaging metadata/version mismatch
- update product description/visible branding to Restaurant without renaming technical package
- establish test factory helpers for branch/location

**Gate:** current Ledgix tests pass before schema work.

## Phase 1 — Branch + Location Foundation

Build:

- Restaurant Brand
- Branch
- Stock Location
- Stock Balance
- branch access on User Profile
- branch/location fields on core transactions
- location-aware stock service
- location-aware low stock/inventory intelligence
- bootstrap/backfill patch

Refactor `Ledgix Item.current_stock` away from being the sole truth.

**Gate:** two branches can hold different quantities for the same item with no leakage.

## Phase 2 — Item/UOM/Menu/Modifier Foundation

Build:

- item restaurant classification
- stock UOM + conversions
- Menu
- Menu Item
- Modifier Group
- Modifier Option
- menu schedule/daypart/channel rules
- branch 86 state
- branch-aware pricing resolution

**Gate:** same item can be available/priced differently by configured branch/menu context without duplicating the item master.

## Phase 3 — Recipe + Food Cost

Build:

- Recipe
- Recipe Ingredient
- conversion-aware recipe quantities
- recipe cost calculation
- food cost/margin views
- version/effective-date rules

No kitchen stock consumption yet until the order/KOT idempotency model exists.

**Gate:** recipe cost reconciles to ingredient valuation and UOM conversions.

## Phase 4 — Floors, Tables and Operational Orders

Build:

- Floor
- Restaurant Table
- Table Session
- Restaurant Order
- Restaurant Order Item
- audit events
- seat/course fields
- split/merge/move server services

**Gate:** dine-in checks can remain open and mutate safely without creating premature finalized sales.

## Phase 5 — KOT + KDS + Ingredient Consumption

Build:

- Kitchen Station
- KOT/KOT Item
- routing
- delta fire model
- KDS custom page
- expo view
- realtime events
- prep timers
- exactly-once recipe consumption
- pre-prep reversal vs post-prep waste behavior

**Gate:** adding one item to an already-fired order creates only one new kitchen delta and exactly one stock consumption event.

## Phase 6 — Restaurant POS Rebuild

Evolve `ledgix_pos` using existing transaction services.

Build:

- order-type workflow
- table/check workflow
- menu + modifiers
- seat/course interaction
- fire/hold
- split/merge
- service charge/tip
- discount/comp/void approvals
- settlement → exactly one Ledgix Sale per settled Restaurant Order
- multi-tender payment

**Gate:** full dine-in/takeaway/delivery golden paths pass.

## Phase 7 — Purchasing + Inventory Operations

Build/evolve:

- branch receiving
- Purchase Order
- partial receiving
- Stock Transfer
- Waste
- location-aware reorder
- stock count after base workflows are stable

**Gate:** purchase, transfer, recipe consumption, waste, return and stock count reconcile to the stock movement ledger.

## Phase 8 — Fiscal + Branch Compliance

Build:

- branch fiscal profile architecture
- FBR resolution by branch
- receipt/invoice branch identity
- FBR sandbox regression tests
- correction/refund behavior with Restaurant sales

**Gate:** finalized restaurant sales preserve correct branch seller identity and existing FBR safety controls.

## Phase 9 — Reports + Owner Operations

Build:

- restaurant Sales report dimensions
- Kitchen Performance
- Table/Cover Performance
- Menu Engineering
- Food Cost / Waste
- shift/cash exceptions
- branch/chain filters
- one restrained management dashboard

**Gate:** dashboard numbers reconcile to source reports/documents.

## Phase 10 — UX Polish + Hardware + Performance

- responsive POS/KDS
- keyboard shortcuts
- touch ergonomics
- loading/empty/error states
- reconnect state
- thermal print polish
- optional kitchen print fallback
- realistic high-volume fixture data
- query/index review

**Gate:** common order operations remain fast with realistic data volume.

## Phase 11 — Security / Regression / Go-Live

- role matrix tests
- branch isolation tests
- duplicate-submit tests
- concurrent stock tests
- KOT idempotency tests
- payment/return tests
- FBR sandbox tests
- migration rerun/idempotency tests
- backup/restore test
- production smoke checklist

---

# 22. Golden-Path Acceptance Flows

## 22.1 Dine-in

```text
Open Shift
→ Select Branch/Floor/Table
→ Open Table Session
→ Add Check
→ Add Items + Modifiers + Seats/Courses
→ Fire KOT
→ Kitchen Stations Prepare
→ Expo Ready
→ Add second round as delta KOT
→ Split/merge check if required
→ Settle with one or more payment methods
→ Create Ledgix Sale
→ FBR according to branch policy
→ Print Receipt
→ Close Check/Table Session
```

## 22.2 Takeaway

```text
Open Shift
→ New Takeaway Order
→ Add Menu Items + Modifiers
→ Set Pickup Name/Time
→ Fire Kitchen
→ Ready
→ Settle
→ Ledgix Sale + Receipt/FBR
```

## 22.3 Delivery

```text
New Delivery Order
→ Customer/Address/Contact
→ Delivery Fee/Promise Time
→ Fire Kitchen
→ Ready for Dispatch
→ Out for Delivery
→ Settle according to configured payment flow
→ Delivered
```

## 22.4 Post-fire void

```text
Item Fired
→ Staff requests void
→ Manager authorization + reason
→ Kitchen delta VOID
→ If not prepared: reverse recipe consumption
→ If prepared: create waste/comp consequence
→ Audit retained
```

## 22.5 Split bill

```text
One open table check
→ Split by seat/item/equal rule
→ Sibling Restaurant Orders created
→ Original lineage retained
→ Each check settled independently
→ One Ledgix Sale per settled check
```

---

# 23. Non-Negotiable Engineering Rules

1. **One source of truth per concept.**
2. **No second stock engine.**
3. **No second payment engine.**
4. **No ERPNext dependency merely to avoid designing a small missing restaurant model.**
5. **No custom page when a native Frappe form/list is better.**
6. **POS/KDS state changes are server-authoritative.**
7. **Every retryable mutation is idempotent.**
8. **Every branch-scoped API enforces branch authorization server-side.**
9. **Submitted financial/fiscal history is immutable except through explicit correction/refund flows.**
10. **Kitchen fire and ingredient consumption cannot double-run.**
11. **Post-prep voids create operational truth, not fake stock returns.**
12. **Historical price/tax/cost/fiscal snapshots never depend on current master data.**
13. **Migrations are additive and rerunnable before destructive cleanup.**
14. **No feature is considered done without tests for its failure/duplicate path.**
15. **UI simplicity is a product requirement, not a final styling task.**

---

# 24. Testing Strategy

## 24.1 Unit/domain tests

- branch/location stock calculations
- UOM conversion
- pricing context
- recipe cost
- modifier validation
- KOT deltas
- recipe consumption idempotency
- table/check split logic
- discounts/authorization
- payment totals
- tax/FBR payload resolution

## 24.2 Integration tests

- purchase → stock location
- KOT fire → recipe stock OUT
- post-fire void → reversal/waste
- restaurant settlement → Ledgix Sale
- sale → payments → FBR
- return → refund → stock according to policy
- cross-branch permission isolation

## 24.3 Concurrency / integrity

Test:

- two terminals selling same constrained stock
- duplicate create-sale request ID
- duplicate KOT fire
- simultaneous table edits
- duplicate payment callback/retry
- transfer atomicity
- final-sale retry after transient network failure

## 24.4 UI smoke

At minimum:

- cashier POS
- waiter/table flow
- KDS station
- expo
- branch manager
- store user
- admin/FBR

Test realistic 1366×768 and tablet layouts, not only large desktop screens.

---

# 25. Definition of Done for Restaurant V1

V1 is not complete because many DocTypes exist. It is complete when a real restaurant can run a service shift without falling back to spreadsheets for the core flow.

The release must prove:

- branch/user isolation works
- menus/modifiers are fast to operate
- tables and open checks are reliable
- KOT/KDS never duplicates kitchen work
- kitchen timing is visible
- recipe inventory reconciles
- split checks settle correctly
- payments/shifts reconcile
- refunds/voids are controlled and auditable
- tax/FBR remains safe
- receiving/transfers/waste reconcile stock
- management reports reconcile to transactions
- staff only see the complexity relevant to their job
- the POS remains calm and fast during peak service

---

# 26. Final Product Direction

The correct build is **not** “ERPNext Restaurant with a prettier POS” and it is **not** “Retail Ledgix with table numbers added.”

The correct product is:

> **Ledgix Restaurant = the existing Ledgix transaction/compliance engine + a restaurant-native operational layer + Frappe-native back office.**

The current Ledgix work is valuable and remains underneath the product. The restaurant build should concentrate new code where the retail engine genuinely has no equivalent: branches/locations, menus/modifiers, recipes, tables/open checks, KOT/KDS and restaurant-specific operating analytics.

That produces a system that can start cleanly for one restaurant, scale to several outlets without redesigning core truth, and eventually support a larger chain without making the first customer operate an enterprise ERP.
