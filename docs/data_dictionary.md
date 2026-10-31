# Data Dictionary: E-Rate FCC Form 470

<!-- Facts below were checked against a real pull on 2026-10-31: run 20261031T194518Z,
     filter billed_entity_state in('OK','KS') AND funding_year in('2027'), 1,457 rows. -->

## Source

| | |
|---|---|
| **Dataset** | E-Rate FCC Form 470 Tool Data (USAC Open Data), dataset ID `jt8s-3q52` |
| **Publisher** | Universal Service Administrative Company (USAC), the administrator of the FCC's E-Rate program |
| **Base URL** | `https://opendata.usac.org/resource/jt8s-3q52.json` (Socrata SODA 2.1) |
| **Endpoints used** | The one endpoint above, called two ways: (1) row query with `$where`, `$order=:id`, `$limit`, `$offset`; (2) grouped query with `$select … count(*)`, `$group=billed_entity_number, …` to build the applicant list |
| **Documentation** | Dataset page: https://opendata.usac.org/d/jt8s-3q52 · API docs: https://dev.socrata.com/foundry/opendata.usac.org/jt8s-3q52 · App tokens: https://dev.socrata.com/docs/app-tokens |
| **License / terms** | Dataset metadata lists the license as **Public Domain**, attribution "Universal Service Administrative Company (USAC)". USAC's general online-services terms: https://forms.universalservice.org/portal/terms |
| **Authentication** | None required for this public dataset on SODA 2.1. We send a Socrata **app token** in the `X-App-Token` header (read from `SOCRATA_APP_TOKEN` in `.env`) to get our own rate-limit pool. |

## What one record means

**Background:** A school, library, or consortium that wants E-Rate discounts must post an FCC Form 470 to open competitive bidding. Service providers (like an MSP) read the 470 and its RFP documents and submit bids. Contracts can't be signed before the `allowable_contract_date` (28 days after certification).

- **Service-request row (main resource, `data/raw/<run>/service_requests/`):** One row is **one requested service or item (a service request line) on one version of one Form 470, repeated once for each RFP document attached to that request.** For example, an application asking for switches, with three RFP attachments, appears as three rows that differ only in `rfp_documents`.
- **Applicant row (related resource, `data/raw/<run>/applicants/`):** One row is **one billed entity (a school, school district, library, library system, or consortium) that filed at least one Form 470 in our filter**, with a count of its service-request rows and its most recent modification date. It's built by our grouped query, not stored separately by USAC.
- **Application (implied):** One `application_number` is one Form 470 filing. It isn't a separate download; in Week 2 it becomes its own table.

## Fields

"Missing" counts are out of 1,457 rows in our OK + KS, 2027 pull. Socrata **leaves a field out of the JSON entirely** when it's empty, so "missing" means the key doesn't exist in that record.

| Field | Type (API) | Example | Meaning | Can be missing? |
|---|---|---|---|---|
| `application_number` | text | `"270000265"` | Form 470 application number. Same value on every row of that filing. | No (0) |
| `form_version` | text | `"Current"` | `Original` = as certified by the applicant; `Current` = as later processed by USAC. | No (0) |
| `funding_year` | text | `"2027"` | E-Rate funding year the services are for (July 2027–June 2028). | No (0) |
| `fcc_form_470_status` | text | `"Certified"` | Filing status. Seen: `Certified` (1,453), `Canceled` (4). | No (0) |
| `certified_date_time` | date-time (ISO, no time zone; USAC says Eastern) | `"2026-08-05T17:12:25.000"` | When the applicant certified the form. | No (0) |
| `allowable_contract_date` | date | `"2026-09-02T00:00:00.000"` | Earliest date a contract may be signed (certification + 28 days). This is the bidding deadline that matters to a vendor. | No (0) |
| `last_modified_date_time` | date-time | `"2026-10-30T18:23:58.000"` | Last time the record changed. Our "what's new" field. | No (0) |
| `billed_entity_number` | text | `"16037392"` | BEN: USAC's ID for the applicant. Links rows to applicants. | No (0) |
| `billed_entity_name` | text | `"KIPP TULSA ACADEMY"` | Applicant name (usually upper case). | No (0) |
| `applicant_type` | text | `"School District"` | School District (1,409), Library (22), School (14), Consortium (7), Library System (5). | No (0) |
| `billed_entity_city` / `billed_entity_state` / `billed_entity_zip` | text | `"TULSA"` / `"OK"` / `"74106"` | Applicant location. ZIP is always 5 digits; the +4 is in `billed_entity_zip_ext`. | No (0) |
| `contact_name` / `contact_email` / `contact_phone` | text | (a staff member's name, email, phone) | The person bidders should contact first. **Personal data.** | No (0) |
| `consulting_firm_data` | text (packed) | `"{CRW Consulting\|16024800\|918-445-0048\|…}"` | E-Rate consultant: `{name\|consultant registration number\|phone\|email}` packed into one string. | Yes (20) |
| `service_request_id` | text | `"1"` | Line number of the request within the application (1, 2, 3 …). Only unique *within* an application. | Yes (4, canceled forms) |
| `service_category` | text | `"Category 2"` | Category 1 = internet/data transmission (168); Category 2 = internal connections such as switches, Wi-Fi, cabling (1,285). | Yes (4) |
| `service_type` | text | `"Internal Connections"` | Internal Connections (801), Basic Maintenance of Internal Connections (355), Data Transmission and/or Internet Access (168), Managed Internal Broadband Services (129). | Yes (4) |
| `function` | text | `"Switches"` | What's requested, e.g. switches, cabling, wireless access points, UPS. | Yes (4) |
| `quantity` / `unit` | text / text | `"3"` / `"Each"` | How many and in what unit (`Each`, `Feet`, `Fiber Strands`). Quantity is a **string**, not a number. | Yes (140) |
| `manufacturer` | text | `"Extreme Networks"` | Preferred manufacturer; often `"No Preference"`. Free text continues in `other_manufacturer`. | Yes (301) |
| `rfp_documents` | url (object) | `{"url": "https://publicdata.usac.org/…/Attachment C.docx"}` | One RFP attachment. The value is a JSON object with a `url` key, not a plain string. | Yes (42) |
| `service_request_rfp_attachment` | number (sent as text) | `"3"` | **Count** of RFP attachments on this service request (not an index). | Yes (4) |

## Identifiers and relationships

- **Applicant:** `billed_entity_number` (BEN) uniquely identifies an applicant. In our pull every row's BEN matched exactly one applicant row (0 orphans), and every application belonged to exactly one BEN.
- **Application:** `application_number` uniquely identifies a Form 470 filing (129 in our pull).
- **Service request:** `service_request_id` is only a line number, so the service request key is **(`application_number`, `form_version`, `service_request_id`)**.
- **Service-request row:** No single field is unique. In our pull, **(`application_number`, `form_version`, `service_request_id`, `rfp_documents.url`)** was unique across all 1,457 rows. We'll re-test this on larger pulls before relying on it as a primary key.
- **Relationships:**
  `applicant (BEN)` 1 ── many `application` 1 ── many `service request` 1 ── many `RFP document`
  An application can also name one consultant (`consulting_firm_data`) and has one contact person.

## Update behavior

- **New data:** New 470s are certified continuously. In our pull, certification dates ran from 2026-08-05 to 2026-10-30, the day before the pull. The FY2027 filing window is just starting, so the row count will grow for months.
- **Old records change:** Yes. Forms are amended by USAC (`form_version = Current`), canceled (`fcc_form_470_status = Canceled`), and get new RFP uploads (`rfp_upload_date` as late as 2026-10-30). `last_modified_date_time` moves when that happens.
- **Detecting "what's new since last time":** Save the largest `last_modified_date_time` from each sync, then ask only for rows where `last_modified_date_time > '<saved value>'`. Because old records can change, a sync must **update** existing rows by key, not just insert. Rows can also disappear (for example, a canceled form losing its service requests), so a periodic full refresh may still be needed.
- **Publisher refresh rate:** The dataset metadata doesn't state a schedule. The most recent records were one day old when we pulled, which suggests at least daily refresh; we'll confirm this during Week 3 syncs.

## Surprises


1. One surpring issue we've found is that one row in the dataset is not exactly one request, or one application, or one applicant. We have 1,457 rows, but only 129 applications and 119 applicants. We have found that rows multiply because each service requests repeats for every RFP attachment. I am not entirely sure what an RFP attachment is at this time, but will continue to investigate as we complete this project. One single application alone has 98 rows because of these additional RFP attachments.

2. Another is that empty fields are dropped, not set to null. We have 4 canceled forms and they have no service_type keys at all. We've also found that code that reads 'record["service_type"]' crashes, and must use '.get()'

3. Contact details are complete, but packed into a single string. Another interesting field is the 'authorized_person_employer' field, although in the data it equals 'authorized_person_name' so I'm not entirely sure if that's an error at this point or not. I will continue to investigate.

4. Numbers arrive as text strings and not numbers.

5. Altered entries have multiple states, Original and Current, we thought we would need to filter all results as Current, but after looking at the data we saw that only 37 versions are Current, while 90 versions are Original. We will need to continue to search for both.


## Data-use ethics check

**What do the API's terms of service allow and forbid (storage, display, commercial use, attribution)?**
This data is open and accessible to the general public, but requires proper attribution os the source of the data. It is incredibly unfortunate that socrata.com/terms-of-service/ is currently down, making this information much more difficult to find. We were able to find a lot of relevant information on opendata.usac.org.

**Does this data describe real, identifiable people? If so, did they expect it to be used this way?**
Yes, this data does describe real people, schools, staff, technical contacts, etc. This was also their intention in supplying their data, for the purpose of connecting with an appropriate vendor or contractor. This is a notable ethics concern and special consideration may be taken into account with how we handle these data points.

**What is the worst realistic harm if your stored copy leaked or were misread?**
Contact lists or real names could be leaked, spammed or phished. Misreading could lead to missed deadlines, or missed bidding opportunities entirely. Schools may be contacted about bidding contracts that have expired, etc.

**Who should be allowed to read or change these records in your system?**
The job that handles the initial sync should be the only entity writing data I think. Any interaction by the user should only need to be read only, and no one is able to edit the USAC data.

