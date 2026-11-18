-- db/schema.sql: E-Rate Form 470 lead database (Milestone 2).
--
-- Four tables, parent to child:
--   applicants  1 ── many  applications  1 ── many  service_requests  1 ── many  rfp_documents
--
-- Source: USAC Open Data, E-Rate FCC Form 470 (dataset jt8s-3q52). See docs/data_dictionary.md.
-- Every table keeps the source's natural ID under a UNIQUE constraint and uses an identity
-- column we generate as its primary key. Week 3 adds sync_runs; Week 6 adds agent tables.
--
-- Run once against an empty database (Supabase SQL editor, or psql "$DATABASE_URL" -f db/schema.sql).

-- ---------------------------------------------------------------------------
-- applicants: one billed entity (school district, school, library, library system, consortium)
-- ---------------------------------------------------------------------------
create table applicants (
    applicant_id          bigint generated always as identity primary key,
    billed_entity_number  text not null unique                 -- USAC's BEN, the natural ID
        check (billed_entity_number ~ '^[0-9]+$'),
    name                  text not null,
    applicant_type        text not null
        check (applicant_type in ('School District', 'School', 'Library', 'Library System', 'Consortium')),
    address_1             text,
    city                  text not null,
    state                 text not null check (state ~ '^[A-Z]{2}$'),
    zip                   text not null check (zip ~ '^[0-9]{5}$'),   -- always 5 digits in the source
    phone                 text,
    first_seen_at         timestamptz not null default now(),
    last_updated_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- applications: one Form 470 filing. When USAC has both an Original and a Current
-- version of a form, we keep one row: Current if it exists, otherwise Original.
-- form_version records which one we kept.
-- ---------------------------------------------------------------------------
create table applications (
    application_id               bigint generated always as identity primary key,
    application_number           text not null unique           -- natural ID of the filing
        check (application_number ~ '^[0-9]+$'),
    applicant_id                 bigint not null references applicants (applicant_id),
    form_version                 text not null check (form_version in ('Original', 'Current')),
    form_nickname                text,
    funding_year                 integer not null check (funding_year between 2016 and 2100),
    status                       text not null check (status in ('Certified', 'Canceled')),
    -- The source sends these without a time zone; USAC times are US Eastern, and load.py converts them.
    certified_at                 timestamptz not null,
    last_modified_at             timestamptz not null,
    -- The bidding deadline. Stored exactly as USAC sends it, never computed (data_quality.md, Finding 5),
    -- but it can never come earlier than the 28-day minimum after certification.
    allowable_contract_date      date not null,
    number_of_eligible_entities  integer not null check (number_of_eligible_entities >= 0),
    -- Contact for bidders. Personal data: read only through limited roles later.
    contact_name                 text not null,
    contact_email                text not null check (contact_email like '%_@_%'),
    contact_phone                text not null,
    -- Packed as {name|registration number|phone|email}; missing when filed without a consultant.
    consulting_firm_data         text,
    category_one_description     text,
    category_two_description     text,
    first_seen_at                timestamptz not null default now(),
    last_updated_at              timestamptz not null default now(),
    check (allowable_contract_date >= (certified_at at time zone 'America/New_York')::date + 28),
    check (last_modified_at >= certified_at)
);

-- ---------------------------------------------------------------------------
-- service_requests: one requested line item on one application (e.g. 3 switches).
-- The API's service_request_id is only a line number within an application, so it is
-- stored as usac_line_number and is unique together with the application.
-- Canceled forms have no service requests.
-- ---------------------------------------------------------------------------
create table service_requests (
    service_request_id    bigint generated always as identity primary key,
    application_id        bigint not null references applications (application_id) on delete cascade,
    usac_line_number      integer not null check (usac_line_number > 0),  -- USAC's "service_request_id"
    service_category      text not null check (service_category in ('Category 1', 'Category 2')),
    service_type          text not null
        check (service_type in (
            'Data Transmission and/or Internet Access',
            'Internal Connections',
            'Basic Maintenance of Internal Connections',
            'Managed Internal Broadband Services'
        )),
    function              text not null,
    quantity              integer check (quantity >= 0),        -- arrives as text; load.py converts it
    unit                  text,
    manufacturer          text,                                 -- always empty on Category 1 lines
    other_manufacturer    text,
    minimum_capacity      text,                                 -- e.g. '50.00 Mbps' (Category 1 only)
    maximum_capacity      text,
    installation_initial  boolean,
    rfp_attachment_count  integer not null default 0 check (rfp_attachment_count >= 0),
    first_seen_at         timestamptz not null default now(),
    last_updated_at       timestamptz not null default now(),
    unique (application_id, usac_line_number),
    -- A quantity always has a unit. (A unit without a quantity does occur: 4 FY2026 requests
    -- give a unit such as 'Feet' and leave the amount blank.)
    constraint quantity_has_unit check (quantity is null or unit is not null)
);

-- ---------------------------------------------------------------------------
-- rfp_documents: one RFP attachment on one service request. Splitting these out
-- removes the row multiplication in the API data (one API row per attachment).
-- ---------------------------------------------------------------------------
create table rfp_documents (
    rfp_document_id     bigint generated always as identity primary key,
    service_request_id  bigint not null references service_requests (service_request_id) on delete cascade,
    url                 text not null check (url like 'https://%'),
    uploaded_at         timestamptz,
    first_seen_at       timestamptz not null default now(),
    last_updated_at     timestamptz not null default now(),
    unique (service_request_id, url)
);

-- Indexes for the joins and time filters the business queries use.
create index applications_applicant_id_idx on applications (applicant_id);
create index applications_allowable_contract_date_idx on applications (allowable_contract_date);
create index service_requests_application_id_idx on service_requests (application_id);
create index rfp_documents_service_request_id_idx on rfp_documents (service_request_id);
