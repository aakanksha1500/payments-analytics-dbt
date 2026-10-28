### Business Questions

the project takes the point of view of an acquirer's data team: the company that processes card payments for merchants and pays the money out to them. The data covers the acquirer's merchants, their terminals, and every payment,refund and chargeback that goes through them, over 90 days. All timestamps are stored in UTC, and every "date" in this document means th eUTC date of the event.

THE BACKGROUND:
A card payment involves a few parties. The **cardholder** pays the  **merchant** (a shop, a restaurant) at a **terminal** (the card machine). The merchant's payment provider, called the **acquirer**, processes the payment and later pays the 

#### 1. Daily settlement amount per merchant, in EUR
(**What it means?** Settlement is the money acquirer actually pays out to a merchant. It isn't just total sales. SETTLEMENT = PAYMENTS - REFUNDS - CHARGEBACKS. Real acquirer also deduct fees, but our data has no fees, so thats out of scope.

**Why EUR** The merchants take payements in several currencies (turists pay in GBP, USD and so on), but an Irish acquirer pays merchants in EUR. So every amount has to be cpnverted first, which is why you need **fx_rates**

**Who asks it** The finance team. They pay merchants from these numbers and reconcile them against what actually left the bank. If settlement is wrong, a merchant is overpaid or underpaid, which is the most direct cost of a data bug in this whole project)

**Useed by:** Finance, to pay merchants and reconcile payouts aginst the bank.
**Definition:** payments minus refunds minus chargebacks, converted to EUR, per merchant per day. Fees are out of scope.
**Decisions:** 
- Each amount is dated by its own event: payments by **transactions_at**, refunds by **refunded_at**, chargebacks by **chargeback_at**. Money moves when each event happens, so a refund issued on 10 September reduces settlement on 10 September, not on the date of the original payment.
- **loaded_at** (whn the record arrived) is never used as a business date. It is only used for incremental loading and freshness checks. 
- FX rate: each amount uses the rate for this event date. Rates are missing on weekends, so a weekend amount uses the most recent earlier rate (an asof join, will be built in Phase 4) 
- Fees and settlement delays (real acquirers often pay out a day or two later) are out of scope. 

#### 2. Chargeback rate by merchant category
(**What it means** A chargeback happens when a cardholder disputes a payment with their own bank ("I never bought this", ""the item never arrived"). The bank forces the money back, and the merchant loses it, usually plus a fee. Unlike a refund, the merchnat didn't choose it. The card schemes (Visa, Mastercard) run monitoring programmes that track each merchant's chargeback ratio, and merchants above thier thresholds face fines or can lose the ability to take cards. So chargeback rate is one of the main numbers a risk team watches.

**Why by category** Categories have very different normal levels. Online goods and travel get more disputes than a supermarket. Comparing a merchant to its own category tells you whether it's unusual or just in a highdispute business.

**Who asks it** The risk team, to set what "normal" looks like for each category. that feeds directly into question 4.)

**Used by:** Risk, to know the normal chargeback level for each category.
**Definition:** [count or value] of chargebacks divided by [count or value] of payments, over [period].
**Decisions:** [chargeback date or original payment date]
- Chargebacks are counted by the date they were received, not the date of the original payment. This follows how card scheme monitioring works, and it means a past month's rate does not change when a late chargeback arrives.
- Count rather than vlaue as the main measure, so a single large disputed payment does not dominate a category.


### 3. Refund rate per terminal
(**What it means** A refund is the merchant choosing to give money back, for a return or a mistake. Some refunding is normal.

**Why per terminal, not per merchant** One merchant can have many terminals: different tills, different shops. A terminal with a much higher refund rate than its siblings at the same merchnat points to something local: a faulty machine, a staff member keying refunds wrongly, or staff refunding money to their own cards, which is a known type of internal fraud. Per merchant, that would be averaged away.

**Who asks it** The fraud team, and the merchant's own operations team.)

**Used by:** Fraud and merchant operations, to find terminals with unusual refunding.
**Definition:** [count or value] of refunds divided by payments, per terminal.
**Decisions:** [how refunds larger than the payment are treated]
- A refund is attributed to the terminal that issued it, not the termina; of the original payment. The point of this question is to find where refunds are being keyed.
-Refunds larger than their original payment are counted in the rate, and are also flagged separately (is_over_refund) because they should not happen and are a signal on their own.
- Payments with no terminal ID are excluded from the denominator and counted in a data-quality checks.

### 4. High-risk merchant flags
(**What it means** A list of merchants that need attention, based on rules you define. Question 2 qnd 3 are measurements; this one is a decision built on top of them.

**Possible Signals** (you choose which and set the thresholds):
- Chargeback rate well above their category's normal level.
- high refund rate.
- Sudden changes, like transaction volume jumping compared with previous weeks.

**Who asks it** The risk and compliance teams, who would review flagged merchants,a sk for documents, hold back payouts or close accounts. In Phase 8 this list gets pushed to another system)

**Used by:** Risk and compliance, to choose merchants for review.
**Definition:** a merchant is flagged if [rules and thresholds] over the last [window].
- its chargebac rate is more than twice the median for its category, and it has at least 50 approved payments (so low-volume merchnats are not flagged on one or two disputes)
- its refund rate is above 10%
- it issued at least one refund larger than the original payment.
**Decisions:** 
- The thresholds are set as dbt variables, so they can be chnaged without editing SQL.
- The thresholds are a starting point for syenthtic data, not calibrated values.

### 5. Revenue by merchant tier, at the time of the transaction
(**What it means** Merchants are put in tiers (say Standard, Silver, Gold) that typically decide their pricing and service level. Sales wants to know how much revenue each tier brings in.

**Why "at the time of the transaction".** Merchants move between tiers. If a merchant moved from Standard to Gold in September, its August revenue was Standard revenue. Using today's tier would move August's revenue into Gold, and every past report would change whenever a merchnat changed tier. This is the question that forces the SCD2 Design.

**Who asks it** The sales or commercial team, to see whether tiers are priced right and whether upgrading merchnats actually increases revenue.)

**Used by:** Sales, to see what each tier contributes.
**Definition:** [revenue definition], grouped by the tier the merchant had on the payment date.
**Decisions:** 
- An acquirer's real revenue is its fees, which this data does not have. Gross payment volume is used as the measure, and the name says so.
- Refunds and chargebacks are left out here. A net version would need each refund mapped back to the tier at hte time of the original payment, which is possible later but not needed for this question.


### Entities
Facts record events and grow every day. dimensions describe the things involved in events. FX rates fit neither: they are reference data that changes daily, used only to convert amounts.

**merchants (dimension, tracked as SCD2)**
**Grain:** one row per merchant in the source; one row per merchant version in 
column	             type	       notes
merchant_id	         string	       primary key
merchant_name	     string	       
merchant_category	 string	       for example grocery, travel, digital goods
merchant_tier	     string	       standard, silver, gold; changes over time
country_code	     string	
onboarded_at	     timestamp	
updated_at	         timestamp	   when the row last changed; used by the snapshot

**terminals (dimension)**
**Grain:** one row per terminal
column	        type	  notes
terminal_id	    string	  primary key
merchant_id	    string	  foreign key to merchants
terminal_type	string	  for example countertop, mobile, online
activated_at	timestamp	

**Assumption:** a terminal belongs to one merchant for its whole life.

**transactions (fact)**
**Grain:** one row per payment attempt
column	            type	    notes
transaction_id	    string	    primary key; about 0.5% duplicated in raw data
merchant_id	string	foreign     key to merchants
terminal_id	string	foreign     key to terminals; can be null in raw data
transaction_at	    timestamp	when the payment happened
loaded_at	        timestamp	when the record arrived; can be 1 to 3 days later
amount	            decimal	    in the original currency
currency_code	    string	    foreign key to the currencies seed
status	            string	    approved or declined
card_scheme	        string	    visa or mastercard

Only approved payments count towards settlement, revenue and rates.

**refunds (fact)**
**Grain:** one row per refund
column	        type	    notes
refund_id	    string	    primary key
transaction_id	string	    the original payment
terminal_id	    string	    the terminal that issued the refund
refunded_at	    timestamp	
loaded_at	    timestamp	
amount	        decimal	    in the original payment's currency
currency_code	string	
refund_reason	string


**chargebacks (fact)**
**Grain:** one row per chargeback
column	        type	    notes
chargeback_id	string	    primary key
transaction_id	string	    the disputed payment
chargeback_at	timestamp	when the chargeback was received
loaded_at	    timestamp	
amount	        decimal	
currency_code	string	
reason_code	    string	    for example fraud, not received, not as described

Dispute outcomes (merchant wins or lose) are out of scope

**fx_rates (reference)**
**Grain**: one row per currency per business day.
column	        type	  notes
rate_date	    date	  weekdays only
currency_code	string	
rate_to_eur	    decimal	  amount_eur = amount * rate_to_eur

EUR has no rows; EUR amounts are used as they are.

**currencies (seed)**
**GRain:** one row per currency. Actually built: (seeds/currencies.csv)


### Relationships and ERD
- A merchant has many terminals. A terminal belongs to one merchant
- A merchant has many transactions
- A transaction is made on zero or one terminal (zero only for the planted bad rows)
- A transaction can have zero or many refunds (partial refunds are allowed)
- A transaction can have zero or one chargeback
- A terminal can issue many refunds.
- FX rates join to amounts on currency and date. This is a lookup, not a foreign key.

**Planned models and their grain**
model	                 grain	                                answers
dim_merchant	         one row per merchant version (SCD2)	2, 4, 5
dim_date	             one row per calendar day	            all
fct_transactions	     one row per approved or declined payment, with the EUR amount and the merchant version valid at payment time	                                              2, 3, 5
fct_daily_settlement	 one row per merchant per day	        1
merchant_risk_flags	     one row per merchant	                4

### Design Questions

#### Why does question 5 need an SCD2 dimension?
A plain **dim_merchant** keeps one row per merchant with its current tier. If a merchant moves from standard to gold in September, joining its August payments to that table lables them as gold revenue. Every historical report would change whenever a merchant changes tier, and nobody could reproduce last month's numbers. 
An SCD2 dimension keeps a row for every version of the merchant, with **valid_from**, **valid_to** and **is_current**. Each payment joins to the version where **valid_from <= transaction_at < valid_to**, so August payments stay standard.
The cost: the merchant table is no longer one row per merchant, so a careless join on **merchant_id** alone duplicates rows. Every join to **dim_merchant** must either use the date range or filter on **is_current**. It also needs a snapshot process to capture changes, and it can only record changes it sees: if a merchant changes tier twice between two snapshot runs, the middle version is lost.

#### Refunds: separate fact table or negative rows in transactions?
**Option A: A negative rows in transactions.** sum(amount) gives net volume directly, and there is one table to load. But refunds have columns, payments do not (the original transaction_id, a reason), which would be null on every payment row. the grain becomes "one row per payment or refund", so every count of payments needs a filter, and forgetting it inflates the denominator of the refund rate. Checks like "refund larger than the original payment" need a self-join on the same table.
**Option B: a separate refunds fact.** Each table has one clear grain and only the columns it needs. Refunds can arrive late, be matched to their original payment and be tested on theor own. The cost is that net figures need the facts combined: settlement has to aggregate payments, refunds and chargebacks to merchnat and day separately, then join the three results. Joining the raw facts first would repeat payment rows for every refund and double count them.

**Chosen: Option B.** The refund and charge back question depend oon treating them as separate events with their own dates and terminals, and the aggregate-then-join pattern for settlement is a known cost that is easy to test (Phase 6  reconciles settlements against the three facts).

Out of scope
- Fees, interchange and acquirer revenue.
- Settlement delays (payouts are modelled on the event date).
- Chargeback dispute outcomes.
- Terminals moving between merchants.