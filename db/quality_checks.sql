-- db/quality_checks.sql: the measurements behind docs/data_quality.md (Milestone 3, Part E).
--
-- Run them all with:  python scripts/run_quality_checks.py
-- Each check starts with a "-- name:" line. The script runs them as app_reader and prints
-- every result with today's date, ready to paste into docs/data_quality.md.

-- name: 1. Row counts per table
select 'applicants' as table_name, count(*) as row_count from applicants
union all select 'applications', count(*) from applications
union all select 'service_requests', count(*) from service_requests
union all select 'rfp_documents', count(*) from rfp_documents
union all select 'sync_runs', count(*) from sync_runs;

-- name: 2a. Null rates: applications
select count(*) as applications,
       round(100.0 * count(*) filter (where consulting_firm_data is null) / count(*), 1) as pct_no_consultant,
       round(100.0 * count(*) filter (where form_nickname is null) / count(*), 1) as pct_no_nickname,
       round(100.0 * count(*) filter (where category_one_description is null) / count(*), 1) as pct_no_cat1_description,
       round(100.0 * count(*) filter (where category_two_description is null) / count(*), 1) as pct_no_cat2_description
from applications;

-- name: 2b. Null rates: applicants
select count(*) as applicants,
       round(100.0 * count(*) filter (where address_1 is null) / count(*), 1) as pct_no_address,
       round(100.0 * count(*) filter (where phone is null) / count(*), 1) as pct_no_phone
from applicants;

-- name: 2c. Null rates: service requests, by category
select service_category, count(*) as service_requests,
       round(100.0 * count(*) filter (where quantity is null) / count(*), 1) as pct_no_quantity,
       round(100.0 * count(*) filter (where unit is null) / count(*), 1) as pct_no_unit,
       round(100.0 * count(*) filter (where manufacturer is null) / count(*), 1) as pct_no_manufacturer,
       round(100.0 * count(*) filter (where minimum_capacity is null) / count(*), 1) as pct_no_min_capacity
from service_requests
group by service_category order by service_category;

-- name: 3a. Duplicates by natural ID (UNIQUE constraints should make every count 0)
select 'applicants' as table_name, count(*) - count(distinct billed_entity_number) as duplicates from applicants
union all select 'applications', count(*) - count(distinct application_number) from applications
union all select 'service_requests', count(*) - count(distinct (application_id, usac_line_number)) from service_requests
union all select 'rfp_documents', count(*) - count(distinct (service_request_id, url)) from rfp_documents;

-- name: 3b. Same thing, different ID: applicants sharing a name and city under different BENs
select upper(name) as name, upper(city) as city, state, count(*) as bens, string_agg(billed_entity_number, ', ') as ben_list
from applicants
group by upper(name), upper(city), state
having count(*) > 1
order by bens desc, name;

-- name: 3c. Same thing, different ID: one applicant filing the same nickname twice in a funding year
select ap.name, a.funding_year, a.form_nickname, count(*) as applications,
       string_agg(a.application_number || ' (' || a.status || ')', ', ') as application_numbers
from applications a join applicants ap on ap.applicant_id = a.applicant_id
where a.form_nickname is not null
group by ap.applicant_id, ap.name, a.funding_year, a.form_nickname
having count(*) > 1
order by applications desc, ap.name;

-- name: 4. Out-of-range or inconsistent values
select 'certified in the future' as check_name, count(*) as rows_found
  from applications where certified_at > now()
union all select 'funding year outside 2026-2027', count(*)
  from applications where funding_year not between 2026 and 2027
union all select 'bidding window shorter than 28 days', count(*)
  from applications where allowable_contract_date < (certified_at at time zone 'America/New_York')::date + 28
union all select 'quantity of 0', count(*)
  from service_requests where quantity = 0
union all select 'unit given without a quantity', count(*)
  from service_requests where quantity is null and unit is not null
union all select 'Category 1 line naming a manufacturer', count(*)
  from service_requests where service_category = 'Category 1' and manufacturer is not null
union all select 'canceled form with line items', count(*)
  from service_requests sr join applications a on a.application_id = sr.application_id where a.status = 'Canceled'
union all select 'attachment count differs from stored documents', count(*)
  from service_requests sr
  where sr.rfp_attachment_count <> (select count(*) from rfp_documents d where d.service_request_id = sr.service_request_id);

-- name: 5. Orphans and childless parents
select 'service requests without an application' as check_name, count(*) as rows_found
  from service_requests sr left join applications a on a.application_id = sr.application_id where a.application_id is null
union all select 'RFP documents without a service request', count(*)
  from rfp_documents d left join service_requests sr on sr.service_request_id = d.service_request_id
  where sr.service_request_id is null
union all select 'applications without line items (certified)', count(*)
  from applications a where a.status = 'Certified'
  and not exists (select 1 from service_requests sr where sr.application_id = a.application_id)
union all select 'applications without line items (canceled)', count(*)
  from applications a where a.status = 'Canceled'
  and not exists (select 1 from service_requests sr where sr.application_id = a.application_id)
union all select 'applicants without applications', count(*)
  from applicants ap where not exists (select 1 from applications a where a.applicant_id = ap.applicant_id);

-- name: 6a. Fairness: records per state
select ap.state, count(distinct ap.applicant_id) as applicants, count(*) as applications,
       round(100.0 * count(*) / sum(count(*)) over (), 1) as pct_of_applications
from applications a join applicants ap on ap.applicant_id = a.applicant_id
group by ap.state order by applications desc;

-- name: 6b. Fairness: records per applicant type
select ap.applicant_type, count(distinct ap.applicant_id) as applicants, count(*) as applications
from applications a join applicants ap on ap.applicant_id = a.applicant_id
group by ap.applicant_type order by applications desc;

-- name: 6c. Fairness: how much evidence exists per applicant
select applications_filed, count(*) as applicants,
       round(100.0 * count(*) / sum(count(*)) over (), 1) as pct_of_applicants
from (select applicant_id, count(*) as applications_filed from applications group by applicant_id) per_applicant
group by applications_filed order by applications_filed;

-- name: 6d. Fairness: the near-Alva town list compared with everything else
select case when (upper(ap.city), ap.state) in (
            values ('ALVA','OK'),('WAYNOKA','OK'),('CHEROKEE','OK'),('BURLINGTON','OK'),('ALINE','OK'),
                   ('FAIRVIEW','OK'),('ENID','OK'),('KREMLIN','OK'),('LAHOMA','OK'),('DRUMMOND','OK'),
                   ('RINGWOOD','OK'),('WOODWARD','OK'),('BUFFALO','OK'),('SEILING','OK'),
                   ('MEDICINE LODGE','KS'),('KIOWA','KS'),('COLDWATER','KS'))
            then 'near-Alva town list' else 'rest of OK and KS' end as area,
       count(distinct ap.applicant_id) as applicants, count(*) as applications
from applications a join applicants ap on ap.applicant_id = a.applicant_id
group by 1 order by 1;
