# Database Schema (Milestone 2)

The database holds E-Rate FCC Form 470 filings from USAC Open Data (dataset `jt8s-3q52`) for
Oklahoma and Kansas, funding years 2026 and 2027. The SQL lives in [`db/schema.sql`](../db/schema.sql).

## Entity-relationship diagram

```mermaid
erDiagram
    applicants ||--o{ applications : "files"
    applications ||--o{ service_requests : "requests"
    service_requests ||--o{ rfp_documents : "has attachment"

    applicants {
        bigint applicant_id PK
        text billed_entity_number UK "USAC BEN"
        text name
        text applicant_type "5 allowed values"
        text address_1
        text city
        text state "2 letters"
        text zip "5 digits"
        text phone
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    applications {
        bigint application_id PK
        text application_number UK "Form 470 number"
        bigint applicant_id FK
        text form_version "Original or Current"
        text form_nickname
        integer funding_year
        text status "Certified or Canceled"
        timestamptz certified_at
        timestamptz last_modified_at
        date allowable_contract_date "bidding deadline"
        integer number_of_eligible_entities
        text contact_name
        text contact_email
        text contact_phone
        text consulting_firm_data
        text category_one_description
        text category_two_description
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    service_requests {
        bigint service_request_id PK
        bigint application_id FK
        integer usac_line_number "USAC service_request_id"
        text service_category "Category 1 or 2"
        text service_type "4 allowed values"
        text function
        integer quantity
        text unit
        text manufacturer
        text other_manufacturer
        text minimum_capacity
        text maximum_capacity
        boolean installation_initial
        integer rfp_attachment_count
        timestamptz first_seen_at
        timestamptz last_updated_at
    }

    rfp_documents {
        bigint rfp_document_id PK
        bigint service_request_id FK
        text url
        timestamptz uploaded_at
        timestamptz first_seen_at
        timestamptz last_updated_at
    }
```

## What one row means

**`applicants`:** One row is one billed entity: a school district, school, library, library system,
or consortium that filed at least one Form 470 in our data. USAC's billed entity number (BEN) is the
natural ID and is unique.

**`applications`:** One row is one Form 470 filing, the public notice that an applicant is seeking bids.
It holds the dates that matter to a vendor (certification and the allowable contract date, which is the
earliest a contract can be signed) and the contact person bidders should reach.

**`service_requests`:** One row is one item or service requested on an application, such as 3 switches
or internet access at one location. Its natural key is the application plus USAC's line number, which
USAC calls `service_request_id` and which only counts 1, 2, 3 within each application.

**`rfp_documents`:** One row is one RFP attachment (a document describing the bid specifications) on one
service request.

## Relationships

- An **applicant** files one or more **applications**. Every application belongs to exactly one applicant.
- An **application** lists zero or more **service requests**. Canceled forms have none.
- A **service request** has zero or more **RFP documents**.

## Design decision: one row per application, preferring the Current version

Form 470 issues two versions of an application. Original, as the author submitted it, or Current,
as it exists after changes have been made to the document. We found it only necessary to include
one version of the application, Current, when it exists, otherwise Original.

This also helps with filtering as in previous versions, filtering by Current
version greatly reduced results because most results were Original.

## A second decision: splitting out RFP documents

The API sends one row per service request per RFP attachment, so one application appeared as 98 rows.
Giving attachments their own table means a service request is stored once, and counting requests or
applications never gets inflated by large numbers of RFP documents.

