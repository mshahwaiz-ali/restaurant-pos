Plan For Resturant POS

# Ledgix Restaurant Management & POS

## Locked Product Architecture & Development Blueprint — v1.0

**Product Type:** Restaurant Management System + Point of Sale
**Foundation:** Ledgix + Frappe/ERPNext
**Target:** Single Restaurant → Multi-Branch Restaurant → Multi-Brand / Multi-Chain Group

---

# 1. Product Vision

Ledgix Restaurant will be a complete restaurant operating platform built around one simple principle:

> **Running a restaurant should feel simple even if the system behind it is powerful.**

It will not be an overloaded ERP screen presented to restaurant staff.

Instead:

* Cashier sees the POS.
* Waiter sees tables and orders.
* Kitchen sees KDS/KOT.
* Store staff sees inventory.
* Manager sees branch operations.
* Accountant sees ERPNext finance.
* Owner sees the entire business from one clean dashboard.

The product should work equally well for:

### A. Single Restaurant

```text
ABC Restaurant
└── DHA Branch
```

Everything works without exposing chain-related complexity.

### B. Multi-Branch Restaurant

```text
ABC Restaurant
├── DHA
├── Gulberg
├── Johar Town
└── Islamabad
```

Shared menus, centralized reporting and controlled branch configuration.

### C. Multi-Brand / Multi-Chain Group

```text
Restaurant Group
│
├── Burger Brand
│   ├── DHA
│   └── Gulberg
│
├── Pizza Brand
│   ├── DHA
│   └── Islamabad
│
└── Cloud Kitchen Brand
    └── Lahore Kitchen
```

The same architecture scales without creating a second product.

---

# 2. Scope Philosophy

We are **not** trying to build every restaurant technology product in version one.

The first product must perfectly handle five things:

```text
SELL
  ↓
COOK
  ↓
CONTROL STOCK
  ↓
CONTROL MONEY
  ↓
UNDERSTAND BUSINESS
```

Everything else is secondary.

This is important because competing systems already provide large feature catalogs. Foodics offers table management, coursing, multiple payments, order splitting, inventory, supplier purchasing, transfers and internal approvals; Petpooja provides multi-stage recipes, central kitchens and large-chain management; Toast combines restaurant POS, online ordering, inventory and multi-location management.

Our goal therefore is **not feature-count competition**.

Our goal is:

> Better integration, better control, better UX and better visibility.

---

# 3. Scope We Are Locking

## Core Product — Build Now

1. Restaurant organization / branch / chain architecture
2. Menu management
3. Variants, modifiers and combos
4. Restaurant POS
5. Dine-in tables and floor management
6. Takeaway
7. Basic phone/delivery orders
8. Kitchen tickets / KOT
9. Kitchen Display System
10. Course / hold / fire workflow
11. Bills and payment handling
12. Split bills and mixed payments
13. Cashier / till management
14. Void / refund / discount controls
15. Recipe management
16. Ingredient consumption
17. Restaurant inventory
18. Stock counts
19. Waste / spoilage / staff consumption
20. Supplier purchasing
21. Warehouse / branch transfers
22. Basic central kitchen support
23. Food costing
24. Actual vs theoretical consumption
25. Menu profitability
26. Restaurant-specific dashboards
27. Multi-branch / multi-chain reporting
28. Employee access / roles / branch assignment
29. Full audit trail
30. ERPNext accounting integration
31. Pakistan fiscal/FBR integration architecture
32. Receipt and kitchen printing
33. Operational notifications / exception alerts
34. APIs and future integration framework

---

# 4. Explicitly NOT in Core Version

These are deliberately deferred.

## Reservations / Waitlist

**HOLD.**

No reservation engine in the initial product.

The data architecture will not block it later, but we will not spend development time implementing reservations now.

---

## Advanced Guest CRM

**HOLD.**

Basic customer details can still be attached to an order:

* Name
* Mobile
* Address
* Email
* Basic order history

But no:

* automated campaigns
* customer segmentation engine
* birthday campaigns
* VIP workflows
* preference tracking engine
* marketing automation

Yet.

---

## Payroll / Payslips

**Not custom-built in RestaurantOS.**

Core restaurant staff management only needs:

* employee/user
* branch
* role
* access level
* POS PIN
* cashier assignment
* manager authority

If a client later needs full:

* attendance
* leave
* payroll
* salary slips
* overtime
* biometric integration

we can enable/integrate **Frappe HR** separately.

This prevents RestaurantOS itself becoming an HR project.

---

## Loyalty / Advanced Marketing

Phase 2.

Architecture remains compatible with:

* points
* tiers
* vouchers
* coupons
* gift cards
* campaign automation

but these are not required for core restaurant operations.

---

## Reservations / Customer CRM

Phase 2 or later.

---

## Customer QR Ordering

Phase 2.

---

## Self-Service Kiosk

Phase 2.

---

## Delivery Aggregator Integrations

Phase 2.

The core order model will already have:

```text
Order Source
Channel
External Order ID
External Platform
Commission
Delivery Fee
```

so Foodpanda / Careem / other integrations can plug in later without redesigning orders.

---

## AI

**Future only.**

No AI should delay production.

AI becomes valuable after real production data exists.

Recommended window:

> Core system completed → production deployment → approximately 2–3 months operating data → AI layer.

Potential future AI:

* sales forecasting
* stockout prediction
* prep recommendations
* purchase recommendations
* suspicious transaction detection
* supplier price anomaly detection
* automated owner summaries
* menu price recommendations

But **none of this is required for V1**.

---

# 5. Organization Architecture

This is one of the most important architecture decisions.

## Deployment

Prefer:

```text
One Frappe Site
=
One Client / Restaurant Group
```

This gives strong data isolation.

Inside each client:

```text
Client / Restaurant Group
        ↓
Legal Entity
        ↓
Brand
        ↓
Branch
        ↓
Restaurant Operations
```

---

# 6. Legal Company vs Brand vs Branch

We should not make every restaurant branch an ERPNext Company.

### ERPNext Company

Represents a **legal/accounting entity**.

### Restaurant Brand

Represents the commercial concept.

Example:

```text
Zuberi Foods Pvt Ltd
    │
    ├── FireBurger
    └── Napoli Pizza
```

### Branch

Physical operating location.

```text
FireBurger
├── DHA
├── Gulberg
└── Islamabad
```

Each branch maps to appropriate ERPNext structures such as:

* Branch
* Cost Center
* Warehouse
* POS configuration
* Accounting defaults

This gives proper consolidated accounting without abusing ERP companies.

---

# 7. Menu Management

The menu must be restaurant-specific instead of merely exposing ERPNext Items.

## Menu Structure

```text
Menu
 ├── Category
 │    ├── Burgers
 │    ├── Pizza
 │    ├── Drinks
 │    └── Desserts
 │
 └── Menu Item
```

Each menu item can contain:

* Name
* Image
* Description
* Category
* Selling price
* Tax
* Recipe
* Kitchen station
* Active / inactive
* Branch availability
* Order-channel availability
* Day/time availability
* Preparation notes

---

# 8. Variants

Example:

```text
Pizza
├── Small
├── Medium
└── Large
```

Variants may change:

* selling price
* ingredients
* recipe quantities
* preparation time

---

# 9. Modifier Groups

Example:

```text
Zinger Burger

Cheese
├── No Cheese
├── Cheddar +100
└── Double Cheese +180

Sauce
├── Mayo
├── Garlic
└── Spicy

Extras
├── Extra Patty
├── Jalapeño
└── Egg
```

Modifiers should affect both:

### Selling Price

and, where configured,

### Ingredient Consumption

Example:

```text
Extra Cheese
Price: +Rs 120
Stock effect: -1 Cheese Slice
```

This is essential for accurate food costing.

---

# 10. Combos / Meals

Support:

```text
Zinger Meal

1 Zinger Burger
+
1 Fries
+
1 Drink
```

Drink may have selectable choices.

Combo pricing may differ from individual product totals.

All underlying recipe consumption must remain accurate.

---

# 11. Multiple Menus

Support:

* Breakfast
* Lunch
* Dinner
* Dine-in
* Takeaway
* Delivery
* Brand-specific menus

A branch can inherit a corporate menu and selectively override allowed values.

---

# 12. Branch Pricing

Example:

```text
Burger

DHA             Rs 850
Islamabad       Rs 900
Delivery        Rs 950
```

Pricing should support:

* default price
* branch price
* channel price

without creating duplicate menu items.

---

# 13. Menu Availability / 86

When an item is unavailable:

```text
BURGER → SOLD OUT
```

Cashier and waiter should see this immediately.

Manager can manually 86/un-86 items.

Later this can be automatically tied to ingredient availability.

---

# 14. POS / Service Console

This is the product's most important interface.

It must feel extremely fast.

## Core Order Types

```text
Dine-In
Takeaway
Delivery
Phone Order
```

Future order sources can plug into the same engine.

---

# 15. POS Workflow

Typical counter workflow:

```text
New Order
   ↓
Select Items
   ↓
Variants / Modifiers
   ↓
Optional Notes
   ↓
Send Kitchen
   ↓
Payment
   ↓
Receipt
   ↓
Close
```

The interface should minimize clicks.

---

# 16. Dine-In Architecture

For dine-in:

```text
Floor
  ↓
Table
  ↓
Dining Session
  ↓
Restaurant Order
  ↓
Kitchen Tickets
  ↓
Check / Bill
  ↓
Payment
```

This is intentionally separate from the final ERP invoice.

A restaurant order exists **before accounting settlement**.

---

# 17. Floor Management

Manager can configure:

* Floors
* Areas
* Tables
* Table number
* Seating capacity
* Shape/position where useful

Examples:

```text
Ground Floor
VIP Hall
Terrace
Outdoor
```

Current systems such as Odoo, Square and Foodics already treat table/floor management as baseline full-service functionality.

---

# 18. Table Status

Simple visual states:

```text
Available
Occupied
Ordering
Kitchen
Ready
Billing
```

No unnecessary complexity.

---

# 19. Table Transfer

Customer moves:

```text
Table 4
   ↓
Table 9
```

Order follows the table.

---

# 20. Table Merge

Two parties join:

```text
Table 4 + Table 5
```

Orders may be merged into one dining session without losing audit history.

---

# 21. Server / Waiter Assignment

Optional waiter can be assigned to:

* table
* session
* order

Manager reports can then show sales by waiter without implementing full HR.

---

# 22. Courses

Enough functionality for proper full-service restaurants:

```text
Starters
Main
Dessert
```

Waiter can:

```text
HOLD
```

and later:

```text
FIRE
```

No advanced AI timing or kitchen optimization in V1.

---

# 23. Bill Splitting

Support the methods people actually use:

### By Item

Guest A pays burger.

Guest B pays pizza.

### Equal Split

```text
Rs 9,000
÷
3 people
=
Rs 3,000 each
```

### Custom Amount

Manual partial amount.

Seat-level sophistication can be expanded later if genuinely demanded.

---

# 24. Mixed Payments

One bill may have:

```text
Cash      Rs 2,000
Card      Rs 5,000
Wallet    Rs 3,000
```

Total settlement must always reconcile exactly.

---

# 25. Payment Methods

Configurable:

* Cash
* Debit/Credit Card
* Bank
* Wallet
* QR Payment
* Other configured modes

ERP accounting mapping remains centralized.

---

# 26. Service Charges, Tips and Taxes

Support configurable:

* sales tax
* service charge
* tips
* branch-specific taxation where appropriate

Final accounting posting must be deterministic and auditable.

---

# 27. Kitchen Order Ticket — KOT

Kitchen operations must not depend on the final invoice.

When waiter presses:

```text
SEND TO KITCHEN
```

a KOT is created.

---

# 28. Delta KOT

Critical restaurant behavior.

Original:

```text
Burger
Fries
```

Five minutes later customer adds:

```text
Coke
```

Kitchen receives:

```text
ADD
+ Coke
```

The original ticket is not regenerated.

---

# 29. KOT Cancellation

If food has already been fired:

```text
CANCEL ITEM
```

must produce an auditable cancellation event containing:

* original item
* quantity
* employee
* time
* reason
* manager approval where required

The original kitchen history never disappears.

---

# 30. Kitchen Stations

Examples:

```text
Grill
Fryer
Pizza
Bar
Dessert
Cold Kitchen
```

Each menu item routes automatically.

Example:

```text
Burger → Grill
Fries  → Fryer
Coke   → Bar
```

---

# 31. Kitchen Display System

KDS should provide:

* station-specific tickets
* order number
* table/order type
* items
* modifiers
* notes
* elapsed time
* priority
* item status
* order status
* bump
* recall

---

# 32. KDS Timers

Simple operational warnings:

```text
0–7 min    Normal
8–12 min   Attention
12+ min    Late
```

Thresholds configurable by business.

Foodics currently markets multi-station KDS workflows and processing-time reporting, while Odoo provides dedicated preparation displays and station/status workflows.

We should meet the operational baseline without initially building unnecessary algorithmic kitchen optimization.

---

# 33. Expo View

For restaurants with multiple stations:

```text
Grill ──┐
Fryer ──┼──> EXPO ──> SERVE
Bar ────┘
```

Expo sees whether the complete order is ready.

For a small restaurant this module can simply be disabled.

---

# 34. Kitchen Printer Fallback

KDS is preferred where deployed.

But restaurant operations should also support configured:

* kitchen printers
* bar printers
* receipt printers

If a restaurant does not want KDS, KOT printing remains usable.

---

# 35. Recipe Management

This is one of the key product differentiators.

ERPNext BOM alone should not represent every plated dish.

## Restaurant Recipe

Example:

```text
Chicken Burger

Burger Bun       1 ea
Chicken          120 g
Sauce             25 g
Lettuce            20 g
Cheese              1 slice
Oil                 8 ml
```

---

# 36. Sub-Recipes

Example:

```text
Garlic Mayo
├── Mayo
├── Garlic
├── Lemon
└── Seasoning
```

Then:

```text
Burger Recipe
└── Garlic Mayo 25 g
```

This avoids duplicating ingredients across hundreds of dishes.

---

# 37. Recipe Yield

Support prep batches:

```text
10 kg Raw Tomatoes
        ↓
8.1 kg Prepared Sauce
```

Yield allows actual recipe costing rather than assuming zero preparation loss.

---

# 38. Recipe Revisions

Recipe modifications should be versioned/effective-dated.

If chicken changes from:

```text
120g → 135g
```

historical sales should not suddenly appear to have used the new recipe.

---

# 39. ERP Manufacturing Boundary

Use **Restaurant Recipes** for dishes prepared to order.

Use **ERPNext stock/manufacturing mechanisms** where real stocked production exists.

Example:

```text
Central Kitchen
Raw ingredients
      ↓
50 kg Pizza Sauce Batch
      ↓
Stocked Prepared Item
      ↓
Transfer to Branches
```

That genuinely behaves like production.

We should not create ERP manufacturing work orders every time someone orders a burger.

---

# 40. Restaurant Consumption Ledger

A dedicated operational consumption layer should record theoretical ingredient usage from each sold/fired item.

Example:

```text
Order #1482
Burger × 3
        ↓
Chicken -360g
Buns    -3
Sauce   -75g
```

This gives us restaurant-speed tracking without making the POS wait for heavy accounting/stock operations.

ERPNext remains the authoritative physical stock/accounting engine.

Consumption can be posted into ERP stock through controlled aggregated synchronization rather than creating excessive stock transactions during peak service.

---

# 41. Inventory Management

Use ERPNext for core stock capabilities wherever possible instead of rebuilding them.

Core inventory covers:

* raw materials
* packaging
* beverages
* prepared items
* warehouses
* stock receipts
* transfers
* adjustments
* batches
* expiry where applicable
* UOM conversions

RestaurantOS provides the restaurant-aware layer.

---

# 42. Automatic Recipe Consumption

When a menu item sells, theoretical ingredient consumption is automatically generated.

No manual stock deduction by cashier.

---

# 43. Low Stock

Branch dashboard shows:

```text
Chicken      LOW
Cheese       LOW
Coke         OK
Buns         CRITICAL
```

Simple thresholds first.

Predictive stock AI later.

---

# 44. Inventory Count

Store staff can conduct physical stock counts.

Critical option:

### Blind Count

Employee enters the quantity without seeing expected quantity.

This reduces manipulation.

After submission:

```text
Expected: 44 kg
Counted:  39 kg
Variance: -5 kg
```

---

# 45. Waste

Waste must have explicit reasons:

* Spoilage
* Expired
* Burnt
* Dropped
* Preparation waste
* Customer return
* Quality rejection
* Staff meal
* Sample
* Other authorized reason

Waste affects inventory and analytics.

---

# 46. Actual vs Theoretical

This is a **core report**, not future AI.

Restaurant365's Actual-vs-Theoretical model compares inventory actually used with what recipes/POS sales imply should have been used, allowing operators to identify costly variance.

Our example:

```text
Chicken

Theoretical usage     86.4 kg
Actual usage          94.2 kg
Known waste            2.1 kg
Unexplained variance   5.7 kg
```

This immediately gives management something actionable.

Possible causes:

* over-portioning
* incorrect recipes
* receiving errors
* counting errors
* waste
* theft

---

# 47. Recipe Costing

Recipe cost automatically uses ingredient cost.

Example:

```text
Burger Selling Price     Rs 850
Food Cost                Rs 274
Food Cost %              32.2%
Gross Contribution       Rs 576
```

If chicken cost increases, menu profitability changes automatically.

---

# 48. Menu Engineering

Simple useful report:

```text
Item            Sales   Margin   Food Cost

Zinger          High    High     Good
Pasta           High    Low      Review
Premium Steak   Low     High     Promote
Soup            Low     Low      Review/Remove
```

No AI required.

This is basic mathematics from sales + recipes.

---

# 49. Purchasing

Do **not rebuild ERPNext Purchasing**.

Use ERPNext for:

* Supplier
* Material Request
* Purchase Order
* Purchase Receipt
* Purchase Invoice

Restaurant UI can provide simplified entry points where appropriate.

---

# 50. Supplier Cost History

Manager should easily see:

```text
Chicken / kg

Jun     620
Jul     655
Aug     710
```

and:

```text
+8.4% since last month
```

No AI required.

---

# 51. Purchase Approval

Purchases above configured limits can require manager/head-office authorization.

Example:

```text
Branch Manager Limit:
Rs 50,000

PO:
Rs 125,000

→ Head Office Approval Required
```

---

# 52. Branch Transfers

Use ERPNext stock transfer foundation.

Restaurant-friendly workflow:

```text
DHA needs Cheese
       ↓
Request
       ↓
Central Warehouse Approves
       ↓
Dispatch
       ↓
DHA Receives
```

Both dispatch and receipt must remain traceable.

---

# 53. Central Kitchen — Core but Controlled

We **will support central kitchen**, because multi-branch restaurants commonly need it and regional competitors already treat it as a serious chain capability. Petpooja supports central kitchens, multi-stage recipes and outlet supply, while Restroworks provides central-kitchen transfer, indenting and cost tracking.

But we will keep V1 sensible.

## Core Central Kitchen

* Central kitchen warehouse
* Branch requisitions
* Approval
* Production/preparation
* Batch/yield
* Dispatch
* Branch receipt
* Cost
* Stock traceability

Not initially:

* AI demand forecasting
* automated vehicle routing
* complex supply-chain optimization

---

# 54. Cashier / Till Sessions

Cash control is mandatory.

Flow:

```text
Cashier Opens Shift
        ↓
Opening Cash
        ↓
Sales
        ↓
Cash In / Cash Out
        ↓
Closing Count
        ↓
Variance
        ↓
Manager Review
```

---

# 55. Blind Cash Closing

Cashier enters actual drawer count first.

System should not reveal expected amount beforehand where configured.

After submission:

```text
Expected       Rs 84,500
Counted        Rs 82,700
Short          Rs 1,800
```

---

# 56. Cash Movements

Any cash movement outside a sale requires:

* type
* amount
* reason
* employee
* timestamp

Examples:

```text
Petty Cash
Supplier Emergency Payment
Cash Deposit
Cash Pickup
```

---

# 57. Void Controls

No transactional hard deletion.

Once an operational transaction has meaningful history:

> It does not disappear.

A void should retain:

* original transaction
* employee
* reason
* timestamp
* approval
* kitchen impact
* inventory impact
* payment impact

---

# 58. Discounts

Permissions can define:

```text
Cashier      ≤ 5%
Supervisor   ≤ 10%
Manager      ≤ 25%
```

Anything beyond authority requires approval.

---

# 59. Complimentary Items

Comp item requires reason.

Example:

```text
Customer Complaint
Manager Courtesy
Promotion
Staff Meal
```

This prevents free food silently disappearing.

---

# 60. Refunds

Every refund references:

```text
Original Payment
Original Bill
Refundable Amount
Refund Reason
Employee
Approver
```

No detached fake refund.

---

# 61. Loss Prevention — V1

We are keeping this module because most of its value comes from good transaction design rather than heavy AI.

Core controls:

* no hard-delete
* void reason
* post-KOT void tracking
* discount authority limits
* comp reason
* manager approvals
* refund linkage
* individual tills
* blind cash count
* cash variance
* blind stock count
* stock adjustment reasons
* complete audit log
* branch-level exception reporting

No machine-learning fraud engine yet.

---

# 62. Owner Exception Center

Instead of making an owner read 80 reports:

```text
TODAY — DHA

Cash Shortage             Rs 1,800
Post-Kitchen Voids             3
Large Discounts                2
Chicken Variance             6.4%
Critical Stockouts              1
Late Kitchen Tickets            8
```

Rule-based.

Simple.

Useful.

---

# 63. Staff Management

RestaurantOS staff requirements remain intentionally small.

Employee/User fields:

* Name
* User
* Employee ID
* Branch
* Role
* Active/Inactive
* POS PIN
* Assigned till
* Permission level

---

# 64. Role Model

Recommended operational roles:

### Owner / Group Admin

Everything across permitted businesses.

### Head Office Manager

Brand/branch management and consolidated reporting.

### Branch Manager

Own branch operations.

### Cashier

POS, payments and till.

### Waiter / Server

Tables and orders.

### Kitchen

KDS only.

### Storekeeper

Inventory, count, receive, transfer.

### Central Kitchen

Production and dispatch.

### Accountant

ERPNext financial modules.

The cashier does not need an ERPNext accounting dashboard.

---

# 65. Fast POS Authentication

Restaurant operations can optionally support quick staff PIN switching on registered terminals.

Example:

```text
Ali
PIN ****
```

But permissions remain server-side.

A PIN must never bypass authorization rules.

---

# 66. Accounting Architecture

Restaurant operations and accounting are separate layers.

```text
Restaurant Order
      ↓
Kitchen / Service
      ↓
Check
      ↓
Settlement
      ↓
ERPNext Invoice
      ↓
GL / Taxes / Accounts
```

A waiter changing an open order should not be editing posted accounting entries.

---

# 67. ERPNext Responsibilities

ERPNext remains authoritative for:

* General Ledger
* Accounts
* Taxes
* Sales invoices
* Purchase invoices
* Suppliers
* Physical stock ledger
* Warehouses
* Purchase orders
* Receipts
* Payments/accounting
* Cost centers
* financial statements

RestaurantOS should never create competing accounting ledgers.

---

# 68. RestaurantOS Responsibilities

Custom restaurant layer owns:

* open orders
* dining sessions
* tables
* KOT
* KDS
* modifiers
* recipes
* theoretical usage
* restaurant-specific cash controls
* restaurant operational reporting
* branch closing
* operational audit

---

# 69. Final Settlement

When a bill is successfully settled:

```text
Restaurant Check
       ↓
Settlement Validation
       ↓
ERPNext POS/Sales Invoice
       ↓
Payment Allocation
       ↓
Fiscal Integration
       ↓
Receipt
```

The bridge must be idempotent so double-clicks or network retries cannot create duplicate invoices.

---

# 70. Pakistan FBR / Electronic Invoicing

This should be a **first-class integration boundary**, not hardcoded all over POS logic.

FBR currently maintains a significant number of restaurant POS integrations, and its current electronic-invoicing guidance requires applicable registered persons to connect invoicing systems through an authorized/licensed integration route.

Architecture:

```text
Final Invoice
     ↓
Fiscal Connector
     ↓
FBR / Licensed Integrator / PRAL
     ↓
Fiscal Response
     ↓
Invoice Number / QR / Status
```

Exact implementation must follow the client's legal status and the applicable FBR/integrator requirements at deployment time.

No tax rule should be blindly hardcoded forever.

---

# 71. Branch Closing

A restaurant manager needs a simple end-of-day flow.

```text
Review Open Orders
       ↓
Review Tills
       ↓
Count Cash
       ↓
Review Variances
       ↓
Review Voids/Discounts
       ↓
Review Sales
       ↓
Close Day
```

Output:

### Daily Branch Summary

* Gross sales
* Discounts
* Net sales
* Taxes
* Cash
* Cards
* Other payments
* Refunds
* Voids
* Order count
* Average ticket
* Cash variance
* Waste
* major stock variance

---

# 72. Owner Command Center

Owner dashboard should initially remain extremely understandable.

## Today

```text
Net Sales            Rs 1,420,000
Orders                       1,126
Average Ticket           Rs 1,261
Food Cost                    31.8%
Waste                    Rs 11,400
Cash Variance             Rs 1,800
Voids                        0.7%
Discounts                    2.1%
```

---

# 73. Multi-Branch View

```text
Branch        Sales      Food Cost    Cash Var

DHA           540k         29.8%         0
Gulberg       460k         32.2%       800
Islamabad     420k         34.7%     1,000
```

Owner instantly sees which branch needs attention.

---

# 74. Core Reports

## Sales

* Sales summary
* Sales by branch
* Sales by brand
* Sales by hour
* Sales by day
* Sales by category
* Sales by menu item
* Sales by order type
* Sales by payment mode
* Sales by employee
* average ticket
* order count

## Menu

* Best sellers
* Worst sellers
* Menu item margin
* Food cost %
* Menu engineering

## Kitchen

* Orders prepared
* Average preparation time
* Late tickets
* Station performance

## Inventory

* Stock on hand
* Low stock
* Inventory movement
* Waste
* Stock adjustments
* Actual vs theoretical
* Ingredient variance
* Stock count variance
* Expiring stock where tracked

## Purchasing

* Purchase history
* Supplier spend
* Supplier price trends
* Pending PO
* Receiving differences

## Cash / Control

* Till summary
* Cash variance
* Voids
* Refunds
* Discounts
* Comps
* suspicious/high-risk exceptions

## Chain

* Consolidated sales
* Branch comparison
* brand comparison
* branch food cost
* branch wastage
* branch profitability indicators

---

# 75. UX Architecture

The entire product should **not** expose one gigantic sidebar.

## Cashier

```text
POS
Orders
Till
```

## Waiter

```text
Tables
Orders
```

## Kitchen

```text
KDS
```

## Storekeeper

```text
Stock
Count
Receive
Transfer
Waste
```

## Manager

```text
Live Branch
Orders
Kitchen
Inventory
Approvals
Closing
Reports
```

## Owner

```text
Command Center
Branches
Reports
Exceptions
```

## Accountant

```text
ERPNext Accounting
```

The software may be large internally.

The employee experience must remain tiny.

---

# 76. Product Home Screen

Instead of ERP module tiles, manager gets restaurant-relevant shortcuts:

```text
TODAY

Sales
Orders
Tables
Kitchen
Stock
Purchases
Cash
Exceptions
Reports
```

---

# 77. Multi-Chain Configuration

Head office can maintain corporate defaults.

Example:

```text
FireBurger Corporate Menu
          ↓
All FireBurger Branches
```

Allowed branch overrides can include:

* availability
* price
* local tax configuration
* local kitchen station
* branch stock

But protected corporate recipe standards can remain centrally controlled.

---

# 78. New Branch Setup

A strong feature for chains:

```text
Create New Branch
       ↓
Choose Brand
       ↓
Copy Standard Configuration
       ↓
Menu
Recipes
Roles
Kitchen Stations
Tax Defaults
       ↓
Configure Local Warehouse
       ↓
Open
```

No rebuilding a restaurant from scratch every time.

---

# 79. Brand-Level Control

Head office can filter:

```text
Whole Group
Brand A
Brand B
Specific Branch
```

Reports and permissions follow the same hierarchy.

---

# 80. Basic Delivery / Phone Order

We should support basic direct orders without becoming a logistics platform.

Fields:

* Customer
* Phone
* Address
* branch
* delivery/takeaway
* requested time
* payment mode
* notes

No advanced route optimization initially.

---

# 81. API-First Integration Design

All future channels should use the same order service.

```text
POS
Waiter
Phone
Future Website
Future QR
Future Kiosk
Future Delivery Apps
          ↓
     Order Engine
          ↓
         KDS
          ↓
      Inventory
          ↓
      Accounting
```

One order model.

Not six separate systems.

---

# 82. Reliability

Restaurants cannot stop operating because someone double-clicked a button or Wi-Fi disappeared for five seconds.

Core reliability requirements:

* request idempotency
* duplicate-payment prevention
* duplicate-invoice prevention
* transaction locks
* order version checking
* retryable integration queue
* failed-job visibility
* printer retry
* reprint logging
* recoverable POS sessions
* recoverable KDS state

---

# 83. Offline Strategy

Full sophisticated offline synchronization is a substantial project by itself.

Therefore:

### Architecture

Must be offline/retry-friendly from day one.

### Initial Production

Focus on resilient short connectivity interruptions, local operational caching where practical, reliable queues and recovery.

### Full Extended Offline Operation

Build/harden after the core workflow proves stable if Ledgix does not already provide sufficient offline capability.

We should **not promise “complete offline mode” to clients until it has been properly stress-tested.**

---

# 84. Device Management

Each POS/KDS terminal can eventually be registered to:

* client
* brand
* branch
* function
* POS profile

Example:

```text
Terminal 03
DHA
Cashier POS
```

This reduces accidental cross-branch configuration.

---

# 85. Audit

Critical actions must record:

* user
* employee
* device
* branch
* timestamp
* previous value
* new value
* reason where applicable

Critical audit areas:

* order cancellations
* voids
* refunds
* discounts
* comps
* menu prices
* recipes
* stock adjustments
* cash movements
* manager approvals
* branch closing

---

# 86. What We Reuse from Ledgix / ERPNext

We do **not** start by throwing Ledgix away.

During development we classify existing components into:

### KEEP

Stable generic ERP/accounting functionality.

### EXTEND

Existing functionality that needs restaurant fields/workflows.

### REPLACE

UI/workflows that fundamentally conflict with restaurant operation.

### REMOVE / DEPRECATE

Functionality specific to the previous business/product that has no value here.

The highest chance of major custom work is the **restaurant operational layer**, not accounting.

---

# 87. Technical Custom Domain Model

Exact DocType names can evolve during implementation, but conceptually we need:

```text
Restaurant Brand
Restaurant Branch Configuration

Menu
Menu Section
Modifier Group
Modifier Option

Restaurant Recipe
Recipe Ingredient
Recipe Revision

Restaurant Floor
Restaurant Table
Dining Session

Restaurant Order
Order Item
Restaurant Check
Settlement

Kitchen Station
Kitchen Ticket
Kitchen Ticket Item

Till Session
Cash Movement

Restaurant Consumption Ledger
Waste Event
Stock Count Session

Restaurant Approval
Restaurant Exception

Daily Branch Close

Fiscal Integration Log
External Integration Log
```

Where ERPNext already owns the correct document, we link to it rather than duplicate it.

---

# 88. Core Transaction Model

This distinction is critical:

```text
Operational Transaction
        ≠
Accounting Transaction
```

Operational layer:

```text
Restaurant Order
Dining Session
KOT
Kitchen Status
Check
```

Financial layer:

```text
Sales Invoice
Payment
GL
Tax
```

Inventory layer:

```text
Ingredient Consumption
Stock Entry
Stock Reconciliation
Purchase Receipt
```

They are connected but not collapsed into one giant document.

---

# 89. Development Phases

## Phase 0 — Ledgix Technical Audit

Before changing architecture:

* inspect current app
* inspect custom DocTypes
* inspect POS
* inspect ERPNext version
* inspect frontend
* inspect existing inventory
* inspect accounting customization
* inspect reports
* inspect permissions
* identify reusable components
* identify business-specific old logic
* create migration/refactor map

**Deliverable:** exact KEEP / EXTEND / REPLACE / REMOVE matrix.

No framework upgrade merely for the sake of upgrading.

---

## Phase 1 — Restaurant Foundation

Build:

* restaurant settings
* brand
* branch configuration
* branch/warehouse/cost-center mapping
* employee branch/role mapping
* permission model
* menu structure
* modifiers
* variants
* branch pricing
* availability

**Result:** system understands restaurant organization and menus.

---

## Phase 2 — Restaurant POS & Dining

Build:

* restaurant order engine
* counter POS
* takeaway
* basic delivery/phone
* floor
* tables
* dining sessions
* waiter assignment
* modifiers
* table transfer
* table merge
* courses
* bill/check engine
* split bills
* mixed payments
* service charges/tips

**Result:** restaurant can serve customers end-to-end.

---

## Phase 3 — Kitchen

Build:

* KOT
* delta KOT
* cancellation ticket
* kitchen routing
* kitchen stations
* KDS
* timers
* status workflow
* expo
* printers

**Result:** front-of-house and kitchen operate as one system.

---

## Phase 4 — Recipes & Inventory

Build:

* recipes
* sub-recipes
* yield
* recipe revisions
* consumption ledger
* food cost
* stock visibility
* stock counts
* waste
* theoretical usage
* actual vs theoretical
* low stock

**Result:** owner can see where food and margin are going.

---

## Phase 5 — Purchasing & Central Kitchen

Integrate/extend:

* suppliers
* purchase requests
* purchase orders
* receiving
* branch transfers
* requisitions
* central kitchen production
* dispatch/receipt
* supplier cost analysis

**Result:** restaurant supply chain becomes connected.

---

## Phase 6 — Money Control & Accounting

Build/integrate:

* till sessions
* cash movements
* blind closing
* void controls
* discount authority
* comps
* refunds
* manager approvals
* ERP invoice bridge
* settlement reconciliation
* fiscal integration architecture
* branch closing

**Result:** every rupee becomes traceable.

---

## Phase 7 — Dashboards & Management

Build:

* live branch dashboard
* owner command center
* sales reporting
* food-cost reporting
* menu engineering
* kitchen performance
* stock variance
* cash variance
* exception center
* branch comparison
* brand/group reports

**Result:** management understands the business without digging through ERP reports.

---

## Phase 8 — Production Hardening

Before commercial rollout:

* concurrency tests
* peak-order testing
* POS failure recovery
* integration retry
* printer recovery
* permission testing
* audit testing
* stock/accounting reconciliation
* security review
* backup/restore testing
* branch closure tests
* network interruption tests
* performance optimization

**Result:** product becomes something we can confidently install in a real restaurant.

---

# 90. Phase 2 Product Expansion — After Core Stability

Only after V1 is complete and stable:

```text
QR Ordering
Online Ordering Website
Self-Service Kiosk
Delivery Aggregator Connectors
Loyalty
Gift Cards
Advanced CRM
WhatsApp/SMS
Reservations
Waitlist
Advanced Employee Scheduling
Frappe HR integration
Advanced QA / Food Safety
Deeper Offline Mode
Customer Mobile App
```

These plug into the existing architecture.

They do not require rebuilding the core.

---

# 91. Future AI Layer

After enough production data:

```text
Sales Forecasting
        ↓
Prep Recommendation
        ↓
Purchase Recommendation
        ↓
Stockout Prediction
```

and:

```text
Transactions
     ↓
Anomaly Detection
     ↓
Manager Review
```

and:

```text
Owner:
"What went wrong yesterday?"

AI:
"DHA food cost increased 3.2%.
Chicken usage was 7.4 kg above theoretical.
Two large voids occurred after KOT."
```

AI interprets the system.

It does not replace the system.

---

# 92. Competitive Position

Our target is not to clone one competitor.

We take the strongest practical lessons from several categories.

### Foodics

Strong integrated restaurant operations, inventory, KDS, approvals and enterprise multi-branch capabilities.

### Toast

Excellent unified restaurant commerce approach across dine-in, takeout, delivery, inventory/menu and multi-location management.

### Square Restaurants

Strong emphasis on simple restaurant UX, floor management, kitchen routing and accessible staff workflows.

### Petpooja

Strong regional fit around recipes, inventory, central kitchens, multi-outlet operations and practical restaurant workflows.

### Restroworks

Good chain/back-office focus through recipe, supply-chain, inventory and central-kitchen capabilities.

### Restaurant365

Particularly strong benchmark for recipe costing and Actual-vs-Theoretical food-cost analysis.

### Odoo

Good benchmark for basic floor/table management, transfers/merges, restaurant ordering and preparation displays.

---

# 93. Ledgix Restaurant's Differentiation

The intended USP becomes:

## 1. One System From Order to Accounts

```text
Order
Kitchen
Inventory
Cash
Tax
Accounting
Reporting
```

No disconnected spreadsheets.

---

## 2. One Product for Any Size Restaurant

Single restaurant does not see unnecessary enterprise complexity.

A growing customer does not need to migrate systems when opening branch number two.

---

## 3. Food-Cost Control Built In

Recipes are not decorative.

They drive:

* ingredient usage
* costs
* margins
* inventory
* variance analysis

---

## 4. Strong Profit-Leakage Controls

Void, discount, refund, waste, cash and stock exceptions are visible by design.

---

## 5. ERP-Grade Financial Backbone

Restaurant staff get simple software.

Finance gets proper ERPNext accounting underneath.

---

## 6. Multi-Branch Without Complexity

Head office controls standards.

Branches operate independently within those standards.

---

## 7. Simple User Experience

Complexity is hidden based on role.

This may ultimately be the most important differentiator.

---

# 94. Client-Friendly Explanation

**Ledgix Restaurant Management & POS is a unified restaurant operating system designed for a single restaurant, growing multi-branch business or multi-brand restaurant group.**

It combines fast restaurant billing and table service with kitchen operations, recipes, inventory, purchasing, central-kitchen workflows, cash control, accounting and management reporting.

Instead of managing separate software for the POS, kitchen, stock, purchasing and accounts, Ledgix connects the complete flow:

```text
Customer Order
      ↓
Kitchen
      ↓
Ingredient Usage
      ↓
Payment
      ↓
Stock
      ↓
Accounting
      ↓
Management Reporting
```

The system remains simple for employees while giving management much stronger control over sales, stock, food cost, cash and branch performance.

---

# 95. Final Locked Product Scope

## Restaurant Operations

**YES**

* POS
* Dine-in
* Takeaway
* Basic delivery/phone
* Tables
* KOT
* KDS
* Split bills
* Mixed payments

## Menu

**YES**

* Categories
* Variants
* Modifiers
* Combos
* Multiple menus
* Branch prices
* Availability

## Kitchen

**YES**

* Stations
* KOT
* Delta KOT
* KDS
* Timers
* Courses
* Expo
* Print fallback

## Food Cost / Inventory

**YES**

* Recipes
* Sub-recipes
* Yields
* Consumption
* Counts
* Waste
* Variance
* Actual vs theoretical
* Food cost
* Menu engineering

## Procurement

**YES**

* Suppliers
* PO
* Receiving
* Transfers

primarily through ERPNext.

## Central Kitchen

**YES — sensible V1**

* Requisition
* Production
* Transfer
* Dispatch
* Receipt

## Cash & Control

**YES**

* tills
* cash count
* variance
* refunds
* voids
* discounts
* approvals
* audit

## Employees

**BASIC ONLY**

* employees
* roles
* branches
* permissions
* POS access

## Payroll / Payslip

**NOT CORE**

Optional Frappe HR later.

## CRM

**BASIC CUSTOMER RECORD ONLY**

Advanced CRM later.

## Reservation / Waitlist

**HOLD**

## Loyalty

**LATER**

## QR / Kiosk

**LATER**

## Aggregators

**LATER**

## AI

**AFTER PRODUCTION DATA**

---

# 96. Product Rule Going Forward

From this point onward, every proposed feature should pass one test:

> **Does this feature materially help a restaurant sell faster, operate better, control money/stock, or understand performance?**

If **yes**, we consider it.

If it merely sounds impressive in a sales presentation:

> **not now.**

---

# 97. Architecture Rule Going Forward

We build **modularly**, not through one massive rewrite.

```text
Ledgix Foundation
      ↓
Restaurant Core
      ↓
POS
      ↓
Kitchen
      ↓
Recipes / Inventory
      ↓
Purchasing / Central Kitchen
      ↓
Cash / Accounting
      ↓
Analytics
      ↓
Production Hardening
      ↓
Optional Extensions
      ↓
AI
```

Each completed module remains testable before the next one is layered on.

---

# 98. Final Product Definition

The final target is **not**:

> “ERPNext with a restaurant POS page.”

And it is also **not**:

> “An enormous enterprise suite containing every imaginable hospitality feature.”

The target is:

> **A focused Restaurant Management & POS platform that is easy enough for a small restaurant, powerful enough for a multi-branch operator, and architected strongly enough to grow into a multi-brand restaurant chain platform without rebuilding its core.**

That is the baseline architecture to lock.
