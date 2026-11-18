# Running Question List

Every question I find myself asking about my weekly decision: **which schools, libraries, and districts to
reach out to about IT work.** This includes questions the data can't answer yet. In Milestone 3 this list
becomes my golden-question set, the questions the system must answer correctly.

Add a row whenever a new question comes up, with the date. Don't delete questions; mark them answered instead.

## Questions the database can answer now

| Added | Question | Answered by | Notes |
|---|---|---|---|
| 2026-11-11 | Which Form 470s are still open for bidding, and how many days are left on each? | `db/queries.sql` Q1 | Depends on today's date; re-run before every outreach session |
| 2026-11-11 | What Category 2 equipment is requested most, and is demand rising or falling between years? | `db/queries.sql` Q2 | Counts applications, not API rows |
| 2026-11-11 | How many applications go through an E-Rate consultant, and which consultants file the most? | `db/queries.sql` Q3 | Consultant name is parsed from a packed text field |
| 2026-11-11 | In which months are Form 470s certified, so I know when to watch for new bids? | `db/queries.sql` Q4 | Only FY2026 has a complete season so far |
| 2026-11-11 | Which applicants near Alva filed in the last 12 months, and what did they ask for? | `db/queries.sql` Q5 | "Near Alva" is a hand-made town list, not a real distance (see below) |
| 2026-11-11 | Which applicants filed in both funding years (repeat E-Rate users)? | Not written yet | Group applications by applicant and count funding years |
| 2026-11-11 | Which requests name "No Preference" for manufacturer, so a brand-neutral bid is welcome? | Not written yet | `manufacturer` is always empty on Category 1 lines |
| 2026-11-11 | Which applicants filed without a consultant, so I can reach the school directly? | Not written yet | `consulting_firm_data` is missing for these |

## Questions the data can't answer yet

| Added | Question | Why not | What might answer it |
|---|---|---|---|
| 2026-11-11 | Which applicants are actually within about an hour's drive of Alva? | The data has city, state, and ZIP, but no coordinates or drive times | Geocode addresses or ZIP codes and compute distance or drive time from Alva |
| 2026-11-11 | What equipment does an applicant already have installed? | A Form 470 lists what they want to buy, not what they own | Ask the applicant; the RFP documents sometimes describe the current setup |
| 2026-11-11 | How many users, students, or buildings does an applicant support? | Only `number_of_eligible_entities` is in the data, which counts sites, not people | Other USAC datasets or state education data, still to be explored |
| 2026-11-11 | How well does a district use its E-Rate funds, and how much Category 2 budget does it have left? | Form 470 shows requests, not money awarded or spent | Other USAC E-Rate datasets (funding requests and commitments), still to be explored |
| 2026-11-11 | Who won the bid on an application, and at what price? | Form 470 is the request for bids; the award comes later | Other USAC E-Rate datasets on funded services, still to be explored |
| 2026-11-11 | Does an applicant have its own IT staff, or does it already work with an MSP? | Not in any field | Outreach, or the RFP documents |
| 2026-11-11 | Which non-school prospects nearby need IT support (funeral homes, churches, clinics, law offices, farms)? | E-Rate covers only schools and libraries | A separate data source for other sectors |
