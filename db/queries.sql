-- db/queries.sql: business questions answered with SQL (Milestone 2).
--
-- Each question comes from docs/baseline_log.md, where I wished I knew who is requesting
-- what equipment, where, and when, without sifting through USAC's raw data by hand.
--
-- Coverage: JOINs in Q1, Q2, Q5 | GROUP BY in Q2, Q3, Q4 | time filters in Q1, Q4, Q5 | surprise in Q3
-- Counts are of applications, not API rows (see docs/data_quality.md, Finding 2).


-- Q1. Which Form 470s are still open for bidding right now, and how many days do I have
--     before each one's allowable contract date?
--     (Baseline log: contacting a school after its deadline wastes time and looks careless.)
select
    ap.name                                   as applicant,
    ap.city,
    ap.state,
    a.application_number,
    a.form_nickname,
    a.allowable_contract_date,
    a.allowable_contract_date - current_date  as days_left
from applications a
join applicants ap on ap.applicant_id = a.applicant_id
where a.status = 'Certified'
  and a.allowable_contract_date >= current_date
order by a.allowable_contract_date, ap.name;


-- Q2. What Category 2 equipment (switches, Wi-Fi, cabling ...) do applications ask for most,
--     and is demand for each item higher this funding year or last?
--     (Baseline log: "I'd like to know more about their IT needs and their current equipment.")
select
    sr.function,
    count(distinct a.application_id) filter (where a.funding_year = 2026) as applications_fy2026,
    count(distinct a.application_id) filter (where a.funding_year = 2027) as applications_fy2027,
    count(distinct a.application_id)                                       as applications_total
from service_requests sr
join applications a on a.application_id = sr.application_id
where sr.service_category = 'Category 2'
group by sr.function
order by applications_total desc
limit 15;


-- Q3. How many applications are filed through an E-Rate consultant, and which consultants
--     file the most?
--     SURPRISE (DRAFT: confirm against your results and rewrite in your own words):
--     I assumed I'd be pitching to schools directly. In the Nov 11 pull, about 87% of applications
--     named a consultant, and a single firm filed roughly a quarter of all applications in OK and KS.
--     The consultant, not the school, may be the first person an MSP needs to know.
select
    coalesce(split_part(trim(both '{}' from a.consulting_firm_data), '|', 1), '(no consultant)')
        as consultant,
    count(*)                                              as applications,
    round(100.0 * count(*) / sum(count(*)) over (), 1)    as percent_of_applications
from applications a
group by 1
order by applications desc;


-- Q4. In which months are Form 470s certified? When should I be watching for new bids?
--     (Baseline log: I search weekly; this shows which weeks actually matter.)
--     Uses the one complete season in the data, funding year 2026, in US Eastern time.
select
    to_char(date_trunc('month', a.certified_at at time zone 'America/New_York'), 'YYYY-MM') as month_certified,
    count(*) as applications
from applications a
where a.funding_year = 2026
group by 1
order by 1;


-- Q5. Which applicants near Alva filed a Form 470 in the last 12 months, and what did they ask for?
--     The data has no coordinates, so "about an hour from Alva" is a list of towns.
--     DRAFT list: edit it to match the towns you actually serve.
select
    ap.name                                     as applicant,
    ap.city,
    ap.state,
    a.application_number,
    a.certified_at::date                        as certified,
    a.allowable_contract_date,
    string_agg(distinct sr.function, '; ')      as requested
from applicants ap
join applications a       on a.applicant_id = ap.applicant_id
left join service_requests sr on sr.application_id = a.application_id
where (upper(ap.city), ap.state) in (
        values ('ALVA', 'OK'), ('WAYNOKA', 'OK'), ('CHEROKEE', 'OK'), ('BURLINGTON', 'OK'),
               ('ALINE', 'OK'), ('FAIRVIEW', 'OK'), ('ENID', 'OK'), ('KREMLIN', 'OK'),
               ('LAHOMA', 'OK'), ('DRUMMOND', 'OK'), ('RINGWOOD', 'OK'), ('WOODWARD', 'OK'),
               ('BUFFALO', 'OK'), ('SEILING', 'OK'),
               ('MEDICINE LODGE', 'KS'), ('KIOWA', 'KS'), ('COLDWATER', 'KS'))
  and a.certified_at >= now() - interval '12 months'
group by ap.name, ap.city, ap.state, a.application_number, a.certified_at, a.allowable_contract_date
order by a.certified_at desc;
