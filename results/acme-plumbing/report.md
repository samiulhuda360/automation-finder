# Where Acme Plumbing loses time

Based on 4,982 records from 2026-06-01 to 2026-08-24 (2.8 months): 3953 activity log entries, 898 email records, 84 helpdesk tickets, 47 calendar entries.

- **10** repeated tasks found
- **47 hours a month** spent on the top 5
- **32 hours a month** that automation could give back

> These hours are estimates: how often it happens (counted from your records) times minutes per task
> (an assumption you can change). The minutes used are listed with each item.

## The top 5 opportunities

### 1. Automated Invoice Generation on Job Completion

**About 29 h a month now, saves about 17.5 h a month** | moderate to set up | medium risk

**What happens today:** First one of 8 people (Ben, Ryan and others) does 'complete job in jobs'; then Emma does 'create invoice in accounts'. This happens about 292 times a month.

**What starts it:** A field worker marks a job as complete in the jobs system.

**Steps the automation takes:**
1. Detect when a job status changes to complete in the jobs system.
2. Extract job details, customer information, and line items from the completed job.
3. Draft a new invoice in the accounts system using the extracted details.
4. Send the drafted invoice to Emma for review and approval.

**Where AI helps:** Extracts job details and line items to automatically draft the correct invoice in the accounts system.

**Where a person still decides:** Emma must review and approve the draft invoice in the accounts system before it is sent to the customer.

**Why this risk level:** Incorrect invoice amounts or details could lead to billing errors and customer dissatisfaction.

**How the hours were worked out:** 292 times a month x 6 minutes = 29.1 hours; an automation like this usually removes about 60% of that work.

### 2. Daily Customer Reminder Calls

**About 10 h a month now, saves about 8.1 h a month** | easy to set up | low risk

**What happens today:** Claire does the same routine every working day around 16:00: “reminder call (phone)”. That is about 153 tasks a month.

**What starts it:** Triggers every working day at 16:00 to prepare daily reminder calls.

**Steps the automation takes:**
1. Generate the list of customers who need a reminder call for the next working day
2. Draft a friendly reminder script for each customer
3. Queue the call list and notes for review

**Where AI helps:** Summarize customer booking details and draft personalized reminder notes.

**Where a person still decides:** Claire reviews the call list and approved reminder notes before dialing.

**Why this risk level:** Mistakes only result in an incorrect reminder call time, which can be quickly corrected over the phone.

**How the hours were worked out:** 153 times a month x 4 minutes = 10.2 hours; an automation like this usually removes about 80% of that work.

### 3. Automate CRM Lead Creation from Quote Request Emails

**About 3 h a month now, saves about 2.3 h a month** | easy to set up | low risk

**What happens today:** Claire receives an email like “New quote request: Shower mixer replacement - Mangere Bridge” and then types it into crm (create lead) by hand, about 35 times a month.

**What starts it:** A new quote request email is received from a potential customer.

**Steps the automation takes:**
1. Receive the incoming quote request email.
2. Extract the customer details, job description, and location using AI.
3. Check if a lead already exists in the CRM system.
4. Create a new lead in the CRM with the extracted information.

**Where AI helps:** Extracts relevant customer and job details from the email text to format them correctly for the CRM.

**Where a person still decides:** nothing to approve; the person gets a summary

**Why this risk level:** If the automation makes a mistake, an incorrect lead is created in the CRM which can be easily edited or deleted by Claire.

**How the hours were worked out:** 35 times a month x 5 minutes = 2.9 hours; an automation like this usually removes about 80% of that work.

### 4. Automate Supplier Bill Entry from Invoices

**About 2 h a month now, saves about 1.9 h a month** | easy to set up | medium risk

**What happens today:** Emma receives an email like “DrainPro invoice [ref] - payment due in [n] days” and then types it into accounts (enter supplier bill) by hand, about 28 times a month.

**What starts it:** An email is received with a subject line indicating a new supplier invoice and payment due date.

**Steps the automation takes:**
1. Receive the supplier invoice email from DrainPro.
2. Extract the invoice reference number, amount, and payment due date.
3. Draft a new supplier bill in the accounts system with the extracted details.
4. Flag the draft bill for human review before final entry.

**Where AI helps:** Extracting the reference number, due date, and amount from the incoming invoice email.

**Where a person still decides:** Emma reviews and approves the draft supplier bill in the accounts system before it is saved.

**Why this risk level:** Incorrect bill details entered into accounts could lead to overpayment or accounting errors.

**How the hours were worked out:** 28 times a month x 5 minutes = 2.3 hours; an automation like this usually removes about 80% of that work.

### 5. Monthly KPI Report Automation

**About 2 h a month now, saves about 1.8 h a month** | easy to set up | low risk

**What happens today:** Sarah does the same routine on the first working day of each month around 09:00: “Monthly KPI report”, “export job report (jobs)”, “update kpi spreadsheet (spreadsheet)”. That is once a month.

**What starts it:** Triggered on the first working day of each month at 09:00.

**Steps the automation takes:**
1. Export the latest job report from the jobs system
2. Calculate the key performance indicators from the exported data
3. Update the monthly KPI spreadsheet with the new figures
4. Send the final KPI report via email to management

**Where AI helps:** AI calculates key metrics and summarizes the job report data before updating the spreadsheet.

**Where a person still decides:** Review and approve the updated KPI spreadsheet and email before it is sent to management.

**Why this risk level:** Mistakes in internal KPI reporting are easily corrected and do not directly impact customers or finances.

**How the hours were worked out:** 1 times a month x 120 minutes = 2.2 hours; an automation like this usually removes about 80% of that work.

## Other repeated work we found

| What | Who | Times a month | Hours a month |
|---|---|---:|---:|
| James does the same routine every Friday around 13:30: “check timesheet status (payroll)”, “Timesheet reminder - week ending [date]”, “Please submit your timesheet for [date] [date]”. That is about 23 tasks a month. | James | 23 | 1.6 |
| First one of 8 people (Tom, Jack and others) emails “PO request [ref]: toilet suite”; then James emails “PO request [ref]: toilet suite - approval needed ([amount])”; then Sarah emails “PO request [ref]: toilet suite - approved”; then James does 'create purchase order in accounts'. This happens about 12 times a month. | James, Sarah | 12 | 2.4 |
| Claire receives a helpdesk ticket like “Move my plumbing appointment” and then types it into jobs (reschedule booking) by hand, about 12 times a month. | Claire | 12 | 1.0 |
| Claire answers the same kind of request again and again, such as “Availability next week”: about 4 a month, worded differently each time. | Claire | 4 | 0.4 |
| Claire answers the same kind of request again and again, such as “Thanks for the quick visit”: about 2 a month, worded differently each time. | Claire | 2 | 0.2 |
